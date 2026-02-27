"""
Execution Agent — Çoklu TP destekli emir uygulayıcı
- Strateji gücüne göre otomatik tek veya çoklu TP kararı
- Çoklu TP: %33/%33/%34 kısmi kapatma
- SL/TP izleme
"""
import asyncio
import os
import random
from datetime import datetime

from utils.state import SharedState, Position
from utils.logger import setup_logger

logger = setup_logger("ExecutionAgent")

INITIAL_CAPITAL = 1000.0


def decide_tp_levels(price: float, direction: str, confidence: float,
                     rsi: float, macd: float, macd_sig: float,
                     sl_pct: float, tp_pct: float) -> tuple:
    """
    Strateji gücüne ve indikatörlere göre karar ver:
    - Yüksek güven + güçlü momentum → çoklu TP (3 kademe)
    - Orta güven → 2 kademe TP
    - Düşük/normal güven → tek TP
    Döndürür: (take_profit_levels: list, tp_label: str)
    """
    momentum_strong = abs(macd - macd_sig) > abs(macd_sig) * 0.5 if macd_sig else False
    rsi_extreme = rsi < 25 or rsi > 75

    # Çoklu TP kriterleri
    use_multi = confidence >= 0.72 and (momentum_strong or rsi_extreme)
    use_double = confidence >= 0.62 and not use_multi

    if direction == "buy":
        if use_multi:
            # 3 kademe: %1x, %1.8x, %3x tp_pct
            return [
                round(price * (1 + tp_pct * 1.0), 8),
                round(price * (1 + tp_pct * 1.8), 8),
                round(price * (1 + tp_pct * 3.0), 8),
            ], "3x-TP"
        elif use_double:
            return [
                round(price * (1 + tp_pct * 1.0), 8),
                round(price * (1 + tp_pct * 2.0), 8),
            ], "2x-TP"
        else:
            return [round(price * (1 + tp_pct), 8)], "1x-TP"
    else:  # sell/short
        if use_multi:
            return [
                round(price * (1 - tp_pct * 1.0), 8),
                round(price * (1 - tp_pct * 1.8), 8),
                round(price * (1 - tp_pct * 3.0), 8),
            ], "3x-TP"
        elif use_double:
            return [
                round(price * (1 - tp_pct * 1.0), 8),
                round(price * (1 - tp_pct * 2.0), 8),
            ], "2x-TP"
        else:
            return [round(price * (1 - tp_pct), 8)], "1x-TP"


def generate_ai_summary(symbol: str, direction: str, indicators: dict,
                         strategy: str, tp_label: str) -> tuple:
    rsi = indicators.get("rsi", 50)
    macd = indicators.get("macd", 0)
    macd_sig = indicators.get("macd_signal", 0)
    bb_lower = indicators.get("bb_lower", 0)
    bb_upper = indicators.get("bb_upper", 0)
    price = indicators.get("price", 0)
    change = indicators.get("change_24h", 0)
    mom = indicators.get("momentum_1m", 0)

    reasons = []
    summary_parts = []

    if direction == "buy":
        if rsi < 30:
            reasons.append(f"RSI aşırı satım ({rsi:.1f})")
            summary_parts.append(f"RSI {rsi:.1f} ile güçlü aşırı satım sinyali")
        elif rsi < 40:
            reasons.append(f"RSI düşük ({rsi:.1f})")
        if macd > macd_sig and macd > 0:
            reasons.append("MACD yukarı kesiş")
            summary_parts.append(f"MACD ({macd:.5f}) sinyal üzerinde")
        if bb_lower > 0 and price < bb_lower * 1.01:
            reasons.append("BB alt kırılım")
            summary_parts.append("Bollinger alt bandı kırılımı — dip alım")
        if change > 2:
            reasons.append(f"24s artış ({change:+.1f}%)")
        if mom > 0.1:
            summary_parts.append(f"Momentum pozitif ({mom:+.3f}%)")
    else:
        if rsi > 70:
            reasons.append(f"RSI aşırı alım ({rsi:.1f})")
            summary_parts.append(f"RSI {rsi:.1f} ile aşırı alım")
        elif rsi > 60:
            reasons.append(f"RSI yüksek ({rsi:.1f})")
        if macd < macd_sig and macd < 0:
            reasons.append("MACD aşağı kesiş")
            summary_parts.append(f"MACD ({macd:.5f}) sinyal altında")
        if bb_upper > 0 and price > bb_upper * 0.99:
            reasons.append("BB üst kırılım")
            summary_parts.append("Bollinger üst bandı kırılımı — zirve satış")
        if change < -2:
            reasons.append(f"24s düşüş ({change:+.1f}%)")

    reason_str = " | ".join(reasons) if reasons else f"{strategy} sinyali"
    ai_str = ". ".join(summary_parts) if summary_parts else f"{strategy} stratejisi"
    ai_str += f". TP Stratejisi: {tp_label}."
    return reason_str, ai_str


class ExecutionAgent:
    def __init__(self, state: SharedState):
        self.state = state
        self.processed_signals: set = set()
        self.mode = "PAPER"

    def _position_size(self, price: float) -> float:
        risk_usd = INITIAL_CAPITAL * self.state.settings.risk_pct
        return round(risk_usd / price, 8)

    async def _paper_execute(self, symbol: str, direction: str, price: float,
                              signal_reason: str, indicators: dict, strategy: str,
                              confidence: float):
        sl_pct = self.state.settings.stop_loss_pct
        tp_pct = self.state.settings.take_profit_pct
        rsi = indicators.get("rsi", 50)
        macd = indicators.get("macd", 0)
        macd_sig = indicators.get("macd_signal", 0)

        if direction == "buy":
            if symbol not in self.state.positions:
                if len(self.state.positions) >= self.state.settings.max_positions:
                    return
                qty = self._position_size(price)
                sl = round(price * (1 - sl_pct), 8)
                tp_levels, tp_label = decide_tp_levels(
                    price, direction, confidence, rsi, macd, macd_sig, sl_pct, tp_pct
                )
                reason, ai_summary = generate_ai_summary(
                    symbol, direction, indicators, strategy, tp_label
                )
                pos = Position(
                    symbol=symbol, side="long", qty=qty,
                    entry_price=price, current_price=price,
                    stop_loss=sl,
                    take_profit=tp_levels[0],
                    take_profit_levels=tp_levels,
                    tp_hit_count=0,
                    value_usd=round(qty * price, 4),
                    reason=reason, ai_summary=ai_summary,
                    indicators_at_open=indicators,
                )
                await self.state.open_position(pos)
                logger.info(f"📝 [PAPER] LONG {symbol} @ ${price:.4f} | SL:${sl:.4f} | {tp_label}: {tp_levels}")

        elif direction == "sell":
            if symbol in self.state.positions:
                pnl = await self.state.close_position(symbol, price, "SIGNAL")
                logger.info(f"📝 [PAPER] CLOSE {symbol} @ ${price:.4f} | PnL=${pnl:+.4f}")

    async def _check_stop_take(self):
        for symbol, pos in list(self.state.positions.items()):
            market = self.state.market_data.get(symbol, {})
            cur = market.get("price", 0)
            if cur <= 0:
                continue
            pos.current_price = cur
            pos.pnl = (cur - pos.entry_price) * pos.qty if pos.side == "long" else (pos.entry_price - cur) * pos.qty
            pos.pnl_pct = (pos.pnl / pos.value_usd * 100) if pos.value_usd else 0

            if pos.side == "long":
                # SL kontrolü
                if cur <= pos.stop_loss:
                    pnl = await self.state.close_position(symbol, cur, "SL")
                    logger.warning(f"🛑 SL HIT {symbol} @ ${cur:.4f} | PnL=${pnl:+.4f}")
                    continue

                # Çoklu TP kontrolü
                tp_levels = pos.take_profit_levels
                if tp_levels:
                    next_idx = pos.tp_hit_count
                    if next_idx < len(tp_levels) and cur >= tp_levels[next_idx]:
                        tp_label = f"TP{next_idx + 1}"
                        is_last = next_idx == len(tp_levels) - 1
                        if is_last:
                            # Son TP → tamamını kapat
                            pnl = await self.state.close_position(symbol, cur, tp_label)
                            logger.info(f"🎯 {tp_label} (FINAL) HIT {symbol} @ ${cur:.4f} | PnL=${pnl:+.4f}")
                        else:
                            # Kısmi kapat (%50 ilk TP, %50 kalanı bekle)
                            ratio = 0.5 if len(tp_levels) == 2 else 0.33
                            pnl = await self.state.partial_close_position(symbol, cur, ratio, tp_label)
                            # SL'yi giriş fiyatına çek (breakeven)
                            pos.stop_loss = pos.entry_price
                            logger.info(f"🎯 {tp_label} HIT {symbol} @ ${cur:.4f} | Kısmi PnL=${pnl:+.4f} | SL→BE")
                else:
                    # Tekli TP
                    if cur >= pos.take_profit:
                        pnl = await self.state.close_position(symbol, cur, "TP")
                        logger.info(f"🎯 TP HIT {symbol} @ ${cur:.4f} | PnL=${pnl:+.4f}")

    async def run(self, shutdown: asyncio.Event):
        logger.info(f"⚡ Execution Agent başlatıldı | Mod: {self.mode} | Sermaye: ${INITIAL_CAPITAL}")
        while not shutdown.is_set():
            try:
                if not self.state.bot_running or self.state.bot_paused:
                    await asyncio.sleep(2)
                    continue

                await self._check_stop_take()

                signals = await self.state.get_signals()
                for sig in signals:
                    sig_id = f"{sig.symbol}_{sig.direction}_{sig.timestamp.strftime('%H%M%S')}"
                    if sig_id in self.processed_signals:
                        continue
                    self.processed_signals.add(sig_id)

                    if sig.confidence < self.state.settings.min_confidence:
                        continue

                    market = self.state.market_data.get(sig.symbol, {})
                    price = market.get("price", 0)
                    if price <= 0:
                        continue

                    await self._paper_execute(
                        sig.symbol, sig.direction, price,
                        sig.reason, market, sig.strategy, sig.confidence
                    )

                if len(self.processed_signals) > 1000:
                    self.processed_signals = set(list(self.processed_signals)[-500:])

                await self.state.heartbeat("ExecutionAgent")

            except Exception as e:
                logger.error(f"Execution hatası: {e}", exc_info=True)

            await asyncio.sleep(self.state.settings.exec_interval)

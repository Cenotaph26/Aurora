"""
Execution Agent — Gelişmiş Emir Uygulayıcı
- SL/TP ile pozisyon açma
- AI özet üretimi
- Açılış sebebi loglama
- Bot pause/stop kontrolü
"""
import asyncio
import os
import time
from datetime import datetime

from utils.state import SharedState, Position
from utils.logger import setup_logger

logger = setup_logger("ExecutionAgent")

INITIAL_CAPITAL = 1000.0

# AI özetleri üretir (gerçek AI API'si olmadan kural tabanlı)
def generate_ai_summary(symbol: str, direction: str, indicators: dict, strategy: str) -> tuple:
    """(reason, ai_summary) döndürür"""
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
            summary_parts.append(f"RSI {rsi:.1f} ile güçlü aşırı satım sinyali — geri dönüş beklentisi")
        elif rsi < 40:
            reasons.append(f"RSI düşük ({rsi:.1f})")
            summary_parts.append(f"RSI {rsi:.1f} ile satım bölgesine yakın")
        if macd > macd_sig and macd > 0:
            reasons.append("MACD yukarı kesiş")
            summary_parts.append(f"MACD ({macd:.5f}) sinyal üzerinde — yukarı momentum doğrulandı")
        if bb_lower > 0 and price < bb_lower * 1.01:
            reasons.append("Bollinger alt bandı kırılımı")
            summary_parts.append("Fiyat Bollinger alt bandının altında — dip alım fırsatı")
        if change > 2:
            reasons.append(f"24s güçlü artış ({change:+.1f}%)")
        if mom > 0.1:
            summary_parts.append(f"Kısa vadeli momentum pozitif ({mom:+.3f}%)")

    elif direction == "sell":
        if rsi > 70:
            reasons.append(f"RSI aşırı alım ({rsi:.1f})")
            summary_parts.append(f"RSI {rsi:.1f} ile güçlü aşırı alım sinyali — düzeltme beklentisi")
        elif rsi > 60:
            reasons.append(f"RSI yüksek ({rsi:.1f})")
        if macd < macd_sig and macd < 0:
            reasons.append("MACD aşağı kesiş")
            summary_parts.append(f"MACD ({macd:.5f}) sinyal altında — aşağı momentum")
        if bb_upper > 0 and price > bb_upper * 0.99:
            reasons.append("Bollinger üst bandı kırılımı")
            summary_parts.append("Fiyat Bollinger üst bandının üzerinde — zirve satış fırsatı")
        if change < -2:
            reasons.append(f"24s güçlü düşüş ({change:+.1f}%)")

    reason_str = " | ".join(reasons) if reasons else f"{strategy} sinyali"
    ai_str = ". ".join(summary_parts) if summary_parts else f"{strategy} stratejisi {direction} sinyali üretti"
    ai_str += f". Strateji: {strategy}. Güven: hesaplandı."

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
                              signal_reason: str, indicators: dict, strategy: str):
        sl_pct = self.state.settings.stop_loss_pct
        tp_pct = self.state.settings.take_profit_pct

        if direction == "buy":
            if symbol not in self.state.positions:
                if len(self.state.positions) >= self.state.settings.max_positions:
                    return
                qty = self._position_size(price)
                sl = round(price * (1 - sl_pct), 8)
                tp = round(price * (1 + tp_pct), 8)
                reason, ai_summary = generate_ai_summary(symbol, direction, indicators, strategy)
                pos = Position(
                    symbol=symbol, side="long", qty=qty,
                    entry_price=price, current_price=price,
                    stop_loss=sl, take_profit=tp,
                    value_usd=round(qty * price, 4),
                    reason=reason, ai_summary=ai_summary,
                    indicators_at_open=indicators,
                )
                await self.state.open_position(pos)
                logger.info(f"📝 [PAPER] LONG {symbol} @ ${price:.4f} | SL:${sl:.4f} TP:${tp:.4f}")

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
            pos.pnl = (cur - pos.entry_price) * pos.qty
            pos.pnl_pct = (pos.pnl / pos.value_usd * 100) if pos.value_usd else 0

            if pos.side == "long":
                if cur <= pos.stop_loss:
                    pnl = await self.state.close_position(symbol, cur, "SL")
                    logger.warning(f"🛑 SL HIT {symbol} @ ${cur:.4f} | PnL=${pnl:+.4f}")
                elif cur >= pos.take_profit:
                    pnl = await self.state.close_position(symbol, cur, "TP")
                    logger.info(f"🎯 TP HIT {symbol} @ ${cur:.4f} | PnL=${pnl:+.4f}")

    async def run(self, shutdown: asyncio.Event):
        logger.info(f"⚡ Execution Agent başlatıldı | Mod: {self.mode} | Sermaye: ${INITIAL_CAPITAL}")
        while not shutdown.is_set():
            try:
                # Bot durdurulmuşsa veya duraklatılmışsa işlem yapma
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
                        sig.reason, market, sig.strategy
                    )

                if len(self.processed_signals) > 500:
                    self.processed_signals = set(list(self.processed_signals)[-200:])

                await self.state.heartbeat("ExecutionAgent")

            except Exception as e:
                logger.error(f"Execution hatası: {e}", exc_info=True)

            await asyncio.sleep(self.state.settings.exec_interval)

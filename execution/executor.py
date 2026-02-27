"""
Execution Agent — Çoklu TP + duplicate pozisyon koruması
"""
import asyncio
import os
from datetime import datetime, timedelta
from utils.state import SharedState, Position
from utils.logger import setup_logger

logger = setup_logger("ExecutionAgent")
INITIAL_CAPITAL = 1000.0


def decide_tp_levels(price, direction, confidence, rsi, macd, macd_sig, sl_pct, tp_pct):
    momentum_strong = abs(macd - macd_sig) / max(abs(macd_sig), 1e-9) > 0.3
    rsi_extreme = rsi < 28 or rsi > 72
    use_multi = confidence >= 0.68 and (momentum_strong or rsi_extreme)
    use_double = confidence >= 0.55 and not use_multi

    if direction == "buy":
        if use_multi:
            return [round(price*(1+tp_pct), 8), round(price*(1+tp_pct*2), 8), round(price*(1+tp_pct*3.5), 8)], "3x-TP"
        elif use_double:
            return [round(price*(1+tp_pct), 8), round(price*(1+tp_pct*2.2), 8)], "2x-TP"
        else:
            return [round(price*(1+tp_pct), 8)], "1x-TP"
    else:
        if use_multi:
            return [round(price*(1-tp_pct), 8), round(price*(1-tp_pct*2), 8), round(price*(1-tp_pct*3.5), 8)], "3x-TP"
        elif use_double:
            return [round(price*(1-tp_pct), 8), round(price*(1-tp_pct*2.2), 8)], "2x-TP"
        else:
            return [round(price*(1-tp_pct), 8)], "1x-TP"


def generate_ai_summary(symbol, direction, indicators, strategy, tp_label):
    rsi   = indicators.get("rsi", 50)
    macd  = indicators.get("macd", 0)
    msig  = indicators.get("macd_signal", 0)
    price = indicators.get("price", 0)
    chg   = indicators.get("change_24h", 0)
    mom   = indicators.get("momentum_1m", 0)
    vol   = indicators.get("volume_24h", 0)
    parts = []
    if direction == "buy":
        if rsi < 35:  parts.append(f"RSI {rsi:.0f} aşırı satım")
        if macd > msig: parts.append("MACD yukarı")
        if mom > 0:   parts.append(f"Momentum +{mom:.2f}%")
        if vol > 1e6: parts.append(f"Hacim ${vol/1e6:.1f}M")
    else:
        if rsi > 65:  parts.append(f"RSI {rsi:.0f} aşırı alım")
        if macd < msig: parts.append("MACD aşağı")
        if mom < 0:   parts.append(f"Momentum {mom:.2f}%")
    reason = " | ".join(parts) or f"{strategy} sinyali"
    summary = reason + f". TP: {tp_label}."
    return reason, summary


class ExecutionAgent:
    def __init__(self, state: SharedState):
        self.state = state
        self.processed_signals: set = set()
        # Son işlem zamanı per sembol — çok sık aynı coinde işlem açmasın
        self.last_trade_time: dict = {}
        self.mode = "PAPER"

    def _position_size(self, price):
        risk_usd = INITIAL_CAPITAL * self.state.settings.risk_pct
        return round(risk_usd / price, 8)

    def _can_trade(self, symbol) -> bool:
        """Aynı sembolde 5 dakikadan önce tekrar işlem açmasın"""
        last = self.last_trade_time.get(symbol)
        if last and (datetime.utcnow() - last).seconds < 300:
            return False
        return True

    async def _paper_execute(self, symbol, direction, price, signal_reason, indicators, strategy, confidence):
        sl_pct = self.state.settings.stop_loss_pct
        tp_pct = self.state.settings.take_profit_pct
        rsi    = indicators.get("rsi", 50)
        macd   = indicators.get("macd", 0)
        msig   = indicators.get("macd_signal", 0)

        if direction == "buy":
            if symbol in self.state.positions:
                return  # Zaten long var
            if len(self.state.positions) >= self.state.settings.max_positions:
                return
            if not self._can_trade(symbol):
                return
            qty = self._position_size(price)
            sl  = round(price * (1 - sl_pct), 8)
            tp_levels, tp_label = decide_tp_levels(price, direction, confidence, rsi, macd, msig, sl_pct, tp_pct)
            reason, ai_summary  = generate_ai_summary(symbol, direction, indicators, strategy, tp_label)
            pos = Position(
                symbol=symbol, side="long", qty=qty,
                entry_price=price, current_price=price,
                stop_loss=sl, take_profit=tp_levels[0],
                take_profit_levels=tp_levels, tp_hit_count=0,
                value_usd=round(qty * price, 4),
                reason=reason, ai_summary=ai_summary,
                indicators_at_open={**indicators, "leverage": 1},
            )
            await self.state.open_position(pos)
            self.last_trade_time[symbol] = datetime.utcnow()
            logger.info(f"📝 LONG {symbol} @ ${price:.6f} | conf={confidence:.2f} | {tp_label} | SL={sl:.6f}")

        elif direction == "sell":
            if symbol in self.state.positions:
                pnl = await self.state.close_position(symbol, price, "SIGNAL")
                logger.info(f"📝 CLOSE {symbol} @ ${price:.6f} | PnL=${pnl:+.4f}")
            else:
                # Short pozisyon aç
                if len(self.state.positions) >= self.state.settings.max_positions:
                    return
                if not self._can_trade(symbol):
                    return
                qty = self._position_size(price)
                sl  = round(price * (1 + sl_pct), 8)
                tp_levels, tp_label = decide_tp_levels(price, direction, confidence, rsi, macd, msig, sl_pct, tp_pct)
                reason, ai_summary  = generate_ai_summary(symbol, direction, indicators, strategy, tp_label)
                pos = Position(
                    symbol=symbol, side="short", qty=qty,
                    entry_price=price, current_price=price,
                    stop_loss=sl, take_profit=tp_levels[0],
                    take_profit_levels=tp_levels, tp_hit_count=0,
                    value_usd=round(qty * price, 4),
                    reason=reason, ai_summary=ai_summary,
                    indicators_at_open={**indicators, "leverage": 1},
                )
                await self.state.open_position(pos)
                self.last_trade_time[symbol] = datetime.utcnow()
                logger.info(f"📝 SHORT {symbol} @ ${price:.6f} | conf={confidence:.2f} | {tp_label} | SL={sl:.6f}")

    async def _check_stop_take(self):
        for symbol, pos in list(self.state.positions.items()):
            market = self.state.market_data.get(symbol, {})
            cur    = market.get("price", 0)
            if cur <= 0:
                continue
            pos.current_price = cur
            if pos.side == "long":
                pos.pnl = (cur - pos.entry_price) * pos.qty
            else:
                pos.pnl = (pos.entry_price - cur) * pos.qty
            pos.pnl_pct = (pos.pnl / pos.value_usd * 100) if pos.value_usd else 0

            if pos.side == "long":
                if cur <= pos.stop_loss:
                    pnl = await self.state.close_position(symbol, cur, "SL")
                    logger.warning(f"🛑 SL {symbol} @ ${cur:.6f} PnL=${pnl:+.4f}")
                    continue
                tp_levels = pos.take_profit_levels
                if tp_levels:
                    idx = pos.tp_hit_count
                    if idx < len(tp_levels) and cur >= tp_levels[idx]:
                        label = f"TP{idx+1}"
                        if idx == len(tp_levels) - 1:
                            pnl = await self.state.close_position(symbol, cur, label)
                            logger.info(f"🎯 {label} FINAL {symbol} @ ${cur:.6f} PnL=${pnl:+.4f}")
                        else:
                            ratio = 0.5 if len(tp_levels) == 2 else 0.33
                            pnl = await self.state.partial_close_position(symbol, cur, ratio, label)
                            pos.stop_loss = pos.entry_price  # breakeven'e çek
                            logger.info(f"🎯 {label} kısmi {symbol} @ ${cur:.6f} PnL=${pnl:+.4f} → SL=BE")
                else:
                    if cur >= pos.take_profit:
                        pnl = await self.state.close_position(symbol, cur, "TP")
                        logger.info(f"🎯 TP {symbol} @ ${cur:.6f} PnL=${pnl:+.4f}")
            else:  # short
                if cur >= pos.stop_loss:
                    pnl = await self.state.close_position(symbol, cur, "SL")
                    logger.warning(f"🛑 SL SHORT {symbol} @ ${cur:.6f} PnL=${pnl:+.4f}")
                    continue
                tp_levels = pos.take_profit_levels
                if tp_levels:
                    idx = pos.tp_hit_count
                    if idx < len(tp_levels) and cur <= tp_levels[idx]:
                        label = f"TP{idx+1}"
                        if idx == len(tp_levels) - 1:
                            pnl = await self.state.close_position(symbol, cur, label)
                            logger.info(f"🎯 {label} FINAL SHORT {symbol} @ ${cur:.6f} PnL=${pnl:+.4f}")
                        else:
                            ratio = 0.5 if len(tp_levels) == 2 else 0.33
                            pnl = await self.state.partial_close_position(symbol, cur, ratio, label)
                            pos.stop_loss = pos.entry_price
                            logger.info(f"🎯 {label} kısmi SHORT {symbol} PnL=${pnl:+.4f}")
                else:
                    if cur <= pos.take_profit:
                        pnl = await self.state.close_position(symbol, cur, "TP")
                        logger.info(f"🎯 TP SHORT {symbol} @ ${cur:.6f} PnL=${pnl:+.4f}")

    async def run(self, shutdown: asyncio.Event):
        logger.info(f"⚡ Execution Agent başlatıldı | ${INITIAL_CAPITAL}")
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
                    price  = market.get("price", 0)
                    if price <= 0:
                        continue

                    await self._paper_execute(
                        sig.symbol, sig.direction, price,
                        sig.reason, market, sig.strategy, sig.confidence
                    )

                if len(self.processed_signals) > 2000:
                    self.processed_signals = set(list(self.processed_signals)[-500:])

                await self.state.heartbeat("ExecutionAgent")

            except Exception as e:
                logger.error(f"Execution hatası: {e}", exc_info=True)

            await asyncio.sleep(self.state.settings.exec_interval)

"""
Execution Agent v5 — Tüm hatalar düzeltildi
DÜZELTMELER:
1. Signal ID artık sembol+yön+dakika (saniye değil) → duplicate YOK
2. Cooldown timedelta kullanıyor → çalışıyor
3. Position size: mevcut sermayeye göre (sabit 1000 değil)
4. Capital yeterliliği kontrolü eklendi
5. Short PnL hesabı düzeltildi
"""
import asyncio
import os
from datetime import datetime, timedelta
from utils.state import SharedState, Position
from utils.logger import setup_logger

logger = setup_logger("ExecutionAgent")


class ExecutionAgent:
    def __init__(self, state: SharedState):
        self.state = state
        self.processed_signals: set = set()
        self.symbol_last_trade: dict = {}  # symbol → datetime

    def _signal_id(self, sig) -> str:
        # Dakika bazlı ID — aynı dakikada aynı yön tekrar işlenmiyor
        return f"{sig.symbol}_{sig.direction}_{sig.timestamp.strftime('%Y%m%d%H%M')}"

    def _cooldown_ok(self, symbol: str) -> bool:
        last = self.symbol_last_trade.get(symbol)
        if not last:
            return True
        cooldown_min = int(os.getenv("TRADE_COOLDOWN_MIN", "60"))
        return (datetime.utcnow() - last) >= timedelta(minutes=cooldown_min)

    def _get_position_value(self) -> float:
        """Mevcut sermayenin risk_pct kadarı"""
        available = max(self.state.capital, 0)
        return round(available * self.state.settings.risk_pct, 4)

    def _tp_levels(self, price: float, direction: str, confidence: float) -> tuple:
        tp_pct = self.state.settings.take_profit_pct
        if confidence >= 0.78:
            n = 3
        elif confidence >= 0.62:
            n = 2
        else:
            n = 1
        if direction == "buy":
            levels = [round(price * (1 + tp_pct * (i + 1)), 8) for i in range(n)]
        else:
            levels = [round(price * (1 - tp_pct * (i + 1)), 8) for i in range(n)]
        return levels, f"{n}x-TP"

    async def _open(self, symbol: str, side: str, price: float, confidence: float,
                    indicators: dict, reason: str):
        # Kontroller
        if symbol in self.state.positions:
            return
        if len(self.state.positions) >= self.state.settings.max_positions:
            return
        if not self._cooldown_ok(symbol):
            return

        pos_value = self._get_position_value()
        if pos_value < 1.0 or self.state.capital < pos_value:
            logger.warning(f"Yetersiz sermaye: ${self.state.capital:.2f}")
            return

        sl_pct = self.state.settings.stop_loss_pct
        qty = round(pos_value / price, 8)

        if side == "long":
            sl = round(price * (1 - sl_pct), 8)
        else:
            sl = round(price * (1 + sl_pct), 8)

        tp_levels, tp_label = self._tp_levels(price, "buy" if side == "long" else "sell", confidence)

        lev = self.state.settings.leverage
        ai_summary = f"{reason} [{tp_label}] conf={confidence:.0%}"

        pos = Position(
            symbol=symbol, side=side, qty=qty,
            entry_price=price, current_price=price,
            stop_loss=sl,
            take_profit=tp_levels[0],
            take_profit_levels=tp_levels,
            tp_hit_count=0,
            value_usd=pos_value,
            reason=reason,
            ai_summary=ai_summary,
            indicators_at_open={**indicators, "leverage": lev},
        )
        await self.state.open_position(pos)
        self.symbol_last_trade[symbol] = datetime.utcnow()
        logger.info(f"{'📈' if side=='long' else '📉'} {side.upper()} {symbol} @${price:.6f} conf={confidence:.2f} {tp_label} SL={sl:.6f}")

    async def _check_sl_tp(self):
        for symbol, pos in list(self.state.positions.items()):
            mkt = self.state.market_data.get(symbol, {})
            cur = mkt.get("price", 0)
            if cur <= 0:
                continue

            pos.current_price = cur
            if pos.side == "long":
                pos.pnl = (cur - pos.entry_price) * pos.qty
            else:
                pos.pnl = (pos.entry_price - cur) * pos.qty
            pos.pnl_pct = (pos.pnl / pos.value_usd * 100) if pos.value_usd else 0

            # ── LONG ──
            if pos.side == "long":
                if cur <= pos.stop_loss:
                    pnl = await self.state.close_position(symbol, cur, "SL")
                    logger.warning(f"🛑 SL LONG {symbol} PnL=${pnl:+.4f}")
                    continue
                tps = pos.take_profit_levels or [pos.take_profit]
                idx = pos.tp_hit_count
                if idx < len(tps) and cur >= tps[idx]:
                    if idx == len(tps) - 1:
                        pnl = await self.state.close_position(symbol, cur, f"TP{idx+1}")
                        logger.info(f"🎯 TP{idx+1} FINAL LONG {symbol} PnL=${pnl:+.4f}")
                    else:
                        pnl = await self.state.partial_close_position(symbol, cur, 1/len(tps), f"TP{idx+1}")
                        pos.stop_loss = pos.entry_price
                        logger.info(f"🎯 TP{idx+1} kısmi {symbol} PnL=${pnl:+.4f} → BE")
            # ── SHORT ──
            else:
                if cur >= pos.stop_loss:
                    pnl = await self.state.close_position(symbol, cur, "SL")
                    logger.warning(f"🛑 SL SHORT {symbol} PnL=${pnl:+.4f}")
                    continue
                tps = pos.take_profit_levels or [pos.take_profit]
                idx = pos.tp_hit_count
                if idx < len(tps) and cur <= tps[idx]:
                    if idx == len(tps) - 1:
                        pnl = await self.state.close_position(symbol, cur, f"TP{idx+1}")
                        logger.info(f"🎯 TP{idx+1} FINAL SHORT {symbol} PnL=${pnl:+.4f}")
                    else:
                        pnl = await self.state.partial_close_position(symbol, cur, 1/len(tps), f"TP{idx+1}")
                        pos.stop_loss = pos.entry_price
                        logger.info(f"🎯 TP{idx+1} kısmi SHORT {symbol} PnL=${pnl:+.4f} → BE")

    async def run(self, shutdown: asyncio.Event):
        logger.info("⚡ Execution Agent v5 | Duplicate korumalı | Cooldown: 60dk")
        interval = int(os.getenv("EXEC_INTERVAL", "10"))

        while not shutdown.is_set():
            try:
                if not self.state.bot_running or self.state.bot_paused:
                    await asyncio.sleep(2)
                    continue

                await self._check_sl_tp()

                for sig in await self.state.get_signals():
                    sig_id = self._signal_id(sig)
                    if sig_id in self.processed_signals:
                        continue
                    self.processed_signals.add(sig_id)

                    if sig.confidence < self.state.settings.min_confidence:
                        continue

                    mkt   = self.state.market_data.get(sig.symbol, {})
                    price = mkt.get("price", 0)
                    if price <= 0:
                        continue

                    if sig.direction == "buy":
                        await self._open(sig.symbol, "long", price, sig.confidence, mkt, sig.reason)
                    elif sig.direction == "sell":
                        # Var olan long'u kapat
                        if sig.symbol in self.state.positions and self.state.positions[sig.symbol].side == "long":
                            await self.state.close_position(sig.symbol, price, "SIGNAL")
                        else:
                            await self._open(sig.symbol, "short", price, sig.confidence, mkt, sig.reason)

                # Temizlik
                if len(self.processed_signals) > 5000:
                    self.processed_signals = set(list(self.processed_signals)[-1000:])

                await self.state.heartbeat("ExecutionAgent")

            except Exception as e:
                logger.error(f"Execution hatası: {e}", exc_info=True)

            await asyncio.sleep(interval)

"""
Aurora AI — SharedState v5
DÜZELTMELER:
- leverage BotSettings'e eklendi
- max_positions default 5
- min_confidence default 0.60
- capital hiçbir zaman negatife gitmiyor
- analytics için win/loss streak, avg_pnl_win, avg_pnl_loss
"""
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class Position:
    symbol: str
    side: str
    qty: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    take_profit_levels: List[float] = field(default_factory=list)
    tp_hit_count: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    reason: str = ""
    ai_summary: str = ""
    indicators_at_open: dict = field(default_factory=dict)
    value_usd: float = 0.0


@dataclass
class ClosedPosition:
    symbol: str
    side: str
    qty: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    opened_at: datetime
    closed_at: datetime = field(default_factory=datetime.utcnow)
    close_reason: str = ""
    ai_summary: str = ""
    duration_sec: float = 0.0


@dataclass
class Signal:
    symbol: str
    direction: str
    confidence: float
    strategy: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    reason: str = ""
    indicators: dict = field(default_factory=dict)


class BotSettings:
    def __init__(self):
        self.min_confidence: float = 0.60
        self.risk_pct: float = 0.02        # her pozisyon sermayenin %2'si
        self.stop_loss_pct: float = 0.03
        self.take_profit_pct: float = 0.05
        self.market_interval: int = 30
        self.strategy_interval: int = 20
        self.exec_interval: int = 10
        self.max_positions: int = 5
        self.leverage: int = 1
        self.scan_batch: int = 50          # strateji her turda kaç coin tarasın

    def to_dict(self):
        return {k: getattr(self, k) for k in [
            "min_confidence", "risk_pct", "stop_loss_pct", "take_profit_pct",
            "market_interval", "strategy_interval", "exec_interval",
            "max_positions", "leverage", "scan_batch",
        ]}

    def update(self, data: dict):
        for k, v in data.items():
            if hasattr(self, k):
                try:
                    setattr(self, k, type(getattr(self, k))(v))
                except Exception:
                    pass


class SharedState:
    INITIAL_CAPITAL = 1000.0

    def __init__(self):
        self._lock = threading.Lock()
        self.market_data: Dict[str, dict] = {}
        self.signals: List[Signal] = []
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[ClosedPosition] = []
        self.rl_metrics: dict = {}

        self.capital = self.INITIAL_CAPITAL
        self.total_pnl: float = 0.0
        self.trade_count: int = 0
        self.win_count: int = 0

        # Analytics
        self.pnl_history: List[float] = [0.0]   # equity curve
        self.daily_pnl: Dict[str, float] = {}     # "YYYY-MM-DD" → pnl
        self.peak_equity: float = self.INITIAL_CAPITAL
        self.win_streak: int = 0
        self.loss_streak: int = 0
        self.current_streak: int = 0              # + kazanç, - kayıp
        self.total_win_pnl: float = 0.0
        self.total_loss_pnl: float = 0.0

        self.agent_heartbeats: Dict[str, datetime] = {}
        self.started_at: datetime = datetime.utcnow()
        self.bot_running: bool = True
        self.bot_paused: bool = False
        self.settings = BotSettings()
        self.system_log: List[dict] = []

    def _add_log(self, level: str, msg: str):
        with self._lock:
            self.system_log.append({"ts": datetime.utcnow().isoformat(), "level": level, "msg": msg})
            if len(self.system_log) > 300:
                self.system_log = self.system_log[-300:]

    async def update_market(self, symbol: str, data: dict):
        with self._lock:
            self.market_data[symbol] = {**data, "updated_at": datetime.utcnow().isoformat()}

    async def add_signal(self, signal: Signal):
        with self._lock:
            self.signals.append(signal)
            if len(self.signals) > 500:
                self.signals = self.signals[-500:]

    async def get_signals(self) -> List[Signal]:
        with self._lock:
            return list(self.signals)

    async def open_position(self, pos: Position):
        with self._lock:
            self.positions[pos.symbol] = pos
            self.trade_count += 1
            self.capital = max(0.0, self.capital - pos.value_usd)
            tps = " / ".join([f"${t:.6f}" for t in pos.take_profit_levels]) if pos.take_profit_levels else f"${pos.take_profit:.6f}"
            self.system_log.append({
                "ts": datetime.utcnow().isoformat(), "level": "TRADE",
                "msg": f"{'📈' if pos.side=='long' else '📉'} {pos.side.upper()} açıldı: {pos.symbol} @ ${pos.entry_price:.6f} | SL:${pos.stop_loss:.6f} | TP: {tps}"
            })

    async def close_position(self, symbol: str, exit_price: float, reason: str = "SIGNAL") -> float:
        with self._lock:
            if symbol not in self.positions:
                return 0.0
            pos = self.positions.pop(symbol)

            if pos.side == "long":
                pnl = (exit_price - pos.entry_price) * pos.qty
            else:
                pnl = (pos.entry_price - exit_price) * pos.qty

            pnl_pct = (pnl / pos.value_usd * 100) if pos.value_usd else 0
            self.total_pnl += pnl
            self.capital = max(0.0, self.capital + pos.value_usd + pnl)

            # Analytics
            today = datetime.utcnow().strftime("%Y-%m-%d")
            self.daily_pnl[today] = self.daily_pnl.get(today, 0.0) + pnl
            self.pnl_history.append(round(self.total_pnl, 4))
            if len(self.pnl_history) > 500:
                self.pnl_history = self.pnl_history[-500:]
            equity = self.capital
            if equity > self.peak_equity:
                self.peak_equity = equity

            if pnl > 0:
                self.win_count += 1
                self.total_win_pnl += pnl
                self.current_streak = max(0, self.current_streak) + 1
                self.win_streak = max(self.win_streak, self.current_streak)
            else:
                self.total_loss_pnl += pnl
                self.current_streak = min(0, self.current_streak) - 1
                self.loss_streak = max(self.loss_streak, -self.current_streak)

            dur = (datetime.utcnow() - pos.opened_at).total_seconds()
            closed = ClosedPosition(
                symbol=symbol, side=pos.side, qty=pos.qty,
                entry_price=pos.entry_price, exit_price=exit_price,
                pnl=round(pnl, 6), pnl_pct=round(pnl_pct, 2),
                opened_at=pos.opened_at, close_reason=reason,
                ai_summary=pos.ai_summary, duration_sec=dur,
            )
            self.closed_positions.append(closed)
            if len(self.closed_positions) > 500:
                self.closed_positions = self.closed_positions[-500:]

            icon = "🎯" if reason.startswith("TP") else "🛑" if reason == "SL" else "📉"
            self.system_log.append({
                "ts": datetime.utcnow().isoformat(), "level": "TRADE",
                "msg": f"{icon} {pos.side.upper()} kapatıldı: {symbol} [{reason}] PnL=${pnl:+.4f} ({pnl_pct:+.2f}%)"
            })
            if len(self.system_log) > 300:
                self.system_log = self.system_log[-300:]
            return pnl

    async def partial_close_position(self, symbol: str, exit_price: float, ratio: float, reason: str) -> float:
        with self._lock:
            if symbol not in self.positions:
                return 0.0
            pos = self.positions[symbol]
            close_qty = pos.qty * ratio
            close_value = close_qty * pos.entry_price

            if pos.side == "long":
                pnl = (exit_price - pos.entry_price) * close_qty
            else:
                pnl = (pos.entry_price - exit_price) * close_qty

            pos.qty -= close_qty
            pos.value_usd = max(0.0, pos.value_usd - close_value)
            pos.tp_hit_count += 1
            self.total_pnl += pnl
            self.capital = max(0.0, self.capital + close_value + pnl)

            today = datetime.utcnow().strftime("%Y-%m-%d")
            self.daily_pnl[today] = self.daily_pnl.get(today, 0.0) + pnl
            self.pnl_history.append(round(self.total_pnl, 4))
            if len(self.pnl_history) > 500:
                self.pnl_history = self.pnl_history[-500:]
            if pnl > 0:
                self.win_count += 1
                self.total_win_pnl += pnl
            else:
                self.total_loss_pnl += pnl

            self.system_log.append({
                "ts": datetime.utcnow().isoformat(), "level": "TRADE",
                "msg": f"🎯 Kısmi {pos.side.upper()}: {symbol} [{reason}] %{int(ratio*100)} PnL=${pnl:+.4f}"
            })
            if len(self.system_log) > 300:
                self.system_log = self.system_log[-300:]
            return pnl

    async def heartbeat(self, agent_name: str):
        with self._lock:
            self.agent_heartbeats[agent_name] = datetime.utcnow()

    def start_bot(self):
        with self._lock:
            self.bot_running = True
            self.bot_paused = False
            self.system_log.append({"ts": datetime.utcnow().isoformat(), "level": "INFO", "msg": "▶️ Bot başlatıldı"})

    def stop_bot(self):
        with self._lock:
            self.bot_running = False
            self._add_log("WARN", "⏹️ Bot durduruldu")

    def pause_bot(self):
        with self._lock:
            self.bot_paused = not self.bot_paused
            self._add_log("WARN", f"{'⏸️ Bot durakladı' if self.bot_paused else '▶️ Bot devam ediyor'}")

    def get_summary(self) -> dict:
        with self._lock:
            trades = self.trade_count
            wr = (self.win_count / trades * 100) if trades else 0
            open_pnl = sum(p.pnl for p in self.positions.values())
            equity = self.capital + open_pnl
            dd = ((self.peak_equity - equity) / self.peak_equity * 100) if self.peak_equity else 0
            avg_win  = (self.total_win_pnl  / self.win_count) if self.win_count else 0
            losses   = trades - self.win_count
            avg_loss = (self.total_loss_pnl / losses) if losses else 0
            rr = abs(avg_win / avg_loss) if avg_loss else 0
            return {
                "total_pnl": round(self.total_pnl, 4),
                "open_pnl": round(open_pnl, 4),
                "trade_count": trades,
                "win_count": self.win_count,
                "loss_count": trades - self.win_count,
                "win_rate": round(wr, 1),
                "open_positions": len(self.positions),
                "market_symbols": len(self.market_data),
                "uptime_seconds": (datetime.utcnow() - self.started_at).total_seconds(),
                "agent_heartbeats": {k: v.isoformat() for k, v in self.agent_heartbeats.items()},
                "bot_running": self.bot_running,
                "bot_paused": self.bot_paused,
                "initial_capital": self.INITIAL_CAPITAL,
                "current_capital": round(self.capital, 4),
                "equity": round(equity, 4),
                "return_pct": round((equity - self.INITIAL_CAPITAL) / self.INITIAL_CAPITAL * 100, 2),
                "max_drawdown_pct": round(dd, 2),
                "peak_equity": round(self.peak_equity, 4),
                "settings": self.settings.to_dict(),
                "win_streak": self.win_streak,
                "loss_streak": self.loss_streak,
                "current_streak": self.current_streak,
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "risk_reward": round(rr, 2),
                "total_win_pnl": round(self.total_win_pnl, 4),
                "total_loss_pnl": round(self.total_loss_pnl, 4),
                "pnl_history": self.pnl_history[-100:],
                "daily_pnl": dict(self.daily_pnl),
                "rl_metrics": self.rl_metrics,
            }

    def get_positions_detail(self) -> list:
        with self._lock:
            result = []
            for sym, p in self.positions.items():
                mdata = self.market_data.get(sym, {})
                cur = mdata.get("price", p.entry_price)
                pnl = (cur - p.entry_price) * p.qty if p.side == "long" else (p.entry_price - cur) * p.qty
                pnl_pct = (pnl / p.value_usd * 100) if p.value_usd else 0
                tps = p.take_profit_levels or [p.take_profit]
                idx = p.tp_hit_count
                active_tp = tps[min(idx, len(tps)-1)]
                tp_dist = abs(active_tp - p.entry_price)
                cur_dist = abs(cur - p.entry_price)
                prog = min(100, (cur_dist / tp_dist * 100)) if tp_dist else 0
                lev = p.indicators_at_open.get("leverage", 1) if p.indicators_at_open else 1
                dur = (datetime.utcnow() - p.opened_at).total_seconds()
                result.append({
                    "symbol": sym, "side": p.side, "qty": round(p.qty, 6),
                    "entry_price": p.entry_price, "current_price": cur,
                    "stop_loss": p.stop_loss, "take_profit": active_tp,
                    "take_profit_levels": tps, "tp_hit_count": p.tp_hit_count,
                    "pnl": round(pnl, 6), "pnl_pct": round(pnl_pct, 2),
                    "value_usd": round(p.value_usd, 2), "leverage": lev,
                    "progress_pct": round(prog, 1),
                    "opened_at": p.opened_at.isoformat(),
                    "duration_sec": round(dur),
                    "reason": p.reason, "ai_summary": p.ai_summary,
                })
            return sorted(result, key=lambda x: abs(x["pnl"]), reverse=True)

    def get_closed_positions(self) -> list:
        with self._lock:
            return [{
                "symbol": c.symbol, "side": c.side,
                "entry_price": c.entry_price, "exit_price": c.exit_price,
                "pnl": round(c.pnl, 6), "pnl_pct": round(c.pnl_pct, 2),
                "close_reason": c.close_reason, "ai_summary": c.ai_summary,
                "opened_at": c.opened_at.isoformat(), "closed_at": c.closed_at.isoformat(),
                "duration_sec": round(c.duration_sec),
            } for c in reversed(self.closed_positions[-200:])]

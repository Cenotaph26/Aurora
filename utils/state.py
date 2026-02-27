"""
Aurora AI — Gelişmiş Paylaşılan Durum Yöneticisi
- Pozisyonlarda SL/TP/AI özeti/sebep alanları
- Bot kontrol (start/stop/pause)
- Kapalı pozisyon geçmişi
- Dinamik ayarlar
- Başlangıç sermayesi takibi
"""
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class Position:
    symbol: str
    side: str                    # "long" | "short"
    qty: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    reason: str = ""             # Neden açıldı (strateji özeti)
    ai_summary: str = ""         # AI özet metni
    indicators_at_open: dict = field(default_factory=dict)
    value_usd: float = 0.0       # Açılış değeri ($)


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
    close_reason: str = ""       # "SL" | "TP" | "SIGNAL" | "MANUAL"
    ai_summary: str = ""


@dataclass
class Signal:
    symbol: str
    direction: str               # "buy" | "sell" | "hold"
    confidence: float
    strategy: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    reason: str = ""
    indicators: dict = field(default_factory=dict)


class BotSettings:
    def __init__(self):
        self.min_confidence: float = 0.55
        self.risk_pct: float = 0.02
        self.stop_loss_pct: float = 0.03
        self.take_profit_pct: float = 0.06
        self.market_interval: int = 15
        self.strategy_interval: int = 20
        self.exec_interval: int = 10
        self.watch_symbols: str = "bitcoin,ethereum,solana,binancecoin,ripple"
        self.max_positions: int = 5

    def to_dict(self):
        return {
            "min_confidence": self.min_confidence,
            "risk_pct": self.risk_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "market_interval": self.market_interval,
            "strategy_interval": self.strategy_interval,
            "exec_interval": self.exec_interval,
            "watch_symbols": self.watch_symbols,
            "max_positions": self.max_positions,
        }

    def update(self, data: dict):
        for k, v in data.items():
            if hasattr(self, k):
                try:
                    t = type(getattr(self, k))
                    setattr(self, k, t(v))
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

        self.agent_heartbeats: Dict[str, datetime] = {}
        self.started_at: datetime = datetime.utcnow()

        # Bot control
        self.bot_running: bool = True
        self.bot_paused: bool = False
        self.bot_status_log: List[dict] = []

        # Settings
        self.settings = BotSettings()

        # System log
        self.system_log: List[dict] = []

    def _log(self, level: str, msg: str):
        with self._lock:
            self.system_log.append({
                "ts": datetime.utcnow().isoformat(),
                "level": level,
                "msg": msg
            })
            if len(self.system_log) > 200:
                self.system_log = self.system_log[-200:]

    # ── Market ──────────────────────────────────────────────────────────────
    async def update_market(self, symbol: str, data: dict):
        with self._lock:
            self.market_data[symbol] = {**data, "updated_at": datetime.utcnow().isoformat()}

    # ── Signals ─────────────────────────────────────────────────────────────
    async def add_signal(self, signal: Signal):
        with self._lock:
            self.signals.append(signal)
            if len(self.signals) > 100:
                self.signals = self.signals[-100:]

    async def get_signals(self) -> List[Signal]:
        with self._lock:
            return list(self.signals)

    # ── Positions ────────────────────────────────────────────────────────────
    async def open_position(self, pos: Position):
        with self._lock:
            self.positions[pos.symbol] = pos
            self.trade_count += 1
            self.capital -= pos.value_usd
            self.system_log.append({
                "ts": datetime.utcnow().isoformat(),
                "level": "TRADE",
                "msg": f"📈 {pos.side.upper()} açıldı: {pos.symbol} @ ${pos.entry_price:.4f} | SL:${pos.stop_loss:.4f} TP:${pos.take_profit:.4f}"
            })

    async def close_position(self, symbol: str, exit_price: float, reason: str = "SIGNAL") -> float:
        with self._lock:
            if symbol not in self.positions:
                return 0.0
            pos = self.positions.pop(symbol)
            pnl = (exit_price - pos.entry_price) * pos.qty
            if pos.side == "short":
                pnl = -pnl
            pnl_pct = (pnl / pos.value_usd * 100) if pos.value_usd else 0
            self.total_pnl += pnl
            self.capital += pos.value_usd + pnl
            if pnl > 0:
                self.win_count += 1
            closed = ClosedPosition(
                symbol=symbol, side=pos.side, qty=pos.qty,
                entry_price=pos.entry_price, exit_price=exit_price,
                pnl=round(pnl, 6), pnl_pct=round(pnl_pct, 2),
                opened_at=pos.opened_at, close_reason=reason,
                ai_summary=pos.ai_summary,
            )
            self.closed_positions.append(closed)
            if len(self.closed_positions) > 100:
                self.closed_positions = self.closed_positions[-100:]
            icon = "🎯" if reason == "TP" else "🛑" if reason == "SL" else "📉"
            self.system_log.append({
                "ts": datetime.utcnow().isoformat(),
                "level": "TRADE",
                "msg": f"{icon} {pos.side.upper()} kapatıldı: {symbol} [{reason}] PnL=${pnl:+.4f} ({pnl_pct:+.2f}%)"
            })
            if len(self.system_log) > 200:
                self.system_log = self.system_log[-200:]
            return pnl

    # ── Heartbeat ────────────────────────────────────────────────────────────
    async def heartbeat(self, agent_name: str):
        with self._lock:
            self.agent_heartbeats[agent_name] = datetime.utcnow()

    # ── Bot Control ──────────────────────────────────────────────────────────
    def start_bot(self):
        with self._lock:
            self.bot_running = True
            self.bot_paused = False
            self.system_log.append({"ts": datetime.utcnow().isoformat(), "level": "INFO", "msg": "▶️ Bot başlatıldı"})

    def stop_bot(self):
        with self._lock:
            self.bot_running = False
            self.bot_paused = False
            self.system_log.append({"ts": datetime.utcnow().isoformat(), "level": "WARN", "msg": "⏹️ Bot durduruldu"})

    def pause_bot(self):
        with self._lock:
            self.bot_paused = not self.bot_paused
            status = "durakladı" if self.bot_paused else "devam ediyor"
            self.system_log.append({"ts": datetime.utcnow().isoformat(), "level": "WARN", "msg": f"⏸️ Bot {status}"})

    # ── Summary ──────────────────────────────────────────────────────────────
    def get_summary(self) -> dict:
        with self._lock:
            win_rate = (self.win_count / self.trade_count * 100) if self.trade_count else 0
            equity = self.capital + sum(
                (p.current_price - p.entry_price) * p.qty for p in self.positions.values()
            )
            return {
                "total_pnl": round(self.total_pnl, 4),
                "trade_count": self.trade_count,
                "win_rate": round(win_rate, 1),
                "win_count": self.win_count,
                "loss_count": self.trade_count - self.win_count,
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
                "settings": self.settings.to_dict(),
            }

    def get_positions_detail(self) -> list:
        with self._lock:
            result = []
            for sym, p in self.positions.items():
                mdata = self.market_data.get(sym, {})
                cur = mdata.get("price", p.entry_price)
                pnl = (cur - p.entry_price) * p.qty if p.side == "long" else (p.entry_price - cur) * p.qty
                pnl_pct = (pnl / p.value_usd * 100) if p.value_usd else 0
                # SL/TP progress (0-100%)
                sl_dist = abs(p.entry_price - p.stop_loss)
                tp_dist = abs(p.take_profit - p.entry_price)
                cur_dist = abs(cur - p.entry_price)
                if tp_dist > 0:
                    progress = min(100, max(0, (cur_dist / tp_dist) * 100))
                else:
                    progress = 0
                result.append({
                    "symbol": sym,
                    "side": p.side,
                    "qty": p.qty,
                    "entry_price": p.entry_price,
                    "current_price": cur,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "pnl": round(pnl, 6),
                    "pnl_pct": round(pnl_pct, 2),
                    "value_usd": round(p.value_usd, 2),
                    "progress_pct": round(progress, 1),
                    "opened_at": p.opened_at.isoformat(),
                    "reason": p.reason,
                    "ai_summary": p.ai_summary,
                    "indicators": p.indicators_at_open,
                })
            return result

    def get_closed_positions(self) -> list:
        with self._lock:
            return [
                {
                    "symbol": c.symbol,
                    "side": c.side,
                    "entry_price": c.entry_price,
                    "exit_price": c.exit_price,
                    "pnl": round(c.pnl, 6),
                    "pnl_pct": round(c.pnl_pct, 2),
                    "close_reason": c.close_reason,
                    "opened_at": c.opened_at.isoformat(),
                    "closed_at": c.closed_at.isoformat(),
                    "ai_summary": c.ai_summary,
                }
                for c in reversed(self.closed_positions[-50:])
            ]

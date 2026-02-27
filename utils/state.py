"""
Ajanlar arası paylaşılan durum yöneticisi.
Thread-safe asyncio.Lock ile korunur.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class Position:
    symbol: str
    side: str          # "long" | "short"
    qty: float
    entry_price: float
    current_price: float = 0.0
    pnl: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Signal:
    symbol: str
    direction: str     # "buy" | "sell" | "hold"
    confidence: float  # 0-1
    strategy: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SharedState:
    def __init__(self):
        self._lock = asyncio.Lock()

        # Piyasa verisi: {symbol: {price, volume, change_pct, ...}}
        self.market_data: Dict[str, dict] = {}

        # Aktif sinyal listesi
        self.signals: List[Signal] = []

        # Açık pozisyonlar
        self.positions: Dict[str, Position] = {}

        # RL modelin son ağırlık güncellemesi bilgisi
        self.rl_metrics: dict = {}

        # Toplam PnL
        self.total_pnl: float = 0.0
        self.trade_count: int = 0
        self.win_count: int = 0

        # Sistem durumu
        self.agent_heartbeats: Dict[str, datetime] = {}
        self.started_at: datetime = datetime.utcnow()

    async def update_market(self, symbol: str, data: dict):
        async with self._lock:
            self.market_data[symbol] = {**data, "updated_at": datetime.utcnow().isoformat()}

    async def add_signal(self, signal: Signal):
        async with self._lock:
            self.signals.append(signal)
            # Son 100 sinyali tut
            if len(self.signals) > 100:
                self.signals = self.signals[-100:]

    async def get_signals(self) -> List[Signal]:
        async with self._lock:
            return list(self.signals)

    async def open_position(self, pos: Position):
        async with self._lock:
            self.positions[pos.symbol] = pos
            self.trade_count += 1

    async def close_position(self, symbol: str, exit_price: float):
        async with self._lock:
            if symbol in self.positions:
                pos = self.positions.pop(symbol)
                pnl = (exit_price - pos.entry_price) * pos.qty
                if pos.side == "short":
                    pnl = -pnl
                self.total_pnl += pnl
                if pnl > 0:
                    self.win_count += 1
                return pnl
            return 0.0

    async def heartbeat(self, agent_name: str):
        async with self._lock:
            self.agent_heartbeats[agent_name] = datetime.utcnow()

    def get_summary(self) -> dict:
        win_rate = (self.win_count / self.trade_count * 100) if self.trade_count > 0 else 0
        return {
            "total_pnl": round(self.total_pnl, 4),
            "trade_count": self.trade_count,
            "win_rate": round(win_rate, 1),
            "open_positions": len(self.positions),
            "market_symbols": len(self.market_data),
            "uptime_seconds": (datetime.utcnow() - self.started_at).total_seconds(),
            "agent_heartbeats": {k: v.isoformat() for k, v in self.agent_heartbeats.items()},
        }

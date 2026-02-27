"""
Strategy Swarm - Çoklu strateji sinyal jeneratörü

Stratejiler:
1. RSI Mean Reversion   - aşırı alım/satım sinyalleri
2. MACD Momentum        - trend takibi
3. Bollinger Breakout   - kırılım sinyalleri
4. Composite Voting     - ağırlıklı oy birleştirici
"""
import asyncio
import os
from datetime import datetime

from utils.state import SharedState, Signal
from utils.logger import setup_logger

logger = setup_logger("StrategyAgent")

INTERVAL = int(os.getenv("STRATEGY_INTERVAL", "20"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.55"))


def rsi_strategy(data: dict) -> tuple:
    """RSI aşırı satım/alım stratejisi"""
    rsi = data.get("rsi", 50)
    if rsi < 30:
        conf = 0.5 + (30 - rsi) / 100  # daha düşük RSI = daha yüksek güven
        return "buy", min(conf, 0.95)
    elif rsi > 70:
        conf = 0.5 + (rsi - 70) / 100
        return "sell", min(conf, 0.95)
    return "hold", 0.3


def macd_strategy(data: dict) -> tuple:
    """MACD crossover momentum stratejisi"""
    macd = data.get("macd", 0)
    signal = data.get("macd_signal", 0)
    change = data.get("change_24h", 0)

    if macd > signal and macd > 0 and change > 1:
        conf = min(0.5 + abs(macd - signal) * 10, 0.9)
        return "buy", conf
    elif macd < signal and macd < 0 and change < -1:
        conf = min(0.5 + abs(macd - signal) * 10, 0.9)
        return "sell", conf
    return "hold", 0.3


def bollinger_strategy(data: dict) -> tuple:
    """Bollinger Band kırılım stratejisi"""
    price = data.get("price", 0)
    bb_lower = data.get("bb_lower", 0)
    bb_upper = data.get("bb_upper", 0)
    bb_mid = data.get("bb_mid", 0)

    if price == 0 or bb_lower == 0 or bb_upper == 0:
        return "hold", 0.3

    band_width = bb_upper - bb_lower
    if band_width == 0:
        return "hold", 0.3

    if price < bb_lower:
        # Aşırı satılmış - bant altı kırılımı
        dist = (bb_lower - price) / band_width
        return "buy", min(0.55 + dist, 0.90)
    elif price > bb_upper:
        dist = (price - bb_upper) / band_width
        return "sell", min(0.55 + dist, 0.90)
    elif price > bb_mid:
        return "buy", 0.35
    return "hold", 0.25


def momentum_filter(data: dict) -> float:
    """Momentum filtresi - sinyal güvenini artırır/azaltır"""
    mom = data.get("momentum_1m", 0)
    return 1.0 + min(abs(mom) / 100, 0.1)  # max %10 boost


def composite_vote(symbol: str, data: dict) -> Signal | None:
    """Tüm stratejileri oy birleştiriciyle birleştirir"""
    strategies = {
        "rsi":       rsi_strategy(data),
        "macd":      macd_strategy(data),
        "bollinger": bollinger_strategy(data),
    }

    direction_votes = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    for strat, (direction, conf) in strategies.items():
        direction_votes[direction] += conf

    # En yüksek oyu alan yönü seç
    best_dir = max(direction_votes, key=direction_votes.__getitem__)
    raw_conf = direction_votes[best_dir] / len(strategies)

    # Momentum filtresi uygula
    momentum_boost = momentum_filter(data)
    final_conf = min(raw_conf * momentum_boost, 0.98)

    if best_dir == "hold" or final_conf < MIN_CONFIDENCE:
        return None

    details = {k: f"{v[0]}({v[1]:.2f})" for k, v in strategies.items()}
    logger.info(
        f"📊 {symbol} → {best_dir.upper()} | conf={final_conf:.2f} | "
        f"price={data.get('price')} | RSI={data.get('rsi')} | "
        f"votes={details}"
    )

    return Signal(
        symbol=symbol,
        direction=best_dir,
        confidence=round(final_conf, 4),
        strategy="composite",
    )


class StrategyAgent:
    def __init__(self, state: SharedState):
        self.state = state

    async def run(self, shutdown: asyncio.Event):
        logger.info("🧠 Strategy Swarm başlatıldı")
        while not shutdown.is_set():
            try:
                market = self.state.market_data
                if not market:
                    await asyncio.sleep(5)
                    continue

                for symbol, data in market.items():
                    if data.get("history_len", 0) < 20:
                        continue  # Yeterli veri yok
                    signal = composite_vote(symbol, data)
                    if signal:
                        await self.state.add_signal(signal)

                await self.state.heartbeat("StrategyAgent")
            except Exception as e:
                logger.error(f"Strateji hatası: {e}", exc_info=True)

            await asyncio.sleep(INTERVAL)

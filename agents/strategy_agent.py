"""
Strategy Swarm — Sinyal üretici (reason alanı eklendi)
"""
import asyncio
import os
from datetime import datetime
from utils.state import SharedState, Signal
from utils.logger import setup_logger

logger = setup_logger("StrategyAgent")
INTERVAL = int(os.getenv("STRATEGY_INTERVAL", "20"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.45"))

def rsi_strategy(data):
    rsi = data.get("rsi", 50)
    if rsi < 30:
        return "buy", min(0.5 + (30-rsi)/100, 0.95), f"RSI={rsi:.1f} (aşırı satım)"
    elif rsi > 70:
        return "sell", min(0.5 + (rsi-70)/100, 0.95), f"RSI={rsi:.1f} (aşırı alım)"
    return "hold", 0.3, ""

def macd_strategy(data):
    macd = data.get("macd", 0)
    sig  = data.get("macd_signal", 0)
    chg  = data.get("change_24h", 0)
    diff = abs(macd - sig)
    if macd > sig and diff > 0:
        conf = min(0.5 + diff * 50, 0.9)
        return "buy", conf, f"MACD yukarı kesiş ({macd:.5f})"
    elif macd < sig and diff > 0:
        conf = min(0.5 + diff * 50, 0.9)
        return "sell", conf, f"MACD aşağı kesiş ({macd:.5f})"
    return "hold", 0.3, ""

def bollinger_strategy(data):
    price = data.get("price", 0)
    lo = data.get("bb_lower", 0)
    hi = data.get("bb_upper", 0)
    mid = data.get("bb_mid", 0)
    if not (price and lo and hi): return "hold", 0.3, ""
    bw = hi - lo
    if bw <= 0: return "hold", 0.3, ""
    if price < lo:
        return "buy",  min(0.55 + (lo-price)/bw, 0.90), f"BB alt kırılım (price={price:.4f}<lo={lo:.4f})"
    elif price > hi:
        return "sell", min(0.55 + (price-hi)/bw, 0.90), f"BB üst kırılım (price={price:.4f}>hi={hi:.4f})"
    return "hold", 0.25, ""

def momentum_strategy(data):
    mom = data.get("momentum_1m", 0)
    chg = data.get("change_24h", 0)
    rsi = data.get("rsi", 50)
    if mom > 0.15 and chg > 1 and rsi < 65:
        return "buy", min(0.45 + mom * 2, 0.85), f"Momentum ↑ ({mom:+.3f}%)"
    elif mom < -0.15 and chg < -1 and rsi > 35:
        return "sell", min(0.45 + abs(mom) * 2, 0.85), f"Momentum ↓ ({mom:+.3f}%)"
    return "hold", 0.2, ""

def composite_vote(symbol, data):
    strats = {
        "rsi":       rsi_strategy(data),
        "macd":      macd_strategy(data),
        "bollinger": bollinger_strategy(data),
        "momentum":  momentum_strategy(data),
    }
    votes = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    reasons = []
    for name, (d, c, r) in strats.items():
        votes[d] += c
        if r:
            reasons.append(r)
    best = max(votes, key=votes.__getitem__)
    raw_conf = votes[best] / len(strats)
    mom = data.get("momentum_1m", 0)
    final_conf = min(raw_conf * (1.0 + min(abs(mom)/100, 0.1)), 0.98)
    if best == "hold" or final_conf < MIN_CONFIDENCE:
        return None
    reason_str = " | ".join(reasons) if reasons else "Composite vote"
    logger.info(f"📊 {symbol} → {best.upper()} conf={final_conf:.2f} | {reason_str}")
    return Signal(
        symbol=symbol, direction=best,
        confidence=round(final_conf, 4),
        strategy="composite",
        reason=reason_str,
        indicators={k: data.get(k, 0) for k in ["rsi","macd","macd_signal","bb_lower","bb_upper","price","change_24h","momentum_1m"]},
    )

class StrategyAgent:
    def __init__(self, state: SharedState):
        self.state = state

    async def run(self, shutdown: asyncio.Event):
        logger.info("🧠 Strategy Swarm başlatıldı")
        while not shutdown.is_set():
            try:
                if not self.state.bot_running or self.state.bot_paused:
                    await asyncio.sleep(5)
                    continue
                for symbol, data in self.state.market_data.items():
                    if data.get("history_len", 0) < 5:
                        continue
                    sig = composite_vote(symbol, data)
                    if sig:
                        await self.state.add_signal(sig)
                await self.state.heartbeat("StrategyAgent")
            except Exception as e:
                logger.error(f"Strateji hatası: {e}", exc_info=True)
            await asyncio.sleep(INTERVAL)

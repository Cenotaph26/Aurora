"""
Strategy Agent - Sinyal üretici
Düzeltmeler:
- hold oyları composite hesabından çıkarıldı
- MACD normalize edildi (coin fiyatına göre)
- Daha agresif eşikler - daha fazla sinyal
- Trend filtresi eklendi
"""
import asyncio
import os
from datetime import datetime
from utils.state import SharedState, Signal
from utils.logger import setup_logger

logger = setup_logger("StrategyAgent")
INTERVAL  = int(os.getenv("STRATEGY_INTERVAL", "15"))
MIN_CONF  = float(os.getenv("MIN_CONFIDENCE", "0.40"))


def rsi_strategy(data):
    rsi = data.get("rsi", 50)
    if rsi <= 25:
        return "buy",  0.85, f"RSI={rsi:.1f} güçlü aşırı satım"
    if rsi <= 32:
        return "buy",  0.70, f"RSI={rsi:.1f} aşırı satım"
    if rsi <= 40:
        return "buy",  0.52, f"RSI={rsi:.1f} satım bölgesi"
    if rsi >= 75:
        return "sell", 0.85, f"RSI={rsi:.1f} güçlü aşırı alım"
    if rsi >= 68:
        return "sell", 0.70, f"RSI={rsi:.1f} aşırı alım"
    if rsi >= 60:
        return "sell", 0.52, f"RSI={rsi:.1f} alım bölgesi"
    return None


def macd_strategy(data):
    macd  = data.get("macd", 0)
    sig   = data.get("macd_signal", 0)
    price = data.get("price", 1) or 1
    # MACD'yi fiyata göre normalize et — küçük coinlerde diff çok küçük olur
    norm  = abs(macd - sig) / price * 1000
    if macd > sig and norm > 0.001:
        conf = min(0.45 + norm * 2, 0.88)
        return "buy",  conf, f"MACD ↑ norm={norm:.4f}"
    if macd < sig and norm > 0.001:
        conf = min(0.45 + norm * 2, 0.88)
        return "sell", conf, f"MACD ↓ norm={norm:.4f}"
    return None


def bollinger_strategy(data):
    price = data.get("price", 0)
    lo    = data.get("bb_lower", 0)
    hi    = data.get("bb_upper", 0)
    if not (price and lo and hi):
        return None
    bw = hi - lo
    if bw <= 0:
        return None
    if price <= lo:
        strength = min((lo - price) / bw + 0.55, 0.92)
        return "buy",  strength, f"BB altı kırılım ({((lo-price)/lo*100):.2f}%)"
    if price >= hi:
        strength = min((price - hi) / bw + 0.55, 0.92)
        return "sell", strength, f"BB üstü kırılım ({((price-hi)/hi*100):.2f}%)"
    # BB içinde — yüzdelik pozisyon: alt %20 → zayıf buy, üst %80 → zayıf sell
    pos = (price - lo) / bw
    if pos < 0.20:
        return "buy",  0.44, f"BB alt çeyrek (pos={pos:.2f})"
    if pos > 0.80:
        return "sell", 0.44, f"BB üst çeyrek (pos={pos:.2f})"
    return None


def momentum_strategy(data):
    mom = data.get("momentum_1m", 0)
    chg = data.get("change_24h", 0)
    rsi = data.get("rsi", 50)
    vol = data.get("volume_24h", 0)
    if mom > 0.10 and rsi < 68:
        conf = min(0.42 + abs(mom) * 3, 0.82)
        return "buy",  conf, f"Momentum ↑ {mom:+.3f}%"
    if mom < -0.10 and rsi > 32:
        conf = min(0.42 + abs(mom) * 3, 0.82)
        return "sell", conf, f"Momentum ↓ {mom:+.3f}%"
    return None


def volume_spike_strategy(data):
    """Hacim patlaması = güçlü yön sinyali"""
    vol   = data.get("volume_24h", 0)
    chg   = data.get("change_24h", 0)
    rsi   = data.get("rsi", 50)
    # Hacim $5M+ ve güçlü yön hareketi
    if vol > 5_000_000:
        if chg > 3 and rsi < 70:
            return "buy",  min(0.48 + chg / 100, 0.80), f"Hacim patlaması ↑ vol=${vol/1e6:.1f}M chg={chg:+.1f}%"
        if chg < -3 and rsi > 30:
            return "sell", min(0.48 + abs(chg) / 100, 0.80), f"Hacim patlaması ↓ vol=${vol/1e6:.1f}M chg={chg:+.1f}%"
    return None


def composite_vote(symbol, data):
    raw_signals = [
        ("rsi",       rsi_strategy(data)),
        ("macd",      macd_strategy(data)),
        ("bollinger", bollinger_strategy(data)),
        ("momentum",  momentum_strategy(data)),
        ("volume",    volume_spike_strategy(data)),
    ]
    # Sadece gerçek yön sinyallerini al (hold/None değil)
    actives = [(name, d, c, r) for name, sig in raw_signals
               if sig is not None
               for d, c, r in [sig]]

    if not actives:
        return None

    votes = {"buy": [], "sell": []}
    reasons = []
    for name, direction, conf, reason in actives:
        if direction in votes:
            votes[direction].append(conf)
        if reason:
            reasons.append(reason)

    buy_score  = sum(votes["buy"])  / max(len(votes["buy"]),  1) if votes["buy"]  else 0
    sell_score = sum(votes["sell"]) / max(len(votes["sell"]), 1) if votes["sell"] else 0

    # Konsensus bonusu: birden fazla strateji aynı yönü gösterirse +boost
    buy_count  = len(votes["buy"])
    sell_count = len(votes["sell"])

    if buy_count >= 2:
        buy_score  = min(buy_score  * (1 + buy_count  * 0.08), 0.97)
    if sell_count >= 2:
        sell_score = min(sell_score * (1 + sell_count * 0.08), 0.97)

    best, final_conf = ("buy", buy_score) if buy_score >= sell_score else ("sell", sell_score)
    active_count = buy_count if best == "buy" else sell_count

    if final_conf < MIN_CONF or active_count == 0:
        return None

    reason_str = " | ".join(reasons[:3]) if reasons else "composite"
    logger.info(f"📊 {symbol} → {best.upper()} conf={final_conf:.2f} ({active_count} strateji) | {reason_str[:80]}")

    return Signal(
        symbol=symbol,
        direction=best,
        confidence=round(final_conf, 4),
        strategy="composite",
        reason=reason_str,
        indicators={k: data.get(k, 0) for k in [
            "rsi","macd","macd_signal","bb_lower","bb_upper",
            "price","change_24h","momentum_1m","volume_24h"
        ]},
    )


class StrategyAgent:
    def __init__(self, state: SharedState):
        self.state = state

    async def run(self, shutdown: asyncio.Event):
        logger.info("🧠 Strategy Agent başlatıldı | 5 strateji aktif")
        while not shutdown.is_set():
            try:
                if not self.state.bot_running or self.state.bot_paused:
                    await asyncio.sleep(5)
                    continue
                signals_generated = 0
                for symbol, data in list(self.state.market_data.items()):
                    if data.get("history_len", 0) < 5:
                        continue
                    sig = composite_vote(symbol, data)
                    if sig:
                        await self.state.add_signal(sig)
                        signals_generated += 1
                if signals_generated:
                    logger.info(f"✅ {signals_generated} sinyal üretildi")
                await self.state.heartbeat("StrategyAgent")
            except Exception as e:
                logger.error(f"Strateji hatası: {e}", exc_info=True)
            await asyncio.sleep(INTERVAL)

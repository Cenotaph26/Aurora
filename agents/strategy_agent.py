"""
Strategy Agent v3 — scan_batch ile kontrollü sinyal üretimi
Her turda MAX scan_batch kadar sembol taranır (rotasyon)
"""
import asyncio, os, random
from datetime import datetime
from utils.state import SharedState, Signal
from utils.logger import setup_logger

logger = setup_logger("StrategyAgent")
INTERVAL = int(os.getenv("STRATEGY_INTERVAL", "20"))

def rsi_sig(d):
    r = d.get("rsi", 50)
    if r <= 25: return "buy",  0.82, f"RSI {r:.1f} güçlü satım"
    if r <= 33: return "buy",  0.65, f"RSI {r:.1f} satım"
    if r >= 75: return "sell", 0.82, f"RSI {r:.1f} güçlü alım"
    if r >= 67: return "sell", 0.65, f"RSI {r:.1f} alım"
    return None

def macd_sig(d):
    macd, sig, price = d.get("macd",0), d.get("macd_signal",0), d.get("price",1) or 1
    norm = abs(macd - sig) / price * 1000
    if norm < 0.002: return None
    conf = min(0.48 + norm * 1.5, 0.88)
    if macd > sig: return "buy",  conf, f"MACD↑ {norm:.4f}"
    return "sell", conf, f"MACD↓ {norm:.4f}"

def bb_sig(d):
    p, lo, hi = d.get("price",0), d.get("bb_lower",0), d.get("bb_upper",0)
    if not (p and lo and hi): return None
    bw = hi - lo
    if bw <= 0: return None
    if p < lo:  return "buy",  min(0.55+(lo-p)/bw, 0.90), f"BB alt ({(lo-p)/lo*100:.2f}%)"
    if p > hi:  return "sell", min(0.55+(p-hi)/bw, 0.90), f"BB üst ({(p-hi)/hi*100:.2f}%)"
    pos = (p - lo) / bw
    if pos < 0.15: return "buy",  0.42, f"BB alt çeyrek"
    if pos > 0.85: return "sell", 0.42, f"BB üst çeyrek"
    return None

def mom_sig(d):
    mom, rsi = d.get("momentum_1m",0), d.get("rsi",50)
    if mom > 0.12 and rsi < 68: return "buy",  min(0.44+abs(mom)*2.5, 0.82), f"Mom↑ {mom:+.3f}%"
    if mom < -0.12 and rsi > 32: return "sell", min(0.44+abs(mom)*2.5, 0.82), f"Mom↓ {mom:+.3f}%"
    return None

def vol_sig(d):
    vol, chg, rsi = d.get("volume_24h",0), d.get("change_24h",0), d.get("rsi",50)
    if vol < 3_000_000: return None
    if chg > 4 and rsi < 72: return "buy",  min(0.50+chg/100, 0.80), f"Vol spike↑ ${vol/1e6:.1f}M"
    if chg < -4 and rsi > 28: return "sell", min(0.50+abs(chg)/100, 0.80), f"Vol spike↓ ${vol/1e6:.1f}M"
    return None

STRATS = [rsi_sig, macd_sig, bb_sig, mom_sig, vol_sig]

def analyze(symbol: str, data: dict, min_conf: float) -> Signal | None:
    if data.get("history_len", 0) < 5:
        return None
    votes = {"buy": [], "sell": []}
    reasons = []
    for fn in STRATS:
        r = fn(data)
        if r:
            d, c, txt = r
            votes[d].append(c)
            reasons.append(txt)
    buy_n, sell_n = len(votes["buy"]), len(votes["sell"])
    if not buy_n and not sell_n:
        return None
    buy_sc  = (sum(votes["buy"])  / buy_n)  * (1 + buy_n  * 0.06) if buy_n  else 0
    sell_sc = (sum(votes["sell"]) / sell_n) * (1 + sell_n * 0.06) if sell_n else 0
    best, sc = ("buy", buy_sc) if buy_sc >= sell_sc else ("sell", sell_sc)
    sc = min(sc, 0.97)
    if sc < min_conf:
        return None
    return Signal(
        symbol=symbol, direction=best, confidence=round(sc, 4),
        strategy="composite", reason=" | ".join(reasons[:3]),
        indicators={k: data.get(k, 0) for k in ["rsi","macd","macd_signal","bb_lower","bb_upper","price","change_24h","momentum_1m","volume_24h"]},
    )

class StrategyAgent:
    def __init__(self, state: SharedState):
        self.state = state
        self._scan_ptr = 0  # rotasyon pointer

    async def run(self, shutdown: asyncio.Event):
        logger.info("🧠 Strategy Agent v3 | Rotasyonlu tarama aktif")
        while not shutdown.is_set():
            try:
                if not self.state.bot_running or self.state.bot_paused:
                    await asyncio.sleep(5)
                    continue

                symbols = list(self.state.market_data.keys())
                if not symbols:
                    await asyncio.sleep(INTERVAL)
                    continue

                batch = self.state.settings.scan_batch
                start = self._scan_ptr % len(symbols)
                chunk = (symbols + symbols)[start:start + batch]
                self._scan_ptr = (start + batch) % len(symbols)

                generated = 0
                for sym in chunk:
                    data = self.state.market_data.get(sym, {})
                    sig = analyze(sym, data, self.state.settings.min_confidence)
                    if sig:
                        await self.state.add_signal(sig)
                        generated += 1

                if generated:
                    logger.info(f"✅ {generated} sinyal | {batch} sembol tarandı ({start}→{self._scan_ptr})")
                await self.state.heartbeat("StrategyAgent")
            except Exception as e:
                logger.error(f"Strateji hatası: {e}", exc_info=True)
            await asyncio.sleep(INTERVAL)

"""
Market Agent - Piyasa veri toplayıcısı
- CoinGecko ücretsiz API'sinden fiyat/hacim verisi çeker
- Teknik indikatörler hesaplar (RSI, MACD, Bollinger Bands)
- Binance entegrasyonu: BINANCE_API_KEY env var varsa aktif olur
"""
import asyncio
import aiohttp
import os
from collections import deque
from typing import Deque, Dict
from datetime import datetime

from utils.state import SharedState
from utils.logger import setup_logger

logger = setup_logger("MarketAgent")

SYMBOLS = os.getenv("WATCH_SYMBOLS", "bitcoin,ethereum,solana,binancecoin,ripple").split(",")
INTERVAL = int(os.getenv("MARKET_INTERVAL", "15"))  # saniye

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        diff = prices[i] - prices[i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 1e-9
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_ema(prices: list, span: int) -> float:
    if not prices:
        return 0.0
    k = 2 / (span + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_macd(prices: list):
    if len(prices) < 26:
        return 0.0, 0.0
    ema12 = calc_ema(prices[-26:], 12)
    ema26 = calc_ema(prices[-26:], 26)
    macd_line = ema12 - ema26
    signal = calc_ema([macd_line], 9)
    return round(macd_line, 6), round(signal, 6)


def calc_bollinger(prices: list, period: int = 20):
    if len(prices) < period:
        return 0, 0, 0
    window = prices[-period:]
    mean = sum(window) / period
    std = (sum((p - mean) ** 2 for p in window) / period) ** 0.5
    return round(mean - 2 * std, 4), round(mean, 4), round(mean + 2 * std, 4)


class MarketAgent:
    def __init__(self, state: SharedState):
        self.state = state
        self.price_history: Dict[str, Deque] = {s: deque(maxlen=200) for s in SYMBOLS}
        self.prev_prices: Dict[str, float] = {}

    async def fetch_prices(self, session: aiohttp.ClientSession) -> dict:
        try:
            params = {
                "ids": ",".join(SYMBOLS),
                "vs_currencies": "usd",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            }
            async with session.get(COINGECKO_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            logger.warning(f"Fiyat çekme hatası: {e}")
        return {}

    async def run(self, shutdown: asyncio.Event):
        logger.info(f"📡 Market Agent başlatıldı | Semboller: {SYMBOLS}")
        async with aiohttp.ClientSession() as session:
            while not shutdown.is_set():
                try:
                    raw = await self.fetch_prices(session)
                    for symbol, data in raw.items():
                        price = data.get("usd", 0)
                        if price <= 0:
                            continue

                        hist = self.price_history[symbol]
                        hist.append(price)
                        prices = list(hist)

                        rsi = calc_rsi(prices)
                        macd, macd_sig = calc_macd(prices)
                        bb_lower, bb_mid, bb_upper = calc_bollinger(prices)
                        prev = self.prev_prices.get(symbol, price)
                        momentum = round((price - prev) / prev * 100, 4) if prev else 0

                        await self.state.update_market(symbol, {
                            "price": price,
                            "volume_24h": data.get("usd_24h_vol", 0),
                            "change_24h": data.get("usd_24h_change", 0),
                            "market_cap": data.get("usd_market_cap", 0),
                            "rsi": rsi,
                            "macd": macd,
                            "macd_signal": macd_sig,
                            "bb_lower": bb_lower,
                            "bb_mid": bb_mid,
                            "bb_upper": bb_upper,
                            "momentum_1m": momentum,
                            "history_len": len(prices),
                        })
                        self.prev_prices[symbol] = price

                    logger.debug(f"✅ {len(raw)} sembol güncellendi")
                    await self.state.heartbeat("MarketAgent")

                except Exception as e:
                    logger.error(f"Market döngüsü hatası: {e}", exc_info=True)

                await asyncio.sleep(INTERVAL)

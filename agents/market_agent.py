"""
Market Agent - Binance Futures veri toplayıcısı
- Binance Futures'dan tüm USDT perpetual coinleri çeker
- Teknik indikatörler hesaplar (RSI, MACD, Bollinger Bands)
"""
import asyncio
import aiohttp
import os
from collections import deque
from typing import Deque, Dict, List
from datetime import datetime

from utils.state import SharedState
from utils.logger import setup_logger

logger = setup_logger("MarketAgent")

INTERVAL = int(os.getenv("MARKET_INTERVAL", "30"))
BINANCE_FUTURES_BASE = "https://fapi.binance.com"
MAX_COINS = int(os.getenv("MAX_COINS", "0"))  # 0 = hepsi


def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains.append(diff)
        elif diff < 0:
            losses.append(abs(diff))
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
        self.price_history: Dict[str, Deque] = {}
        self.prev_prices: Dict[str, float] = {}
        self.symbols: List[str] = []

    async def fetch_all_symbols(self, session: aiohttp.ClientSession) -> List[str]:
        try:
            url = f"{BINANCE_FUTURES_BASE}/fapi/v1/exchangeInfo"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    data = await r.json()
                    symbols = [
                        s["symbol"] for s in data.get("symbols", [])
                        if s.get("quoteAsset") == "USDT"
                        and s.get("contractType") == "PERPETUAL"
                        and s.get("status") == "TRADING"
                    ]
                    if MAX_COINS > 0:
                        symbols = symbols[:MAX_COINS]
                    logger.info(f"📡 {len(symbols)} USDT Perpetual sembol bulundu")
                    return symbols
        except Exception as e:
            logger.warning(f"Sembol listesi alınamadı: {e}")
        return []

    async def fetch_ticker_batch(self, session: aiohttp.ClientSession) -> dict:
        try:
            url = f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/24hr"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    tickers = await r.json()
                    return {t["symbol"]: t for t in tickers}
        except Exception as e:
            logger.warning(f"Ticker çekme hatası: {e}")
        return {}

    async def fetch_klines(self, session: aiohttp.ClientSession, symbol: str, limit: int = 50) -> list:
        try:
            url = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
            params = {"symbol": symbol, "interval": "1m", "limit": limit}
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    klines = await r.json()
                    return [float(k[4]) for k in klines]
        except Exception:
            pass
        return []

    async def run(self, shutdown: asyncio.Event):
        logger.info("📡 Market Agent başlatıldı | Binance Futures USDT Perpetual")
        async with aiohttp.ClientSession() as session:
            self.symbols = await self.fetch_all_symbols(session)
            if not self.symbols:
                logger.error("Sembol listesi boş! Varsayılan listeye dönülüyor.")
                self.symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

            for sym in self.symbols:
                if sym not in self.price_history:
                    self.price_history[sym] = deque(maxlen=200)

            # Geçmiş fiyat verileri - batch olarak yükle
            logger.info("📊 Geçmiş fiyat verileri yükleniyor...")
            batch_size = 20
            for i in range(0, min(len(self.symbols), 100), batch_size):
                batch = self.symbols[i:i+batch_size]
                tasks = [self.fetch_klines(session, sym, 50) for sym in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for sym, closes in zip(batch, results):
                    if isinstance(closes, list) and closes:
                        for c in closes:
                            self.price_history[sym].append(c)
                await asyncio.sleep(0.5)

            logger.info(f"✅ Geçmiş veriler yüklendi | {len(self.symbols)} sembol aktif")

            while not shutdown.is_set():
                try:
                    ticker_map = await self.fetch_ticker_batch(session)
                    updated = 0
                    for symbol in self.symbols:
                        t = ticker_map.get(symbol)
                        if not t:
                            continue
                        price = float(t.get("lastPrice", 0))
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
                            "volume_24h": float(t.get("quoteVolume", 0)),
                            "change_24h": float(t.get("priceChangePercent", 0)),
                            "high_24h": float(t.get("highPrice", 0)),
                            "low_24h": float(t.get("lowPrice", 0)),
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
                        updated += 1

                    logger.debug(f"✅ {updated} sembol güncellendi")
                    await self.state.heartbeat("MarketAgent")

                except Exception as e:
                    logger.error(f"Market döngüsü hatası: {e}", exc_info=True)

                await asyncio.sleep(INTERVAL)

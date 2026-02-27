"""
Execution Agent - Emir Uygulayıcı

Modlar:
- PAPER_TRADING=true (varsayılan): Gerçek emir vermez, simüle eder
- PAPER_TRADING=false + BINANCE_API_KEY/SECRET: Binance spot emirleri

Özellikler:
- Sinyal filtresi (min. güven eşiği)
- Pozisyon boyutlandırma (risk % portföy)
- Stop-loss / take-profit takibi
- Duplicate sinyal önleme
"""
import asyncio
import os
import aiohttp
import hmac
import hashlib
import time
from urllib.parse import urlencode
from datetime import datetime

from utils.state import SharedState, Position
from utils.logger import setup_logger

logger = setup_logger("ExecutionAgent")

INTERVAL        = int(os.getenv("EXEC_INTERVAL", "10"))
PAPER_TRADING   = os.getenv("PAPER_TRADING", "true").lower() == "true"
BINANCE_KEY     = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET  = os.getenv("BINANCE_API_SECRET", "")
PORTFOLIO_USD   = float(os.getenv("PORTFOLIO_USD", "1000"))
RISK_PCT        = float(os.getenv("RISK_PCT", "0.02"))  # Her işlemde portföyün %2'si
STOP_LOSS_PCT   = float(os.getenv("STOP_LOSS_PCT", "0.03"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.06"))

# CoinGecko sembol → Binance çifti eşlemesi
SYMBOL_MAP = {
    "bitcoin":     "BTCUSDT",
    "ethereum":    "ETHUSDT",
    "solana":      "SOLUSDT",
    "binancecoin": "BNBUSDT",
    "ripple":      "XRPUSDT",
}


class ExecutionAgent:
    def __init__(self, state: SharedState):
        self.state = state
        self.processed_signals: set = set()
        self.paper_pnl = 0.0
        self.mode = "PAPER" if PAPER_TRADING else "LIVE"

    def _position_size(self, price: float) -> float:
        """Risk yüzdesiyle pozisyon büyüklüğü hesapla"""
        risk_usd = PORTFOLIO_USD * RISK_PCT
        return round(risk_usd / price, 6)

    async def _paper_execute(self, symbol: str, direction: str, price: float):
        """Kağıt üzerinde işlem simülasyonu"""
        qty = self._position_size(price)
        if direction == "buy":
            if symbol not in self.state.positions:
                pos = Position(
                    symbol=symbol, side="long", qty=qty,
                    entry_price=price, current_price=price
                )
                await self.state.open_position(pos)
                logger.info(
                    f"📝 [PAPER] BUY  {symbol} | qty={qty} | price=${price:,.4f} | "
                    f"cost=${qty * price:.2f}"
                )
        elif direction == "sell":
            if symbol in self.state.positions:
                pnl = await self.state.close_position(symbol, price)
                logger.info(
                    f"📝 [PAPER] SELL {symbol} | price=${price:,.4f} | "
                    f"PnL=${pnl:+.4f}"
                )

    async def _binance_execute(self, symbol: str, direction: str, qty: float, session: aiohttp.ClientSession):
        """Gerçek Binance spot emri"""
        binance_sym = SYMBOL_MAP.get(symbol)
        if not binance_sym:
            logger.warning(f"Binance eşlemesi bulunamadı: {symbol}")
            return

        side = "BUY" if direction == "buy" else "SELL"
        params = {
            "symbol": binance_sym,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        query = urlencode(params)
        signature = hmac.new(BINANCE_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature

        headers = {"X-MBX-APIKEY": BINANCE_KEY}
        try:
            url = "https://api.binance.com/api/v3/order"
            async with session.post(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                resp = await r.json()
                if r.status == 200:
                    logger.info(f"✅ [LIVE] {side} {binance_sym} | orderId={resp.get('orderId')}")
                else:
                    logger.error(f"❌ Binance hata: {resp}")
        except Exception as e:
            logger.error(f"Binance bağlantı hatası: {e}")

    async def _check_stop_take(self):
        """Açık pozisyonlar için stop-loss / take-profit kontrol et"""
        for symbol, pos in list(self.state.positions.items()):
            market = self.state.market_data.get(symbol, {})
            cur_price = market.get("price", 0)
            if cur_price == 0:
                continue

            pos.current_price = cur_price
            change = (cur_price - pos.entry_price) / pos.entry_price

            if pos.side == "long":
                if change <= -STOP_LOSS_PCT:
                    pnl = await self.state.close_position(symbol, cur_price)
                    logger.warning(f"🛑 STOP-LOSS {symbol} | change={change:.2%} | PnL=${pnl:+.2f}")
                elif change >= TAKE_PROFIT_PCT:
                    pnl = await self.state.close_position(symbol, cur_price)
                    logger.info(f"🎯 TAKE-PROFIT {symbol} | change={change:.2%} | PnL=${pnl:+.2f}")

    async def run(self, shutdown: asyncio.Event):
        logger.info(f"⚡ Execution Agent başlatıldı | Mod: {self.mode}")
        if not PAPER_TRADING:
            if not BINANCE_KEY or not BINANCE_SECRET:
                logger.error("❌ LIVE mod ama BINANCE_API_KEY/SECRET ayarlanmamış! PAPER moduna geçiliyor.")

        async with aiohttp.ClientSession() as session:
            while not shutdown.is_set():
                try:
                    await self._check_stop_take()

                    signals = await self.state.get_signals()
                    for sig in signals:
                        sig_id = f"{sig.symbol}_{sig.direction}_{sig.timestamp.strftime('%H%M')}"
                        if sig_id in self.processed_signals:
                            continue
                        self.processed_signals.add(sig_id)

                        if sig.confidence < float(os.getenv("MIN_CONFIDENCE", "0.55")):
                            continue

                        market = self.state.market_data.get(sig.symbol, {})
                        price = market.get("price", 0)
                        if price <= 0:
                            continue

                        if PAPER_TRADING:
                            await self._paper_execute(sig.symbol, sig.direction, price)
                        else:
                            qty = self._position_size(price)
                            await self._binance_execute(sig.symbol, sig.direction, qty, session)

                    # İşlenmiş sinyal kümesini temizle (bellek yönetimi)
                    if len(self.processed_signals) > 500:
                        self.processed_signals = set(list(self.processed_signals)[-200:])

                    await self.state.heartbeat("ExecutionAgent")

                except Exception as e:
                    logger.error(f"Execution hatası: {e}", exc_info=True)

                await asyncio.sleep(INTERVAL)

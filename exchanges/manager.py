from exchanges.binance import BinanceClient
from exchanges.bybit import BybitClient

class ExchangeManager:

    def __init__(self):
        self.binance = BinanceClient()
        self.bybit = BybitClient()

    async def funding_rates(self, symbol):
        b1 = await self.binance.funding(symbol)
        b2 = await self.bybit.funding(symbol)
        return {"binance": b1, "bybit": b2}

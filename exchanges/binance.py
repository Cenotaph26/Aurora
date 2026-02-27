import aiohttp
from config import BINANCE_URL

class BinanceClient:

    async def funding(self, symbol):
        async with aiohttp.ClientSession() as s:
            url=f"{BINANCE_URL}/fapi/v1/premiumIndex?symbol={symbol}"
            async with s.get(url) as r:
                data = await r.json()
                return float(data["lastFundingRate"])

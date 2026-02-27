import random

class StrategyAgent:

    async def decide(self, symbol):
        side = random.choice(["LONG","SHORT"])
        return {
            "symbol": symbol,
            "side": side,
            "confidence": random.random()
        }

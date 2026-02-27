import random

class LiquidationAgent:

    async def heatmap(self, symbol):
        return {
            "long_liq": random.randint(1,100),
            "short_liq": random.randint(1,100)
        }

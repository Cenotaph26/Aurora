import random

class NewsAgent:

    async def sentiment(self):
        score = random.uniform(-1,1)
        return {
            "sentiment": score,
            "reason": "market news sentiment"
        }

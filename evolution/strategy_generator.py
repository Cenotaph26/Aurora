import random

class StrategyGenerator:

    def generate(self):
        strategy = {
            "ema_fast": random.randint(5,20),
            "ema_slow": random.randint(30,100),
            "rsi": random.randint(40,70)
        }

        return strategy

import random

class Backtester:

    def test(self, strategy):
        performance = random.uniform(-0.1,0.3)

        return {
            "sharpe": performance,
            "drawdown": random.uniform(0,0.2)
        }

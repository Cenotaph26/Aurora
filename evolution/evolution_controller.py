from evolution.strategy_generator import StrategyGenerator
from evolution.backtester import Backtester

class EvolutionController:

    def __init__(self):
        self.generator = StrategyGenerator()
        self.backtester = Backtester()
        self.best_score = 0

    def evolve(self):
        new_strategy = self.generator.generate()
        result = self.backtester.test(new_strategy)

        score = result["sharpe"]

        if score > self.best_score:
            self.best_score = score
            print("NEW STRATEGY DEPLOYED")
            return new_strategy

        return None

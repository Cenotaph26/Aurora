from agents.news_agent import NewsAgent
from agents.strategy_agent import StrategyAgent
from agents.liquidation_agent import LiquidationAgent
from agents.funding_agent import FundingArbitrageAgent

from core.portfolio import PortfolioBrain
from core.risk import RiskManager
from execution.executor import Executor
from exchanges.manager import ExchangeManager
from evolution.evolution_controller import EvolutionController

class Swarm:

    def __init__(self):
        self.news = NewsAgent()
        self.strategy = StrategyAgent()
        self.liq = LiquidationAgent()
        self.funding = FundingArbitrageAgent()

        self.portfolio = PortfolioBrain()
        self.risk = RiskManager()
        self.exec = Executor()
        self.exchange = ExchangeManager()
        self.evolution = EvolutionController()

    async def cycle(self, symbols):
        sentiment = await self.news.sentiment()
        signals = []

        for s in symbols:
            strat = await self.strategy.decide(s)
            funding = await self.exchange.funding_rates(s)
            arb = self.funding.detect(funding)

            strat["confidence"] += (sentiment["sentiment"] * 0.2)

            if arb["arb"]:
                strat["confidence"] += 0.3

            signals.append(strat)

        allocated = self.portfolio.allocate(signals)

        for trade in allocated:
            if self.risk.approve(trade):
                await self.exec.execute(trade)

        new_strategy = self.evolution.evolve()
        if new_strategy:
            print("AI UPDATED ITSELF:", new_strategy)

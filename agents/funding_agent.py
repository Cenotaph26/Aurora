class FundingArbitrageAgent:

    def detect(self, rates):
        diff = abs(rates["binance"] - rates["bybit"])

        if diff > 0.002:
            return {"arb": True, "edge": diff}

        return {"arb": False}

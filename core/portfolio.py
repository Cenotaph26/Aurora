class PortfolioBrain:

    def __init__(self):
        self.positions = {}

    def allocate(self, signals):
        total_conf = sum(s["confidence"] for s in signals)

        for s in signals:
            s["weight"] = s["confidence"] / total_conf if total_conf else 0

        return signals

class ReflectionAgent:

    def analyze(self, trade):
        pnl = trade.get("pnl", 0)

        if pnl < 0:
            lesson = "entry timing bad"
        else:
            lesson = "trend alignment good"

        return {
            "lesson": lesson,
            "pnl": pnl
        }

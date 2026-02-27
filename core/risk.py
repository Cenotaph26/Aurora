from config import MAX_RISK

class RiskManager:

    def approve(self, trade):
        if trade["confidence"] < 0.4:
            return False

        trade["risk"] = MAX_RISK
        return True

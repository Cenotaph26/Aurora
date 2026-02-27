"""
RL Meta Agent - Pekiştirmeli Öğrenme Ağırlık Güncelleyici

Görev:
- Geçmiş sinyallerin PnL'ini izle
- Strateji ağırlıklarını ödül tabanlı güncelle (Q-learning benzeri)
- Epsilon-greedy keşif / sömürme dengesi
"""
import asyncio
import os
import json
import random
import math
from collections import defaultdict
from datetime import datetime

from utils.state import SharedState
from utils.logger import setup_logger

logger = setup_logger("RLMetaAgent")

INTERVAL    = int(os.getenv("RL_INTERVAL", "60"))
ALPHA       = float(os.getenv("RL_ALPHA", "0.1"))    # öğrenme oranı
GAMMA       = float(os.getenv("RL_GAMMA", "0.95"))   # indirim faktörü
EPSILON     = float(os.getenv("RL_EPSILON", "0.15"))  # keşif oranı


class RLMetaAgent:
    def __init__(self, state: SharedState):
        self.state = state
        # Strateji performans Q-tablosu: {strategy: {action: q_value}}
        self.q_table: dict = defaultdict(lambda: {"buy": 0.5, "sell": 0.5, "hold": 0.1})
        # Geçmiş reward birikimi
        self.reward_history = []
        self.episode = 0
        self.epsilon = EPSILON

    def compute_reward(self, signal, pnl_delta: float) -> float:
        """Sinyal yönü + PnL değişimine göre ödül hesapla"""
        if signal.direction == "buy" and pnl_delta > 0:
            return +1.0 + math.log(1 + pnl_delta)
        elif signal.direction == "sell" and pnl_delta < 0:
            return +1.0 + math.log(1 + abs(pnl_delta))
        elif signal.direction == "hold":
            return 0.0
        else:
            return -0.5  # Yanlış tahmin

    def update_q(self, strategy: str, action: str, reward: float):
        """Q-value güncelle: Q(s,a) ← Q(s,a) + α[r + γ·max Q(s',a') - Q(s,a)]"""
        current_q = self.q_table[strategy][action]
        max_next_q = max(self.q_table[strategy].values())
        new_q = current_q + ALPHA * (reward + GAMMA * max_next_q - current_q)
        self.q_table[strategy][action] = round(new_q, 6)

    def epsilon_decay(self):
        """Epsilon zamanla azalt (daha az keşif, daha fazla sömürü)"""
        self.epsilon = max(0.01, self.epsilon * 0.995)

    def get_strategy_weights(self) -> dict:
        """Q-değerlerine göre normalize strateji ağırlıkları döndür"""
        weights = {}
        for strategy, actions in self.q_table.items():
            weights[strategy] = round(sum(actions.values()) / len(actions), 4)
        total = sum(weights.values()) or 1
        return {k: round(v / total, 4) for k, v in weights.items()}

    async def run(self, shutdown: asyncio.Event):
        logger.info("🤖 RL Meta Agent başlatıldı")
        prev_pnl = 0.0

        while not shutdown.is_set():
            try:
                self.episode += 1
                current_pnl = self.state.total_pnl
                pnl_delta = current_pnl - prev_pnl
                prev_pnl = current_pnl

                # Son sinyalleri al ve ödüllerle güncelle
                signals = await self.state.get_signals()
                recent = signals[-10:] if signals else []

                for sig in recent:
                    reward = self.compute_reward(sig, pnl_delta)
                    self.update_q(sig.strategy, sig.direction, reward)
                    self.reward_history.append(reward)

                self.epsilon_decay()

                # Epsilon-greedy keşif: rastgele bir sembolde keşif sinyali
                if random.random() < self.epsilon:
                    explore_symbols = list(self.state.market_data.keys())
                    if explore_symbols:
                        sym = random.choice(explore_symbols)
                        logger.debug(f"🔍 Keşif: {sym}")

                weights = self.get_strategy_weights()
                avg_reward = (sum(self.reward_history[-20:]) / 20) if len(self.reward_history) >= 20 else 0

                metrics = {
                    "episode": self.episode,
                    "epsilon": round(self.epsilon, 4),
                    "avg_reward_20ep": round(avg_reward, 4),
                    "strategy_weights": weights,
                    "total_signals_processed": len(self.reward_history),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                self.state.rl_metrics = metrics

                logger.info(
                    f"🧬 Episode {self.episode} | ε={self.epsilon:.3f} | "
                    f"avg_reward={avg_reward:.3f} | weights={weights}"
                )
                await self.state.heartbeat("RLMetaAgent")

            except Exception as e:
                logger.error(f"RL hatası: {e}", exc_info=True)

            await asyncio.sleep(INTERVAL)

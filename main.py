"""
Aurora AI Hedge Fund - Production Entry Point
Railway'de 7/24 çalışmak üzere tasarlanmıştır.
"""
import asyncio
import signal
import sys
import logging
import os
from datetime import datetime

from agents.market_agent import MarketAgent
from agents.strategy_agent import StrategyAgent
from rl_engine.meta_agent import RLMetaAgent
from execution.executor import ExecutionAgent
from api.dashboard import start_dashboard
from utils.state import SharedState
from utils.logger import setup_logger

logger = setup_logger("main")

shutdown_event = asyncio.Event()

def handle_signal(sig, frame):
    logger.warning(f"Signal {sig} alındı, kapatılıyor...")
    shutdown_event.set()

async def main():
    logger.info("🚀 Aurora AI Hedge Fund başlatılıyor...")

    # Paylaşılan durum
    state = SharedState()

    # Ajanları oluştur
    market_agent    = MarketAgent(state)
    strategy_agent  = StrategyAgent(state)
    rl_agent        = RLMetaAgent(state)
    exec_agent      = ExecutionAgent(state)

    tasks = [
        asyncio.create_task(market_agent.run(shutdown_event),   name="MarketAgent"),
        asyncio.create_task(strategy_agent.run(shutdown_event), name="StrategyAgent"),
        asyncio.create_task(rl_agent.run(shutdown_event),       name="RLMetaAgent"),
        asyncio.create_task(exec_agent.run(shutdown_event),     name="ExecutionAgent"),
        asyncio.create_task(start_dashboard(state, shutdown_event), name="Dashboard"),
    ]

    logger.info("✅ Tüm ajanlar başlatıldı. Çalışıyor...")

    await shutdown_event.wait()

    logger.info("⏳ Ajanlar durduruluyor...")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("✅ Temiz kapatma tamamlandı.")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while not shutdown_event.is_set():
        try:
            asyncio.run(main())
        except Exception as e:
            logger.error(f"❌ Kritik hata: {e}", exc_info=True)
            logger.info("♻️  5 saniye sonra yeniden başlatılıyor...")
            import time; time.sleep(5)

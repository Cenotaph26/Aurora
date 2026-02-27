import asyncio
import traceback
from agents.market_agent import market_loop
from agents.strategy_agent import strategy_loop
from rl_engine.meta_agent import rl_loop
from execution.executor import execution_loop

async def main():
    tasks = [
        asyncio.create_task(market_loop()),
        asyncio.create_task(strategy_loop()),
        asyncio.create_task(rl_loop()),
        asyncio.create_task(execution_loop()),
    ]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception:
            print(traceback.format_exc())
            asyncio.sleep(5)
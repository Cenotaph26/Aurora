import asyncio
from core.swarm import Swarm
from config import SYMBOLS, LOOP_INTERVAL

swarm = Swarm()

async def run():
    while True:
        await swarm.cycle(SYMBOLS)
        await asyncio.sleep(LOOP_INTERVAL)

asyncio.run(run())

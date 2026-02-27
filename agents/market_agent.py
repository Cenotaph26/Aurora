import asyncio
async def market_loop():
    while True:
        print("Market Agent collecting data...")
        await asyncio.sleep(5)
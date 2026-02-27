import asyncio
async def execution_loop():
    while True:
        print("Execution Agent placing trades...")
        await asyncio.sleep(8)
class Executor:

    async def execute(self, trade):
        print(
            f"EXECUTING {trade['side']} {trade['symbol']} risk={trade['risk']}"
        )

import asyncio, sys
sys.path.insert(0, "/Users/paris/code/quasar-team/kilonova/src")
from kilonova import Server

async def main():
    server = Server(
        "/Users/paris/code/quasar-team/.parity-night/cells/atca-o6/server/Design/Design.xml",
        config_path="/Users/paris/code/quasar-team/.parity-night/cells/atca-o6/server/bin/config-simple.xml",
        endpoint="opc.tcp://0.0.0.0:48431/")
    async with server:
        await server.objects["asmemf-dro-02.Slot 1"].setSlotNumber(7)
        print("SERVING", flush=True)
        await asyncio.sleep(600)

asyncio.run(main())

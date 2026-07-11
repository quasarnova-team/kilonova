"""The microquasar hello-world: the MilkyWay SCA demo, 2026 edition.

Serves an SCA object from a quasar Design and ticks its ``online`` counter —
functionally identical to MilkyWay's 2021 main.py, now async and config-driven.

Run:  python demo.py         then browse opc.tcp://localhost:4841 with any client.
"""

import asyncio
from pathlib import Path

from microquasar import Server

HERE = Path(__file__).parent


async def main() -> None:
    server = Server(HERE / "Design.xml", config_path=HERE / "config.xml")
    async with server:
        sca1 = server.objects["sca1"]
        print("serving on opc.tcp://0.0.0.0:4841 — Ctrl-C to stop")
        counter = 0
        while True:
            await asyncio.sleep(1)
            counter += 1
            await sca1.setOnline(counter)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")

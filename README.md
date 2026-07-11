# microquasar

**Pure-Python OPC UA servers from quasar Design files — a quasar in miniature.**

A *microquasar* is a stellar-mass object inside the Milky Way whose accretion disk and
relativistic jets reproduce quasar physics in miniature. That is precisely this project:
a small, pure-Python engine that lives in the [MilkyWay](https://github.com/quasar-team/MilkyWay)
lineage and behaves exactly like [quasar](https://github.com/quasar-team/quasar) — it loads a
standard quasar `Design.xml` and `config.xml` and serves the identical OPC UA address space,
with **no code generation and no C++**.

Because the served address space uses quasar's addressing (`ns=2` string NodeIds with dotted
`parent.child` paths), everything downstream of a quasar server keeps working:
[UaoForQuasar](https://github.com/quasar-team/UaoForQuasar) clients,
[Cacophony](https://github.com/quasar-team/Cacophony)/WinCC OA integration, and plain OPC UA
clients that know quasar conventions.

## Quick start

```bash
pip install microquasar          # not yet on PyPI — install from source for now
microquasar run --design Design.xml --config config.xml
```

Or from Python, async-first:

```python
import asyncio
from microquasar import Server

async def main():
    server = Server("Design.xml", config_path="config.xml")
    async with server:
        sca1 = server.objects["sca1"]
        while True:
            await asyncio.sleep(1)
            await sca1.setOnline(42)   # typed setter, generated from the Design

asyncio.run(main())
```

## Parity is the product

microquasar's definition of done is **oracle parity with C++ quasar**: for every test case in
quasar's own CI suite (`quasar/.CI/test_cases/`), microquasar must serve an address space whose
client-side NodeSet2 dump matches the case's `reference_ns2.xml`. See `PLAN.md` for the
milestone-by-milestone roadmap and the current parity table.

## Lineage

quasar → MilkyWay (Piotr Nikiel's 2021 pure-Python prototype) → **microquasar** (2026, from
scratch on [asyncua](https://github.com/FreeOpcUa/opcua-asyncio) 2.x).

## License

BSD-2-Clause.

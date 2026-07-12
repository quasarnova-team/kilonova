# kilonova

Pure-Python OPC UA servers from quasar Design files — the
[quasarnova](https://quasarnova-team.github.io/) family's no-codegen engine.

kilonova takes the same `Design.xml` + `config.xml` a C++ quasar server consumes and
serves the same OPC UA address space — same NodeIds, same types, same behaviour — with
no generator, no compiler and no build step. It passes the upstream quasar framework's
complete public conformance suite, on every commit, on three operating systems.

## Install

```bash
pip install kilonova
```

## A server in one command

```bash
kilonova run --design Design.xml --config config.xml
# serving on opc.tcp://0.0.0.0:4841/  (Ctrl-C to stop)
```

## Or as a library

```python
from kilonova import Server

server = Server("Design.xml", config_path="config.xml")

@server.read("ps1.current")
def read_current(obj):              # plain def: runs in a thread pool —
    return driver.read_current()    # blocking drivers cannot stall the server

@server.method("ps1.switchOn")
async def switch_on(obj):
    await obj.setState(1)

async with server:
    ...
```

## Where to next

- **[Device logic](DeviceLogic.md)** — the entire user API: cache and source variables,
  methods, blocking calls and the thread pool, synchronization domains.
- **[Architecture](Architecture.md)** — how a Design file becomes a served address space.
- **[Calculated variables](CalculatedVariables.md)** — formulas, exactly the upstream dialect.
- **[Parity](Parity.md)** — the conformance contract and current status.
- [Changelog](https://github.com/quasarnova-team/kilonova/blob/main/CHANGELOG.md) ·
  [PyPI](https://pypi.org/project/kilonova/) ·
  [GitHub](https://github.com/quasarnova-team/kilonova)

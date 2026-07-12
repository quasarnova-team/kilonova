# kilonova

[![CI](https://github.com/quasarnova-team/kilonova/actions/workflows/ci.yml/badge.svg)](https://github.com/quasarnova-team/kilonova/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/kilonova)](https://pypi.org/project/kilonova/)
[![docs](https://img.shields.io/badge/docs-quasarnova--team.github.io%2Fkilonova-blue)](https://quasarnova-team.github.io/kilonova/)

What is this?
-------------

Describe your device once in a declarative XML model and kilonova serves it as a
complete, standards-compliant OPC UA server — in pure Python, with no code generation,
no compiler and no build step. kilonova is fully compatible with Design files from the
[quasar framework](https://github.com/quasar-team/quasar): it produces the same address
space (same `ns=2` string NodeIds, same dotted `parent.child` addressing), so quasar
ecosystem tools — [Cacophony](https://github.com/quasar-team/Cacophony)/WinCC OA address
generation, [UaoForQuasar](https://github.com/quasar-team/UaoForQuasar) clients, plain
OPC UA clients — work against it unmodified.

Built for the jobs where a server must exist *now*: device simulators, test rigs,
FAT/SAT stand-ins, CI test doubles, edge gateways for network-attached hardware, and
reference implementations while the C++ server is still being written.

A *kilonova* is the luminous flash of a neutron-star merger — a lighter, faster transient
in the nova family. This kilonova is the pure-Python engine of the
[quasarnova](https://github.com/quasarnova-team) family: successor of
[MilkyWay](https://github.com/quasar-team/MilkyWay) (the 2021 pure-Python prototype),
rebuilt from scratch on [asyncua](https://github.com/FreeOpcUa/opcua-asyncio) 2.x.

Basic usage mode
----------------

1. Install (Python ≥ 3.10): `pip install kilonova`
1. Run your existing quasar server's design, unchanged:
   `kilonova run --design Design/Design.xml --config bin/config.xml`
1. Point any OPC UA client at `opc.tcp://host:4841` — the address space is quasar's.
1. Dump a running server's address space (uasak_dump-style NodeSet2):
   `kilonova dump --endpoint opc.tcp://127.0.0.1:4841 --output dump.xml`

Device logic is plain Python (see [doc/DeviceLogic.md](doc/DeviceLogic.md)):

```python
from kilonova import Server

server = Server("Design.xml", config_path="config.xml")

@server.read("sca1.adc")                 # source variable: runs inside the client read
async def read_adc(obj):
    return await hardware.read_adc()

@server.read("sca1.temperature")         # plain def: kilonova runs it in its thread
def read_temperature(obj):               # pool, so blocking drivers cannot stall
    return driver.read_temperature()     # the server

@server.method("sca1.reset")             # method handler
async def reset(obj):
    await obj.setOnline(0)               # generated setter, quasar naming

async with server:
    ...
```

What works
----------

All 12 cases of the upstream quasar framework's own public CI test suite pass against
the reference nodesets (cache/source/calculated variables, methods incl. arguments,
config entries and restrictions, singleVariableNode, design/config instantiation,
StandardMetaData) — checked on every commit on Linux/macOS/Windows, Python 3.10–3.14,
and re-run nightly against upstream master. Beyond the suite, kilonova was probed
against live C++ servers built from real production designs on both C++ backends: two
designs at full structural parity, a third surfacing genuine cross-backend differences
(kilonova sides with one backend on each). Details: [doc/Parity.md](doc/Parity.md).

Limitations
-----------

- Device logic is registered per address at runtime — there is no generated `D<Class>`
  skeleton (that is the point).
- Design-mandated children are instantiated unconditionally; C++ device logic may create
  some conditionally.
- Security: user/password logon and Basic256Sha256 policies via ServerConfig.xml;
  client-certificate trust lists are not supported yet.
- Values live in asyncua's address space; extreme write rates were not a design goal.

Documentation
-------------

- [doc/Architecture.md](doc/Architecture.md) — modules and data flow
- [doc/DeviceLogic.md](doc/DeviceLogic.md) — the user API
- [doc/CalculatedVariables.md](doc/CalculatedVariables.md) — formulas, exactly the C++ dialect
- [doc/Parity.md](doc/Parity.md) — the parity contract and current status
- [ROADMAP.md](ROADMAP.md) — where this is going
- [CHANGELOG.md](CHANGELOG.md) — release history
- Upstream quasar framework documentation (the inherited Design language):
  https://quasar.docs.cern.ch

Heritage
--------

quasarnova builds on the lineage of the open-source
[quasar framework](https://github.com/quasar-team/quasar), developed at CERN and running
large-scale control systems for more than a decade. quasarnova is an independent project
and is not affiliated with or endorsed by CERN. The Design-driven approach and the
[MilkyWay](https://github.com/quasar-team/MilkyWay) prototype are due to the upstream
quasar project and its authors.

Interface stability
-------------------

From 1.0.0, kilonova follows semantic versioning. The public API is
`kilonova.Server` (constructor arguments, `objects`, the `method`/`read`/`write`
decorators, `offload`), `kilonova.Design`, `QuasarObject` (`set_cv`/`get_cv`/generated setters)
and the exceptions in `kilonova.errors`. Anything imported from other modules is
internal. Breaking changes get a deprecation release first.

Contact: [GitHub Issues](https://github.com/quasarnova-team/kilonova/issues) ·
[Discussions](https://github.com/quasarnova-team/kilonova/discussions)

License: BSD-2-Clause. © the quasarnova team.

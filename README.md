# kilonova

[![CI](https://github.com/quasarnova-team/kilonova/actions/workflows/ci.yml/badge.svg)](https://github.com/quasarnova-team/kilonova/actions/workflows/ci.yml)

What is this?
-------------

kilonova serves a quasar `Design.xml` + `config.xml` as a live OPC UA server in pure
Python — no code generation, no C++. It produces the same address space as a
[quasar](https://github.com/quasar-team/quasar)-generated server (same `ns=2` string NodeIds,
same dotted `parent.child` addressing), so quasar ecosystem tools —
[Cacophony](https://github.com/quasar-team/Cacophony)/WinCC OA,
[UaoForQuasar](https://github.com/quasar-team/UaoForQuasar) clients, plain OPC UA clients —
work against it unmodified.

A *kilonova* is the luminous flash of a neutron-star merger — a lighter, faster transient
in the nova family. This kilonova is the pure-Python engine of the
[quasarnova](https://github.com/quasarnova-team) family: successor of
[MilkyWay](https://github.com/quasar-team/MilkyWay) (Piotr Nikiel's 2021 pure-Python
prototype; this rewrite was briefly named microquasar), rebuilt from scratch on
[asyncua](https://github.com/FreeOpcUa/opcua-asyncio) 2.x.

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

@server.method("sca1.reset")             # method handler
async def reset(obj):
    await obj.setOnline(0)               # generated setter, quasar naming

async with server:
    ...
```

What works
----------

All 12 cases of quasar's own CI test suite pass against the reference nodesets
(cache/source/calculated variables, methods incl. arguments, config entries and
restrictions, singleVariableNode, design/config instantiation, StandardMetaData).
Production designs were probed against live C++ servers of both backends: ATCA and CAEN at
full structural parity; CanOpen surfaced two genuine C++ cross-backend quirks (kilonova sides
with one backend on each). Details: [doc/Parity.md](doc/Parity.md).

Limitations
-----------

- Device logic is registered per address at runtime — there is no generated `D<Class>`
  skeleton (that is the point).
- Design-mandated children are instantiated unconditionally; C++ device logic may create
  some conditionally.
- No server-side security policies yet (NoSecurity endpoint only).
- Values live in asyncua's address space; extreme write rates were not a design goal.

Documentation
-------------

- [doc/Architecture.md](doc/Architecture.md) — modules and data flow
- [doc/DeviceLogic.md](doc/DeviceLogic.md) — the user API
- [doc/CalculatedVariables.md](doc/CalculatedVariables.md) — formulas, exactly the C++ dialect
- [doc/Parity.md](doc/Parity.md) — the parity contract and current status
- [PLAN.md](PLAN.md) — milestone log, parity backlog, engineering notes
- [CHANGELOG.md](CHANGELOG.md) — release history
- quasar framework documentation: https://quasar.docs.cern.ch

Credits
-------

- Paris Moschovakos (paris@moschovakos.com) — kilonova
- Piotr Nikiel — quasar concept and architecture; MilkyWay, the predecessor

Interface stability
-------------------

From 1.0.0, kilonova follows semantic versioning. The public API is
`kilonova.Server` (constructor arguments, `objects`, the `method`/`read`/`write`
decorators), `kilonova.Design`, `QuasarObject` (`set_cv`/`get_cv`/generated setters)
and the exceptions in `kilonova.errors`. Anything imported from other modules is
internal. Breaking changes get a deprecation release first.

Contact: paris@moschovakos.com

License: BSD-2-Clause.

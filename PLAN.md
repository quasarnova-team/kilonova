# microquasar — implementation plan

One feature at a time; every step lands with tests, and every user-visible behaviour is tested
**from the UX**: a real asyncua `Client` connects to the running server and reads the address
space, exactly as WinCC OA, UaoForQuasar, or uasak_dump would.

## The parity contract

The oracle is quasar's own CI: `quasar/.CI/test_cases/manifest.json` declares ~12 cases, each
with `Design.xml` + `config.xml` + `reference_ns2.xml`. The gate (same semantics as
`NodeSetTools/nodeset_compare.py`):

- every `UAObject` / `UAVariable` / `UAMethod` NodeId in the reference must exist exactly once
  in our client-side dump;
- every attribute present in the reference (`BrowseName`, `DataType`, `ValueRank`,
  `AccessLevel`) must match exactly. Format rules learned from uasak_dump: NS0 ids as `i=N`,
  quasar ids as `ns=2;s=path`, XSD-default attributes suppressed (DataType `i=24`,
  ValueRank `-1`, AccessLevel `1`);
- `StandardMetaData` nodes are ignored until the StandardMetaData milestone lands.

## Milestones

| # | Feature | UX test gate | Status |
|---|---------|--------------|--------|
| M0 | Scaffold: pyproject/uv, ruff, pytest, git | `uv run pytest` runs | in progress |
| M1 | Design layer: typed `Design.xml` parser | parses all quasar CI test-case designs | pending |
| M2 | Server core on asyncua: boot, ns=2, ObjectTypes | Client connects, browses, finds types | pending |
| M3 | Config instantiation: recursive objects, dotted string NodeIds | Client resolves exact NodeIds from config tree | pending |
| M4 | Cache variables: DataType/ValueRank/AccessLevel/initialValue+Status | Client reads every attribute + value + status | pending |
| M5 | MilkyWay parity: `set_cv`, generated `setXxx` setters, live demo | Client subscribes, sees ticking value | pending |
| M6 | Conformance runner + dumper (uasak_dump equivalent) | parity table over quasar CI cases | pending |
| M7 | Methods: nodes + real async handlers (decorator API) | Client calls method, gets result | pending |
| M8 | Source variables: async read/write callbacks | Client read triggers user coroutine | pending |
| M9 | CalculatedVariables (safe formula eval) | Client reads computed value | pending |
| M10 | StandardMetaData subtree | default_design case passes un-ignored | pending |
| M11 | Config XSD validation + restrictions | invalid config rejected like C++ Configurator | pending |
| M12 | Ecosystem smoke: UaoForQuasar client + Cacophony against microquasar | generated client works unmodified | pending |

## Current parity table (M6 gate, StandardMetaData ignored)

Run `uv run pytest tests/conformance -v` with a quasar checkout next door.
Populated by the conformance runner once M6 lands — no claims before the tests pass.

## Design decisions (2026 rewrite, vs the 2021 MilkyWay prototype)

- **asyncua 2.x** (python-opcua is deprecated); async-first, `asyncio.run` friendly.
- **No copy-paste of quasar's DesignInspector** — a clean-room typed design layer
  (`design.py`) exposing only what the server needs.
- **Setters done right**: `set` + upper-first camelCase (`setMyVar`, not `.title()`), async.
- **DataType always set from the Design** (the 2021 prototype derived it from values;
  null-initialized variables then reported BaseDataType).
- **Conformance from day one**: the dumper reads the address space through a real client
  connection — testing "from the UX" is the default, not an afterthought.
- The 2021 bugs are regression-tested: initialStatus actually applied, numeric initialValue
  works, unsupported config elements raise instead of NameError-ing.

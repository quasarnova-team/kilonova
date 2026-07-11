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
| M0 | Scaffold: pyproject/uv, ruff, pytest, git | `uv run pytest` runs | done |
| M1 | Design layer: typed `Design.xml` parser | parses all quasar CI test-case designs | done |
| M2 | Server core on asyncua: boot, ns=2, ObjectTypes | Client connects, browses, finds types | done |
| M3 | Config instantiation: recursive objects, dotted string NodeIds | Client resolves exact NodeIds from config tree | done |
| M4 | Cache variables: DataType/ValueRank/AccessLevel/initialValue+Status | Client reads every attribute + value + status | done |
| M5 | MilkyWay parity: `set_cv`, generated `setXxx` setters, live demo | Client subscribes, sees ticking value | done |
| M6 | Conformance runner + dumper (uasak_dump equivalent) | parity table over quasar CI cases | done |
| M7 | Methods: nodes + real async handlers (decorator API) | Client calls method, gets result | done |
| M8 | Source variables + delegated-write callbacks | Client read/write triggers user coroutine | pending |
| M9 | CalculatedVariables (safe formula eval) | Client reads computed value | pending |
| M10 | StandardMetaData subtree | default_design case passes un-ignored | pending |
| M11 | Config XSD validation + restrictions | invalid config rejected like C++ Configurator | pending |
| M12 | Ecosystem smoke: UaoForQuasar client + Cacophony against microquasar | generated client works unmodified | pending |

## Current parity table (M6 gate, StandardMetaData ignored)

Run `uv run pytest tests/conformance -v` with a quasar checkout next door.
As of M6 (all verified by `pytest tests/conformance`, 2026-07-11):

| quasar CI case | verdict |
|----------------|---------|
| default_design | PASS |
| methods | PASS |
| async_methods | PASS |
| cache_variables | PASS |
| config_entries | PASS |
| recurrent_hasobjects | PASS |
| single_variable_node | PASS |
| instantiation_from_design | PASS |
| config_restrictions | PASS |
| defaulted_instance_name | PASS |
| source_variables | xfail (M8) |
| calculated_variables | xfail (M9) |

Method *nodes* (incl. `.args`/`.return_values` argument properties) are at parity as part of
M6; M7 added callable handlers via the `@server.method("sca1.scale")` decorator API.

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

## Parity rules learned the hard way (2026-07-11 adversarial review)

A 38-agent review panel with live-repro verification found parity bugs the M6 gate is
structurally blind to (the comparison is one-directional and value-less). All fixed and
regression-tested in `tests/test_robustness.py`:

- **DataType follows nullPolicy**: C++ quasar sets the concrete DataType only for
  `nullForbidden` variables; `nullAllowed` ones serve BaseDataType (i=24) so null writes
  stay legal. (asyncua's type heuristic refuses writes to BaseDataType nodes — instance-local
  override in `Server._allow_writes_to_base_datatype_nodes`, worth upstreaming.)
- **Arrays are `<value>` elements** in config.xml (quasar's generated Configuration.xsd);
  text-content arrays are rejected loudly, as the C++ Configurator would.
- **`defaultConfigInitializerValue`** is honoured when the config omits a value.
- **singleVariableNode instances** take configuration values.
- **Array config entries** are NOT published as properties (C++ skips them).
- Robustness: unknown config attributes/children and out-of-range integers are rejected at
  load; `set_cv` raises on refused writes and range violations; method calls validate
  argument counts (BadArgumentsMissing/BadTooManyArguments).

Known gate limitations (roadmap): the comparer checks only NodeId+attributes (like quasar's
own CI) — values and references are dumped but not compared; strengthening it beyond the C++
gate is future work alongside M11.

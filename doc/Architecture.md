# Architecture

What is this?
-------------

How a Design file becomes a served address space. One page; each module has one job.

Data flow
---------

```
Design.xml ──> design.py ──────┐
                               ├──> address_space.py ──> asyncua Server (ns=2)
config.xml ──> config.py ──────┘         │
                                         ├── objects.py     QuasarObject handles, setters
                                         ├── calculated.py  formulas + recalculation graph
                                         └── meta.py        StandardMetaData subtree
server.py orchestrates; dispatches methods / source reads / delegated writes
dump.py    reads it all back through a real client (uasak_dump equivalent)
```

Modules
-------

| Module | Job |
|--------|-----|
| `design.py` | Typed, frozen model of Design.xml. Total over quasar's CI corpus; unknown constructs fail loudly at instantiation, not parsing. |
| `config.py` | config.xml → instance tree. Validates like the C++ Configurator: unknown attributes/children, hasobjects, `<value>` arrays, restrictions input. |
| `oracle.py` | quasar dataType ↔ OPC UA type maps, value parsing, integer ranges, configRestriction checks. (Named after quasar's own Oracle.) |
| `address_space.py` | Builds ObjectTypes (`ns=2;i=1000+`) and instances (`ns=2;s=parent.child`). Owns the parity-critical attribute rules. |
| `objects.py` | `QuasarObject`: `set_cv`, `get_cv`, generated `setXxx` async setters. |
| `server.py` | Lifecycle + handler registries (`@server.method/read/write`), source-read PreRead hook, delegated-write interception. |
| `calculated.py` | Config-level CalculatedVariables/FreeVariables: whitelisted-AST formulas (no `eval`), datachange-driven recalculation. |
| `meta.py` | StandardMetaData, live: log-level nodes drive Python logging. |
| `dump.py` | Client-side NodeSet2 dump + reference comparison (the conformance gate). |
| `server_config.py` | quasar ServerConfig.xml: endpoint, security policies, identity tokens. |
| `cli.py` | `kilonova run` / `kilonova dump`, clean SIGTERM shutdown. |
| `errors.py` | `KilonovaError` base; `DesignError`, `ConfigurationError`. |

Design decisions
----------------

- **asyncua 2.x, async-first.** Reads of source variables await device coroutines *inside*
  the read transaction (asyncua PreRead callback); calculated variables recompute inside the
  write that changed an input. The 2021 sync prototype could do neither.
- **No copy-paste of DesignInspector.** The design layer is clean-room and typed; drift
  against quasar is caught by parsing quasar's whole CI corpus in the test suite.
- **Parity rules live in one place** (`address_space.py`): DataType is concrete only for
  `nullPolicy="nullForbidden"` (else BaseDataType), ValueRank −1/1/−3 (scalar/array/UaVariant),
  AccessLevel from `addressSpaceWrite` or source read/write modes.
- **Handlers are late-bound by address.** Registration works before or after `start()`;
  unregistered methods/writes answer proper OPC UA status codes.
- **One asyncua override**, documented in `server.py`: BaseDataType variables accept any
  concrete value type (OPC UA Part 3 semantics; upstream FIXME).

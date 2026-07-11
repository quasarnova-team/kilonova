# Parity

What is this?
-------------

microquasar's definition of done: serve the address space the C++ quasar framework would,
verified — never claimed. Two gates exist; both read the server through a real OPC UA
client connection.

Gate 1: quasar's own CI oracle
------------------------------

`tests/conformance` loads `quasar/.CI/test_cases/manifest.json`, serves each case's
Design + config in-process, dumps the address space (uasak_dump-compatible NodeSet2) and
compares it against the case's `reference_ns2.xml`:

1. Have a quasar checkout next door (or set `MICROQUASAR_QUASAR_ROOT`).
1. `uv run pytest tests/conformance -v`

Comparison semantics (same as quasar's NodeSetTools): every `UAObject`/`UAVariable`/
`UAMethod` NodeId in the reference must exist exactly once in the dump, with every
reference attribute (`BrowseName`, `DataType`, `ValueRank`, `AccessLevel`) equal.
`StandardMetaData` is ignored except for the `default_design` case, whose reference *is*
the meta oracle (quasar's own CI ignores it everywhere; the checked-in references carry
mutually contradictory meta snapshots).

Current status: **12/12 cases PASS.**

Gate 2: live production servers
-------------------------------

The `.parity-night` campaign compares probes of real servers. microquasar runs as a third
backend column, no docker/build:

```
bash .parity-night/scripts/run_microquasar_cell.sh <cell> <server-src> <config.xml> <port>
python3 .parity-night/scripts/compare.py cells/<a>/probe.json cells/<b>/probe.json
```

Results (2026-07-11): ATCA and CAEN at full structural parity vs both live C++ backends;
CanOpen surfaced two genuine cross-backend deltas (method-argument AccessLevel: microquasar
agrees with UASDK; FreeVariable writability: microquasar agrees with open62541).

Expected, accepted differences
------------------------------

- Source variables report `err:BadWaitingForInitialData` where C++ device logic answers —
  a microquasar cell has no device logic.
- LogIt components in StandardMetaData reflect each build (`mule`, `ThreadPool`,
  `open62541` on C++; microquasar serves its own subsystems).
- Design-mandated children are instantiated unconditionally (C++ device logic may skip
  some at runtime).

Ecosystem cross-checks
----------------------

- Cacophony: `tools/cacophony_crosscheck.py` verifies every periphery address the
  generated `configParser.ctl` would assign resolves on a live microquasar —
  600/600 on the production ATCA design.
- UaoForQuasar: client classes generate cleanly from production designs; the generated
  NodeId construction is exactly microquasar's addressing. Compile/run of the C++ client
  needs UASDK (docker) — pending.

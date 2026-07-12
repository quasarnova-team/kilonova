# Parity

What is this?
-------------

kilonova's definition of done: serve the address space the C++ quasar framework would,
verified — never claimed. Two gates exist; both read the server through a real OPC UA
client connection.

Gate 1: quasar's own CI oracle
------------------------------

`tests/conformance` loads `quasar/.CI/test_cases/manifest.json`, serves each case's
Design + config in-process, dumps the address space (uasak_dump-compatible NodeSet2) and
compares it against the case's `reference_ns2.xml`:

1. Have a quasar checkout next door (or set `KILONOVA_QUASAR_ROOT`).
1. `uv run pytest tests/conformance -v`

Comparison semantics (same as quasar's NodeSetTools): every `UAObject`/`UAVariable`/
`UAMethod` NodeId in the reference must exist exactly once in the dump, with every
reference attribute (`BrowseName`, `DataType`, `ValueRank`, `AccessLevel`) equal.
`StandardMetaData` is ignored except for the `default_design` case, whose reference *is*
the meta oracle (quasar's own CI ignores it everywhere; the checked-in references carry
mutually contradictory meta snapshots).

Current status: **12/12 cases PASS.**

Gate 2: live servers from real designs
--------------------------------------

A local cross-backend probe harness (a campaign workspace, not part of this repository)
compares client-side probes of live servers built from real production-grade designs.
kilonova runs as a third backend column next to the two C++ backends — no docker, no
build step.

Results (2026-07-11), across three real designs: two at full structural parity vs both
live C++ backends; the third surfaced two genuine cross-backend deltas between the C++
backends themselves (method-argument AccessLevel: kilonova agrees with one backend;
FreeVariable writability: kilonova agrees with the other).

Expected, accepted differences
------------------------------

- Source variables report `err:BadWaitingForInitialData` where C++ device logic answers —
  a kilonova cell has no device logic.
- LogIt components in StandardMetaData reflect each build (`mule`, `ThreadPool`,
  `open62541` on C++; kilonova serves its own subsystems).
- Design-mandated children are instantiated unconditionally (C++ device logic may skip
  some at runtime).

Ecosystem cross-checks
----------------------

- Cacophony (WinCC OA address generation): `tools/cacophony_crosscheck.py` verifies
  every periphery address the generated `configParser.ctl` would assign resolves on a
  live kilonova — 600/600 addresses on a large real-world design.
- UaoForQuasar (generated C++ clients): a generated client class, compiled against a
  UA-SDK-compatible stack, connected to a live kilonova and read back a value set by
  Python device logic (harness preserved in `tools/uao_client_check`).
- A direct live WinCC OA connection has not been exercised yet; the Cacophony address
  cross-check above covers the address layer WinCC OA subscribes through.

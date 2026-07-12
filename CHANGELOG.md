# ChangeLog

1.1.0 (2026-07-12)
------------------
- Blocking device logic: plain `def` handlers (read/write/method) now run in a
  server thread pool (`Server(offload_workers=8)`) — a blocking driver call
  delays its own transaction, never the server. `async def` handlers are
  unchanged (event loop, must not block). New `server.offload(func, *args)`
  awaits a blocking callable from async handlers.
  **Behaviour change:** before 1.1 a plain `def` handler ran inline on the
  event loop (undocumented). Such a handler now runs in a worker thread: it
  must not call asyncio APIs (the server logs a targeted hint if it does) and
  it may run concurrently with other handlers unless a mutex domain says
  otherwise. Documented (`async def`) handlers are unaffected.
- Loop watchdog (`Server(watchdog=0.25)`, seconds; `None` disables): logs a
  warning when something blocks the event loop, naming the device logic that
  overlapped the stall.
- Independent source variables in one read transaction now refresh
  concurrently; Design mutex domains still serialize what they declare.
- Source-variable timestamps are taken after the read handler returns.
- PyPI Development Status reclassified Stable -> Beta: honest staging until
  there is external production use (the 1.0.0 entry below predates this).

1.0.0 (2026-07-11)
------------------
- Enforced security: user/password authentication (ServerConfig identity
  tokens + Server(users=...)); anonymous logon rejectable.
- handpicked mutex domain: C++ semantics (developer holds the lock).
- Scale gate in CI: 2000-variable server under sustained churn with live
  subscription, bounded memory.
- CI: Python 3.10-3.14, Linux/macOS/Windows, nightly conformance run
  against quasar master (upstream drift detection).
- Interface stability commitment (semver); Development Status: Stable.

0.1.1 (2026-07-11)
------------------
- Parity: configentry defaultValue served and required-ness enforced; d:array
  minimumSize/maximumSize enforced; isKey uniqueness among siblings; FreeVariable
  accessLevel (R/RW/W); calculated-variable bad-input status split (Bad vs
  BadWaitingForInitialData, C++ semantics); design namespace URI now OPCUASERVER.
- CLI: --version, --config_file alias, --opcua_backend_config, clean SIGTERM shutdown.
- Full muParser formula dialect + meta-functions; CalculatedVariable
  initialValue/isBoolean/status; synchronization domains (Design mutexes as
  asyncio locks); strict config schema (required-ness incl. cache variables);
  design semantic validation; SVN method nodes; ServerConfig.xml
  (endpoint/security/identity); ArrayDimensions; null Descriptions.

0.1.0 (2026-07-11)
------------------
- First release. Pure-Python OPC UA servers from quasar Design files.
- 12/12 oracle parity with quasar's own CI test suite.
- Async device logic (@server.method/read/write), calculated variables,
  StandardMetaData, config restrictions, cardinality validation.
- Verified against live C++ servers built from three real production-grade designs.

# ChangeLog

0.1.1 (unreleased)
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
- Verified against live production C++ servers (ATCA, CAEN, CanOpen).

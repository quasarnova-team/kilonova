# ChangeLog

0.1.1 (unreleased)
------------------
- Parity: configentry defaultValue served and required-ness enforced; d:array
  minimumSize/maximumSize enforced; isKey uniqueness among siblings; FreeVariable
  accessLevel (R/RW/W); calculated-variable bad-input status split (Bad vs
  BadWaitingForInitialData, C++ semantics); design namespace URI now OPCUASERVER.
- CLI: --version, --config_file alias, clean SIGTERM shutdown.

0.1.0 (2026-07-11)
------------------
- First release. Pure-Python OPC UA servers from quasar Design files.
- 12/12 oracle parity with quasar's own CI test suite.
- Async device logic (@server.method/read/write), calculated variables,
  StandardMetaData, config restrictions, cardinality validation.
- Verified against live production C++ servers (ATCA, CAEN, CanOpen).

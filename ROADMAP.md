# Roadmap

Honest and short. Dates are intentions, not promises; the
[CHANGELOG](CHANGELOG.md) records what actually shipped.

## kilonova (this repo)

- **v1.2 — first-run experience:** `kilonova demo` (bundled example design, one command
  to a running server) and `kilonova init` (scaffold Design.xml + config + device-logic
  skeleton). An examples gallery of runnable designs.
- **Evaluator trust pack:** dedicated docs pages for security posture, licensing FAQ,
  and versioning/support/continuity policy.
- **Security:** client-certificate trust list enforcement.
- Continuous: 12/12 conformance against upstream quasar's public CI suite on every
  commit; nightly drift run against upstream master.

## The wider family

- **supernova** (C++ engine, [repo](https://github.com/quasarnova-team/supernova)):
  OPC UA Pub/Sub (publisher + subscriber) on both supported stacks. In development;
  first tagged release gated on clean-machine buildability, complete Pub/Sub docs and
  a 60-second demo.
- **dwarfnova** (typed client generation) and **rednova** (SCADA integration):
  design-stage ideas, no code yet. They will not be promoted until they exist.

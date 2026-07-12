# Contributing to kilonova

Thanks for considering it. Questions and ideas are welcome in
[Discussions](https://github.com/quasarnova-team/kilonova/discussions); bugs and
concrete proposals in [Issues](https://github.com/quasarnova-team/kilonova/issues).

## Development setup

```bash
git clone https://github.com/quasarnova-team/kilonova
cd kilonova
uv sync                 # or: pip install -e . --group dev
uv run pytest           # unit tests
uv run ruff check src tests examples tools
```

## Running the conformance suite

The parity gate replays the upstream quasar framework's own public CI cases:

```bash
git clone https://github.com/quasar-team/quasar ../quasar   # or anywhere
KILONOVA_QUASAR_ROOT=../quasar uv run pytest tests/conformance -v
```

All 12 cases must pass. If your change affects the served address space, this suite is
the arbiter — see [doc/Parity.md](doc/Parity.md) for the comparison semantics.

## Pull requests

- One topic per PR, with tests for any behaviour change. A parity-affecting change
  needs a green conformance run.
- Match the surrounding style; `ruff` settles formatting arguments.
- CI runs on Linux/macOS/Windows across Python 3.10–3.14 — please don't use
  platform-specific APIs without a guard (see `tests/test_scale.py` for the pattern).
- Breaking API changes need a deprecation path (see "Interface stability" in the
  README).

## Reporting security issues

Please do not open public issues for suspected vulnerabilities — see
[SECURITY.md](SECURITY.md).

"""M6 — the parity gate: kilonova vs quasar's own CI oracle.

For every case in quasar/.CI/test_cases/manifest.json we serve the case's
Design + config in-process, dump the address space through a real client
connection, and compare against the case's reference_ns2.xml with the same
semantics as quasar's NodeSetTools comparison. StandardMetaData is ignored
until M10.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kilonova import Server
from kilonova.dump import compare_nodesets, dump_address_space, load_nodeset
from tests.conftest import free_port

QUASAR_ROOT = Path(
    os.environ.get("KILONOVA_QUASAR_ROOT", Path(__file__).resolve().parents[3] / "quasar")
)
CASES_DIR = QUASAR_ROOT / ".CI" / "test_cases"

# Cases whose features are planned but not implemented yet (see PLAN.md).
NOT_YET: dict[str, str] = {}

pytestmark = pytest.mark.skipif(
    not (CASES_DIR / "manifest.json").exists(),
    reason="quasar checkout with .CI/test_cases not found",
)


def _load_cases() -> list[dict]:
    manifest = json.loads((CASES_DIR / "manifest.json").read_text())
    return [case for case in manifest["cases"] if case.get("kind") == "oracle"]


def _params():
    if not (CASES_DIR / "manifest.json").exists():
        return []
    params = []
    for case in _load_cases():
        marks = []
        if case["name"] in NOT_YET:
            marks.append(pytest.mark.xfail(reason=NOT_YET[case["name"]], strict=True))
        params.append(pytest.param(case, id=case["name"], marks=marks))
    return params


@pytest.mark.parametrize("case", _params())
async def test_parity_with_quasar_reference(case):
    design_path = (
        CASES_DIR / case["design"] if "design" in case
        else QUASAR_ROOT / "Design" / "Design.xml"
    )
    config_path = CASES_DIR / case["config"] if "config" in case else None
    oracle_path = CASES_DIR / case["oracle"]

    url = f"opc.tcp://127.0.0.1:{free_port()}/"
    server = Server(design_path, config_path=config_path, endpoint=url)
    async with server:
        dump = await dump_address_space(url)

    # quasar's own CI ignores StandardMetaData everywhere (the references carry
    # stale, mutually-contradictory meta snapshots — e.g. minThreads is i=7 in one
    # ref and i=12 in another). We go one step further than C++: default_design's
    # reference IS the meta oracle, so that case is compared in full.
    ignore = () if case["name"] == "default_design" else ("StandardMetaData",)
    failures = compare_nodesets(
        load_nodeset(str(oracle_path)), dump, ignore_nodeid_substrings=ignore
    )
    assert not failures, (
        f"{len(failures)} parity failure(s) vs {oracle_path.name}:\n" + "\n".join(failures)
    )

"""M1 — the typed Design layer."""

import os
from pathlib import Path

import pytest

from microquasar.design import Design

DATA = Path(__file__).parent / "data"
QUASAR_ROOT = Path(
    os.environ.get("MICROQUASAR_QUASAR_ROOT", Path(__file__).resolve().parents[2] / "quasar")
)


def test_parses_the_sca_design():
    design = Design.from_file(DATA / "Design.xml")
    assert design.project_short_name == "ScaDemo"
    assert set(design.classes) == {"SCA", "Chip"}

    sca = design.classes["SCA"]
    assert [cv.name for cv in sca.cache_variables] == ["online", "id", "temperature", "channels"]
    assert [m.name for m in sca.methods] == ["reset"]
    assert sca.has_device_logic

    online = sca.cache_variable("online")
    assert online.data_type == "OpcUa_UInt32"
    assert online.initialize_with == "valueAndStatus"
    assert online.initial_status == "OpcUa_BadWaitingForInitialData"
    assert not online.is_writable

    temperature = sca.cache_variable("temperature")
    assert temperature.is_writable

    channels = sca.cache_variable("channels")
    assert channels.is_array

    chip_rel = sca.has_objects[0]
    assert chip_rel.class_name == "Chip"
    assert chip_rel.instantiate_using == "configuration"

    assert design.root_has_objects[0].class_name == "SCA"


def test_design_instantiation_shape():
    """instantiateUsing="design" carries the instance names declared in the Design."""
    path = QUASAR_ROOT / ".CI/test_cases/test_instantiation_from_design/Design.xml"
    if not path.exists():
        pytest.skip("quasar checkout not found")
    design = Design.from_file(path)
    system = design.classes["System"]
    rectifiers = [rel for rel in system.has_objects if rel.class_name == "Rectifier"][0]
    assert rectifiers.instantiate_using == "design"
    assert rectifiers.design_instance_names == ("rectifier1", "rectifier2", "rectifier3")
    assert design.classes["Controller"].default_instance_name == "controller"


def _all_quasar_ci_designs():
    cases_dir = QUASAR_ROOT / ".CI/test_cases"
    if not cases_dir.exists():
        return []
    return sorted(cases_dir.glob("*/Design.xml"))


@pytest.mark.parametrize(
    "design_path", _all_quasar_ci_designs(), ids=lambda p: p.parent.name
)
def test_parses_every_quasar_ci_design(design_path):
    """The design layer must be total over quasar's own test corpus."""
    design = Design.from_file(design_path)
    assert design.classes or design.root_has_objects is not None

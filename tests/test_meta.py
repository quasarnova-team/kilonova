"""M10 — StandardMetaData is served and functional."""

import logging

import pytest
from asyncua import ua


async def test_log_level_variable_drives_python_logging(sca_client):
    log_level = sca_client.get_node(
        ua.NodeId("StandardMetaData.Log.GeneralLogLevel.logLevel", 2)
    )
    assert await log_level.read_value() in ("TRC", "DBG", "INF", "WRN", "ERR")

    await log_level.write_value(ua.Variant("DBG", ua.VariantType.String))
    assert logging.getLogger("kilonova").getEffectiveLevel() == logging.DEBUG

    await log_level.write_value(ua.Variant("WRN", ua.VariantType.String))
    assert logging.getLogger("kilonova").getEffectiveLevel() == logging.WARNING


async def test_meta_subtree_shape(sca_client):
    for address, expected_type in (
        ("StandardMetaData.Quasar.version", ua.VariantType.String),
        ("StandardMetaData.SourceVariableThreadPool.maxThreads", ua.VariantType.String),
        ("StandardMetaData.BuildInformation.ToolkitLibs", ua.VariantType.String),
    ):
        node = sca_client.get_node(ua.NodeId(address, 2))
        data_value = await node.read_data_value()
        assert data_value.Value.VariantType == expected_type


async def test_component_log_level(sca_client):
    calc_vars = sca_client.get_node(
        ua.NodeId("StandardMetaData.Log.ComponentLogLevels.CalcVars.logLevel", 2)
    )
    await calc_vars.write_value(ua.Variant("TRC", ua.VariantType.String))
    assert logging.getLogger("kilonova.calculated").getEffectiveLevel() == 5


async def test_version_mentions_kilonova(sca_client):
    version = sca_client.get_node(ua.NodeId("StandardMetaData.Quasar.version", 2))
    assert "kilonova" in await version.read_value()


@pytest.fixture(autouse=True)
def _restore_log_levels():
    yield
    for name in ("kilonova", "kilonova.calculated", "kilonova.address_space"):
        logging.getLogger(name).setLevel(logging.NOTSET)

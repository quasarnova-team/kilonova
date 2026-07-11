"""M4 — cache variable semantics, read through a real client."""

import pytest
from asyncua import ua


def node(client, path: str):
    return client.get_node(ua.NodeId(path, 2))


async def test_datatype_follows_null_policy(sca_client):
    """C++ quasar rule: concrete DataType only for nullForbidden variables;
    nullAllowed ones keep BaseDataType so null stays writable."""
    channels = node(sca_client, "sca1.channels")  # nullForbidden -> concrete type
    assert await channels.read_data_type() == ua.NodeId(ua.VariantType.UInt16.value)

    bar = node(sca_client, "sca1.chip0.bar")  # nullForbidden -> concrete type
    assert await bar.read_data_type() == ua.NodeId(ua.VariantType.Double.value)

    for null_allowed in ("sca1.online", "sca1.id", "sca1.temperature"):
        assert await node(sca_client, null_allowed).read_data_type() == ua.NodeId(
            ua.ObjectIds.BaseDataType
        )


async def test_value_rank_scalar_vs_array(sca_client):
    online = node(sca_client, "sca1.online")
    assert (await online.read_attribute(ua.AttributeIds.ValueRank)).Value.Value == -1

    channels = node(sca_client, "sca1.channels")
    assert (await channels.read_attribute(ua.AttributeIds.ValueRank)).Value.Value == 1


async def test_access_level_follows_address_space_write(sca_client):
    read_only = node(sca_client, "sca1.online")
    assert (await read_only.read_attribute(ua.AttributeIds.AccessLevel)).Value.Value == 1

    writable = node(sca_client, "sca1.temperature")
    assert (await writable.read_attribute(ua.AttributeIds.AccessLevel)).Value.Value == 3


async def test_value_and_status_initialization(sca_client):
    """The 2021 prototype never applied initialStatus — regression-guarded here."""
    online = node(sca_client, "sca1.online")
    data_value = await online.read_data_value(raise_on_bad_status=False)
    assert data_value.StatusCode.value == ua.StatusCodes.BadWaitingForInitialData
    assert data_value.Value.Value is None


async def test_numeric_initial_value(sca_client):
    """The 2021 prototype crashed on numeric initialValue — regression-guarded here."""
    bar = node(sca_client, "sca1.chip0.bar")
    data_value = await bar.read_data_value()
    assert data_value.Value.Value == pytest.approx(3.14)
    assert data_value.StatusCode.value == ua.StatusCodes.Good


async def test_configuration_initialization(sca_client):
    assert await node(sca_client, "sca1.id").read_value() == "theSCA"
    assert await node(sca_client, "sca1.temperature").read_value() == pytest.approx(25.5)
    assert await node(sca_client, "sca1.channels").read_value() == [1, 2, 3]


async def test_client_write_respects_access_level(sca_client):
    temperature = node(sca_client, "sca1.temperature")
    await temperature.write_value(ua.Variant(30.0, ua.VariantType.Double))
    assert await temperature.read_value() == pytest.approx(30.0)

    online = node(sca_client, "sca1.online")
    with pytest.raises(ua.UaStatusCodeError):
        await online.write_value(ua.Variant(1, ua.VariantType.UInt32))

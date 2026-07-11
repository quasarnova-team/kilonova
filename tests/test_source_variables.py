"""M8 — source variables and delegated writes, exercised by a real client."""

import pytest
from asyncua import ua


def node(client, path: str):
    return client.get_node(ua.NodeId(path, 2))


async def test_unhandled_source_read_stays_waiting(sca_client):
    data_value = await node(sca_client, "sca1.adc").read_data_value(raise_on_bad_status=False)
    assert data_value.StatusCode.value == ua.StatusCodes.BadWaitingForInitialData


async def test_access_level_follows_read_write_modes(sca_client):
    adc = node(sca_client, "sca1.adc")  # read-only source variable
    assert (await adc.read_attribute(ua.AttributeIds.AccessLevel)).Value.Value == 1

    dac = node(sca_client, "sca1.dac")  # read-write source variable
    assert (await dac.read_attribute(ua.AttributeIds.AccessLevel)).Value.Value == 3

    assert await adc.read_data_type() == ua.NodeId(ua.VariantType.Double.value)


async def test_read_handler_runs_inside_the_read(sca_server, sca_client):
    """Each client read triggers the device coroutine and gets the fresh value."""
    server, _ = sca_server
    calls = {"n": 0}

    @server.read("sca1.adc")
    async def read_adc(obj):
        assert obj is server.objects["sca1"]
        calls["n"] += 1
        return 20.0 + calls["n"]

    adc = node(sca_client, "sca1.adc")
    assert await adc.read_value() == pytest.approx(21.0)
    assert await adc.read_value() == pytest.approx(22.0)
    assert calls["n"] == 2


async def test_read_handler_can_report_status(sca_server, sca_client):
    server, _ = sca_server

    @server.read("sca1.adc")
    async def read_adc(obj):
        return None, ua.StatusCodes.BadNoCommunication

    data_value = await node(sca_client, "sca1.adc").read_data_value(raise_on_bad_status=False)
    assert data_value.StatusCode.value == ua.StatusCodes.BadNoCommunication


async def test_source_write_handler_round_trip(sca_server, sca_client):
    server, _ = sca_server
    device = {}

    @server.write("sca1.dac")
    async def write_dac(obj, value):
        device["dac"] = value

    dac = node(sca_client, "sca1.dac")
    await dac.write_value(ua.Variant(5.5, ua.VariantType.Double))
    assert device["dac"] == pytest.approx(5.5)
    # accepted writes are stored, so a plain read (no read handler) sees them
    assert await dac.read_value() == pytest.approx(5.5)


async def test_source_write_handler_can_refuse(sca_server, sca_client):
    server, _ = sca_server

    @server.write("sca1.dac")
    async def write_dac(obj, value):
        raise ua.UaStatusCodeError(ua.StatusCodes.BadOutOfRange)

    dac = node(sca_client, "sca1.dac")
    with pytest.raises(ua.UaStatusCodeError) as refused:
        await dac.write_value(ua.Variant(999.0, ua.VariantType.Double))
    assert refused.value.code == ua.StatusCodes.BadOutOfRange

    # nothing was stored: still waiting for initial data
    data_value = await dac.read_data_value(raise_on_bad_status=False)
    assert data_value.StatusCode.value == ua.StatusCodes.BadWaitingForInitialData


async def test_source_write_forbidden_is_refused_by_access_level(sca_client):
    adc = node(sca_client, "sca1.adc")
    with pytest.raises(ua.UaStatusCodeError):
        await adc.write_value(ua.Variant(1.0, ua.VariantType.Double))


async def test_delegated_write_without_handler(sca_client):
    target = node(sca_client, "sca1.target")
    with pytest.raises(ua.UaStatusCodeError) as refused:
        await target.write_value(ua.Variant(7.7, ua.VariantType.Double))
    assert refused.value.code == ua.StatusCodes.BadNotImplemented


async def test_delegated_write_reaches_device_logic(sca_server, sca_client):
    server, _ = sca_server
    seen = {}

    @server.write("sca1.target")
    async def write_target(obj, value):
        seen["value"] = value

    target = node(sca_client, "sca1.target")
    await target.write_value(ua.Variant(7.7, ua.VariantType.Double))
    assert seen["value"] == pytest.approx(7.7)
    assert await target.read_value() == pytest.approx(7.7)


async def test_server_side_setters_bypass_delegation(sca_server):
    """set_cv is device logic itself — it must not trigger the write handler."""
    server, _ = sca_server
    calls = {"n": 0}

    @server.write("sca1.target")
    async def write_target(obj, value):
        calls["n"] += 1

    await server.objects["sca1"].setTarget(1.0)
    assert calls["n"] == 0
    assert await server.objects["sca1"].get_cv("target") == pytest.approx(1.0)

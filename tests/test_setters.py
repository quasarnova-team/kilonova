"""M5 — MilkyWay feature parity: set_cv, generated setters, live updates."""

import asyncio

import pytest
from asyncua import ua


def node(client, path: str):
    return client.get_node(ua.NodeId(path, 2))


async def test_generated_setter(sca_server, sca_client):
    server, _ = sca_server
    await server.objects["sca1"].setOnline(5)

    data_value = await node(sca_client, "sca1.online").read_data_value()
    assert data_value.Value.Value == 5
    assert data_value.Value.VariantType == ua.VariantType.UInt32
    assert data_value.StatusCode.value == ua.StatusCodes.Good


async def test_set_cv_with_explicit_status(sca_server, sca_client):
    server, _ = sca_server
    await server.objects["sca1"].set_cv("online", 9, status=ua.StatusCodes.Bad)

    data_value = await node(sca_client, "sca1.online").read_data_value(
        raise_on_bad_status=False
    )
    # per OPC UA semantics a Bad-status read carries no value on the wire
    assert data_value.StatusCode.value == ua.StatusCodes.Bad
    assert data_value.Value.Value is None

    # recovering to Good makes the value visible again
    await server.objects["sca1"].set_cv("online", 9)
    data_value = await node(sca_client, "sca1.online").read_data_value()
    assert data_value.Value.Value == 9


async def test_get_cv_round_trip(sca_server):
    server, _ = sca_server
    sca1 = server.objects["sca1"]
    await sca1.setTemperature(42.5)
    assert await sca1.get_cv("temperature") == pytest.approx(42.5)


async def test_unknown_setter_raises(sca_server):
    server, _ = sca_server
    with pytest.raises(AttributeError):
        _ = server.objects["sca1"].setNoSuchVariable


class _Recorder:
    def __init__(self):
        self.values = asyncio.Queue()

    def datachange_notification(self, node, value, data):
        self.values.put_nowait(value)


async def test_client_subscription_sees_setter_updates(sca_server, sca_client):
    """The full UX loop: device logic sets, a subscribed client is notified."""
    server, _ = sca_server
    recorder = _Recorder()
    subscription = await sca_client.create_subscription(50, recorder)
    await subscription.subscribe_data_change(node(sca_client, "sca1.online"))

    await server.objects["sca1"].setOnline(1234)

    async def next_matching(expected):
        while True:
            if await recorder.values.get() == expected:
                return True

    assert await asyncio.wait_for(next_matching(1234), timeout=5.0)
    await subscription.delete()

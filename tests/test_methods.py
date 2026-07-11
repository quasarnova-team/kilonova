"""M7 — callable method handlers, exercised by a real client."""

import pytest
from asyncua import ua


async def test_unhandled_method_answers_bad_not_implemented(sca_client):
    sca1 = sca_client.get_node(ua.NodeId("sca1", 2))
    with pytest.raises(ua.UaStatusCodeError) as excinfo:
        await sca1.call_method(ua.NodeId("sca1.reset", 2))
    assert excinfo.value.code == ua.StatusCodes.BadNotImplemented


async def test_handler_receives_object_and_arguments(sca_server, sca_client):
    server, _ = sca_server
    seen = {}

    @server.method("sca1.scale")
    async def scale(obj, factor):
        seen["object"] = obj
        seen["factor"] = factor
        return factor * 2.0

    sca1 = sca_client.get_node(ua.NodeId("sca1", 2))
    result = await sca1.call_method(
        ua.NodeId("sca1.scale", 2), ua.Variant(21.0, ua.VariantType.Double)
    )

    assert result == pytest.approx(42.0)
    assert seen["factor"] == pytest.approx(21.0)
    assert seen["object"] is server.objects["sca1"]


async def test_handler_can_drive_cache_variables(sca_server, sca_client):
    server, _ = sca_server

    @server.method("sca1.reset")
    async def reset(obj):
        await obj.setOnline(0)

    sca1 = sca_client.get_node(ua.NodeId("sca1", 2))
    result = await sca1.call_method(ua.NodeId("sca1.reset", 2))
    assert result is None

    online = sca_client.get_node(ua.NodeId("sca1.online", 2))
    assert await online.read_value() == 0

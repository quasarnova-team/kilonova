"""M2 — server boots from a Design; a real client connects and browses."""

from asyncua import Client, ua

from tests.conftest import make_server


async def test_client_connects_and_finds_object_types():
    server, url = make_server(config=None)
    async with server, Client(url=url) as client:
        # quasar namespace must be at index 2
        ns_array = await client.get_namespace_array()
        assert len(ns_array) >= 3

        # first design class becomes ObjectType ns=2;i=1000
        sca_type = client.get_node(ua.NodeId(1000, 2))
        browse_name = await sca_type.read_browse_name()
        assert browse_name.Name == "SCA"
        assert browse_name.NamespaceIndex == 2

        chip_type = client.get_node(ua.NodeId(1001, 2))
        assert (await chip_type.read_browse_name()).Name == "Chip"

        node_class = await sca_type.read_node_class()
        assert node_class == ua.NodeClass.ObjectType


async def test_no_config_means_no_instances():
    server, url = make_server(config=None)
    async with server, Client(url=url) as client:
        children = await client.nodes.objects.get_children()
        ns2 = [n.nodeid.Identifier for n in children if n.nodeid.NamespaceIndex == 2]
        assert ns2 == ["StandardMetaData"]  # meta only, no design instances

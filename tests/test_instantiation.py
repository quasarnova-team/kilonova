"""M3 — config.xml instantiation with quasar's dotted string NodeIds."""

from asyncua import ua


async def test_objects_resolve_by_quasar_nodeid(sca_client):
    """A client that knows quasar addressing resolves nodes directly by NodeId."""
    sca1 = sca_client.get_node(ua.NodeId("sca1", 2))
    assert (await sca1.read_browse_name()).Name == "sca1"
    assert await sca1.read_node_class() == ua.NodeClass.Object

    chip0 = sca_client.get_node(ua.NodeId("sca1.chip0", 2))
    assert (await chip0.read_browse_name()).Name == "chip0"


async def test_hierarchy_matches_config(sca_client):
    objects = sca_client.nodes.objects
    top = [
        n for n in await objects.get_children()
        if n.nodeid.NamespaceIndex == 2 and n.nodeid.Identifier != "StandardMetaData"
    ]
    assert [n.nodeid.Identifier for n in top] == ["sca1"]

    sca1 = top[0]
    child_names = {
        (await child.read_browse_name()).Name for child in await sca1.get_children()
    }
    assert {"online", "id", "temperature", "channels", "chip0", "reset"} <= child_names


async def test_type_definition_points_to_design_type(sca_client):
    sca1 = sca_client.get_node(ua.NodeId("sca1", 2))
    type_definition = await sca1.read_type_definition()
    assert type_definition == ua.NodeId(1000, 2)


async def test_registry_uses_dotted_addresses(sca_server):
    server, _ = sca_server
    assert set(server.objects) == {"sca1", "sca1.chip0"}
    assert server.objects["sca1"].quasar_class.name == "SCA"

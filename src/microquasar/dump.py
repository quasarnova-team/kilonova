"""Client-side address-space dump and NodeSet2 comparison.

This is microquasar's equivalent of UaSwissArmyKnife's ``uasak_dump``: it
connects to a *running* server as an ordinary OPC UA client, walks the
hierarchy, and emits a NodeSet2-style XML document. Testing through a real
client connection is the point — the dump sees exactly what WinCC OA or any
other client would.

Format contract (learned from uasak_dump + quasar's reference_ns2.xml files):

- entities: ``UAObject`` / ``UAVariable`` / ``UAMethod``, each with
  ``BrowseName`` (name part only) and ``NodeId``;
- variables also carry ``DataType`` / ``ValueRank`` / ``AccessLevel``,
  suppressed when equal to the NodeSet2 XSD defaults (``i=24`` / ``-1`` / ``1``);
- ``DataType`` uses UaNodeId::toString style (``i=12``, no ``ns=0;`` prefix),
  reference targets always carry the explicit namespace (``ns=0;i=47``).

The comparison implements the same semantics as NodeSetTools/nodeset_compare.py:
one-directional, NodeId-keyed, attribute-exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from asyncua import Client, ua
from lxml import etree

NODESET_NS = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"
_X = f"{{{NODESET_NS}}}"

_XSD_DEFAULTS = {"DataType": "i=24", "ValueRank": "-1", "AccessLevel": "1"}


def _nodeid_str(node_id: ua.NodeId, explicit_ns0: bool = False) -> str:
    kind = {
        ua.NodeIdType.Numeric: "i",
        ua.NodeIdType.TwoByte: "i",
        ua.NodeIdType.FourByte: "i",
        ua.NodeIdType.String: "s",
        ua.NodeIdType.Guid: "g",
        ua.NodeIdType.ByteString: "b",
    }[node_id.NodeIdType]
    body = f"{kind}={node_id.Identifier}"
    if node_id.NamespaceIndex == 0 and not explicit_ns0:
        return body
    return f"ns={node_id.NamespaceIndex};{body}"


@dataclass
class _DumpedNode:
    node_class: ua.NodeClass
    node_id: str
    browse_name: str
    references: list[tuple[str, str]] = field(default_factory=list)  # (reftype, target)
    attributes: dict[str, str] = field(default_factory=dict)


async def dump_address_space(
    endpoint: str, namespace_index: int = 2
) -> etree._ElementTree:
    """Connect as a client and dump all namespace-`namespace_index` nodes."""
    dumped: dict[str, _DumpedNode] = {}
    async with Client(url=endpoint) as client:
        objects = client.get_node(ua.NodeId(ua.ObjectIds.ObjectsFolder))
        await _walk(client, objects, namespace_index, dumped)
    return _to_nodeset_xml(dumped.values())


async def _walk(client: Client, node, namespace_index: int, dumped: dict) -> None:
    children = await node.get_references(
        refs=ua.ObjectIds.HierarchicalReferences,
        direction=ua.BrowseDirection.Forward,
        includesubtypes=True,
    )
    for child_ref in children:
        child_id = child_ref.NodeId.to_nodeid()
        child_key = _nodeid_str(child_id, explicit_ns0=True)
        if child_key in dumped:
            continue
        child = client.get_node(child_id)
        if child_id.NamespaceIndex == namespace_index:
            dumped[child_key] = await _dump_node(client, child, child_ref)
        # descend regardless: ns-2 nodes may hang below ns-0 folders
        if child_ref.NodeClass in (ua.NodeClass.Object, ua.NodeClass.Variable):
            if child_id.NamespaceIndex == namespace_index or _is_folderish(child_id):
                await _walk(client, child, namespace_index, dumped)


def _is_folderish(node_id: ua.NodeId) -> bool:
    """ns-0 containers worth descending into (avoid the whole Server object)."""
    return node_id.NamespaceIndex == 0 and node_id.Identifier in (
        ua.ObjectIds.ObjectsFolder,
    )


async def _dump_node(client: Client, node, ref_description) -> _DumpedNode:
    entry = _DumpedNode(
        node_class=ref_description.NodeClass,
        node_id=_nodeid_str(node.nodeid),
        browse_name=ref_description.BrowseName.Name,
    )
    for ref in await node.get_references(direction=ua.BrowseDirection.Forward):
        entry.references.append(
            (
                _nodeid_str(ua.NodeId(ref.ReferenceTypeId.Identifier,
                                      ref.ReferenceTypeId.NamespaceIndex), explicit_ns0=True),
                _nodeid_str(ref.NodeId.to_nodeid(), explicit_ns0=True),
            )
        )
    if ref_description.NodeClass == ua.NodeClass.Variable:
        attrs = await node.read_attributes(
            [ua.AttributeIds.DataType, ua.AttributeIds.ValueRank, ua.AttributeIds.AccessLevel]
        )
        data_type, value_rank, access_level = (dv.Value.Value for dv in attrs)
        entry.attributes["DataType"] = _nodeid_str(data_type)
        entry.attributes["ValueRank"] = str(value_rank)
        entry.attributes["AccessLevel"] = str(access_level)
    return entry


def _to_nodeset_xml(nodes) -> etree._ElementTree:
    root = etree.Element(f"{_X}UANodeSet", nsmap={None: NODESET_NS})
    tag_by_class = {
        ua.NodeClass.Object: "UAObject",
        ua.NodeClass.Variable: "UAVariable",
        ua.NodeClass.Method: "UAMethod",
    }
    for node in nodes:
        tag = tag_by_class.get(node.node_class)
        if tag is None:
            continue
        element = etree.SubElement(root, f"{_X}{tag}")
        element.set("BrowseName", node.browse_name)
        element.set("NodeId", node.node_id)
        for attr, value in node.attributes.items():
            if _XSD_DEFAULTS.get(attr) != value:
                element.set(attr, value)
        if node.references:
            refs_el = etree.SubElement(element, f"{_X}References")
            for ref_type, target in node.references:
                ref_el = etree.SubElement(refs_el, f"{_X}Reference")
                ref_el.set("ReferenceType", ref_type)
                ref_el.text = target
    return etree.ElementTree(root)


# -- comparison (NodeSetTools/nodeset_compare.py semantics) --------------------


def compare_nodesets(
    reference: etree._ElementTree,
    test: etree._ElementTree,
    ignore_nodeid_substrings: tuple[str, ...] = (),
) -> list[str]:
    """Return a list of human-readable failures; empty means parity."""
    failures: list[str] = []
    ns = {"x": NODESET_NS}
    for entity_type in ("UAObject", "UAVariable", "UAMethod"):
        for ref_entity in reference.getroot().xpath(f"x:{entity_type}", namespaces=ns):
            ref_nodeid = ref_entity.attrib["NodeId"]
            if any(sub in ref_nodeid for sub in ignore_nodeid_substrings):
                continue
            matches = test.getroot().xpath(
                f"x:{entity_type}[@NodeId='{ref_nodeid}']", namespaces=ns
            )
            if len(matches) != 1:
                verdict = "missing" if not matches else "duplicated"
                failures.append(f"{entity_type} {ref_nodeid}: {verdict} in dump")
                continue
            test_entity = matches[0]
            for attr, ref_value in ref_entity.attrib.items():
                test_value = test_entity.attrib.get(attr)
                if test_value is None:
                    failures.append(f"{entity_type} {ref_nodeid}: attribute {attr} missing")
                elif test_value != ref_value:
                    failures.append(
                        f"{entity_type} {ref_nodeid}: {attr} is {test_value!r},"
                        f" reference says {ref_value!r}"
                    )
    return failures


def load_nodeset(path: str) -> etree._ElementTree:
    return etree.parse(path)

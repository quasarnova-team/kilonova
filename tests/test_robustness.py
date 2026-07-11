"""Regression tests for the adversarial-review findings (2026-07-11 panel)."""

import pytest
from asyncua import Client, ua

from kilonova import Design, Server
from kilonova.errors import ConfigurationError, DesignError
from tests.conftest import free_port

DESIGN_HEADER = (
    '<d:design xmlns:d="http://cern.ch/quasar/Design" projectShortName="T">'
)
CONFIG_HEADER = '<configuration xmlns="http://cern.ch/quasar/Configuration">'


def write_pair(tmp_path, design_body: str, config_body: str):
    design = tmp_path / "Design.xml"
    design.write_text(f"{DESIGN_HEADER}{design_body}</d:design>")
    config = tmp_path / "config.xml"
    config.write_text(f"{CONFIG_HEADER}{config_body}</configuration>")
    return design, config


async def boot(tmp_path, design_body, config_body):
    design, config = write_pair(tmp_path, design_body, config_body)
    url = f"opc.tcp://127.0.0.1:{free_port()}/"
    server = Server(design, config_path=config, endpoint=url)
    return server, url


SIMPLE_CLASS = (
    '<d:class name="A"><d:devicelogic/>'
    '<d:cachevariable name="x" dataType="OpcUa_UInt16" addressSpaceWrite="forbidden"'
    ' initializeWith="configuration" nullPolicy="nullAllowed"'
    ' defaultConfigInitializerValue="42"/></d:class>'
    '<d:root><d:hasobjects instantiateUsing="configuration" class="A"/></d:root>'
)


async def test_default_config_initializer_value(tmp_path):
    """Omitted config values fall back to the Design's defaultConfigInitializerValue."""
    server, url = await boot(tmp_path, SIMPLE_CLASS, '<A name="a1"/>')
    async with server, Client(url=url) as client:
        assert await client.get_node(ua.NodeId("a1.x", 2)).read_value() == 42


async def test_unknown_config_attribute_rejected(tmp_path):
    server, _ = await boot(tmp_path, SIMPLE_CLASS, '<A name="a1" X="1"/>')
    with pytest.raises(ConfigurationError, match="unknown attribute 'X'"):
        await server.init()


async def test_out_of_range_config_value_rejected(tmp_path):
    server, _ = await boot(tmp_path, SIMPLE_CLASS, '<A name="a1" x="70000"/>')
    with pytest.raises(ConfigurationError, match="out of range for UInt16"):
        await server.init()


async def test_child_not_in_hasobjects_rejected(tmp_path):
    design_body = SIMPLE_CLASS.replace(
        "</d:class>",
        "</d:class>"
        '<d:class name="B"><d:cachevariable name="y" dataType="OpcUa_Double"'
        ' addressSpaceWrite="forbidden" initializeWith="configuration"'
        ' nullPolicy="nullAllowed" defaultConfigInitializerValue="0"/></d:class>',
        1,
    )
    server, _ = await boot(tmp_path, design_body, '<A name="a1"><B name="b1"/></A>')
    with pytest.raises(ConfigurationError, match="not declared in this class's hasobjects"):
        await server.init()


async def test_text_style_arrays_rejected(tmp_path):
    """quasar arrays are <value> elements; the 2021-style text form must not silently
    load as an empty array."""
    design_body = SIMPLE_CLASS.replace(
        'defaultConfigInitializerValue="42"/>',
        'defaultConfigInitializerValue="42"/>'
        '<d:cachevariable name="arr" dataType="OpcUa_UInt16" addressSpaceWrite="forbidden"'
        ' initializeWith="configuration" nullPolicy="nullAllowed"><d:array/></d:cachevariable>',
    ).replace("/></d:class>", "/></d:class>", 1)
    server, _ = await boot(tmp_path, design_body, '<A name="a1"><arr>1 2 3</arr></A>')
    with pytest.raises(ConfigurationError, match="<value>"):
        await server.init()


def test_duplicate_class_names_rejected(tmp_path):
    design = tmp_path / "Design.xml"
    design.write_text(
        f"{DESIGN_HEADER}"
        '<d:class name="A"/><d:class name="A"/><d:root/></d:design>'
    )
    with pytest.raises(DesignError, match="duplicate class 'A'"):
        Design.from_file(design)


def test_missing_name_rejected_at_parse_time(tmp_path):
    design = tmp_path / "Design.xml"
    design.write_text(
        f"{DESIGN_HEADER}"
        '<d:class name="A"><d:cachevariable dataType="OpcUa_Double"'
        ' addressSpaceWrite="forbidden" initializeWith="configuration"'
        ' nullPolicy="nullAllowed"/></d:class><d:root/></d:design>'
    )
    with pytest.raises(DesignError, match="missing required attribute 'name'"):
        Design.from_file(design)


async def test_single_variable_node_takes_config_value(tmp_path):
    """SVN instances must honour configuration-initialized values (2026 panel find)."""
    design_body = (
        '<d:class name="Prop" singleVariableNode="true"><d:devicelogic/>'
        '<d:cachevariable name="value" dataType="UaString" addressSpaceWrite="forbidden"'
        ' initializeWith="configuration" nullPolicy="nullAllowed"'
        ' defaultConfigInitializerValue=""/></d:class>'
        '<d:root><d:hasobjects instantiateUsing="configuration" class="Prop"/></d:root>'
    )
    server, url = await boot(tmp_path, design_body, '<Prop name="p1" value="hello"/>')
    async with server, Client(url=url) as client:
        assert await client.get_node(ua.NodeId("p1", 2)).read_value() == "hello"


async def test_set_cv_null_respects_null_policy(sca_server):
    server, _ = sca_server
    sca1 = server.objects["sca1"]

    await sca1.setId(None)  # nullAllowed: fine
    assert await sca1.get_cv("id") is None

    with pytest.raises(ua.UaStatusCodeError):  # nullForbidden: refused loudly
        await sca1.set_cv("channels", None)
    assert await sca1.get_cv("channels") == [1, 2, 3]


async def test_set_cv_out_of_range_raises(sca_server):
    server, _ = sca_server
    with pytest.raises(ValueError, match="out of range"):
        await server.objects["sca1"].setOnline(-1)
    with pytest.raises(ValueError, match="out of range"):
        await server.objects["sca1"].set_cv("channels", [1, 70000])


async def test_method_argument_count_status_codes(sca_server, sca_client):
    server, _ = sca_server

    @server.method("sca1.scale")
    async def scale(obj, factor):
        return factor

    sca1 = sca_client.get_node(ua.NodeId("sca1", 2))
    with pytest.raises(ua.UaStatusCodeError) as too_few:
        await sca1.call_method(ua.NodeId("sca1.scale", 2))
    assert too_few.value.code == ua.StatusCodes.BadArgumentsMissing

    with pytest.raises(ua.UaStatusCodeError) as too_many:
        await sca1.call_method(
            ua.NodeId("sca1.scale", 2),
            ua.Variant(1.0, ua.VariantType.Double),
            ua.Variant(2.0, ua.VariantType.Double),
        )
    assert too_many.value.code == ua.StatusCodes.BadTooManyArguments


RESTRICTED_CLASS = (
    '<d:class name="R"><d:devicelogic/>'
    '<d:cachevariable name="mode" dataType="UaString" addressSpaceWrite="forbidden"'
    ' initializeWith="configuration" nullPolicy="nullAllowed"'
    ' defaultConfigInitializerValue="auto">'
    "<d:configRestriction><d:restrictionByEnumeration>"
    '<d:enumerationValue value="auto"/><d:enumerationValue value="manual"/>'
    "</d:restrictionByEnumeration></d:configRestriction></d:cachevariable>"
    '<d:cachevariable name="gain" dataType="OpcUa_Double" addressSpaceWrite="forbidden"'
    ' initializeWith="configuration" nullPolicy="nullAllowed"'
    ' defaultConfigInitializerValue="1">'
    '<d:configRestriction><d:restrictionByBounds minInclusive="0" maxExclusive="10"/>'
    "</d:configRestriction></d:cachevariable>"
    '<d:configentry name="tag" dataType="UaString">'
    '<d:configRestriction><d:restrictionByPattern pattern="[A-Z]{3}[0-9]+"/>'
    "</d:configRestriction></d:configentry></d:class>"
    '<d:root><d:hasobjects instantiateUsing="configuration" class="R" maxOccurs="1"/></d:root>'
)


async def test_restrictions_accept_valid_config(tmp_path):
    server, url = await boot(
        tmp_path, RESTRICTED_CLASS, '<R name="r1" mode="auto" gain="9.5" tag="ABC42"/>'
    )
    async with server, Client(url=url) as client:
        assert await client.get_node(ua.NodeId("r1.mode", 2)).read_value() == "auto"


@pytest.mark.parametrize(
    "bad_config, complaint",
    [
        ('<R name="r1" mode="turbo"/>', "not one of the enumerated values"),
        ('<R name="r1" gain="10"/>', "violates bound"),
        ('<R name="r1" tag="abc"/>', "does not match pattern"),
    ],
)
async def test_restrictions_reject_invalid_config(tmp_path, bad_config, complaint):
    server, _ = await boot(tmp_path, RESTRICTED_CLASS, bad_config)
    with pytest.raises(ConfigurationError, match=complaint):
        await server.init()


async def test_max_occurs_enforced(tmp_path):
    server, _ = await boot(tmp_path, RESTRICTED_CLASS, '<R name="r1"/><R name="r2"/>')
    with pytest.raises(ConfigurationError, match="at most 1"):
        await server.init()


async def test_server_config_endpoint_and_policy(tmp_path):
    """quasar ServerConfig.xml: endpoint URL and security settings are honoured."""
    from kilonova import Server as KServer

    port = free_port()
    (tmp_path / "ServerConfig.xml").write_text(f"""<OpcServerConfig>
      <UaServerConfig>
        <UaEndpoint>
          <Url>opc.tcp://[NodeName]:{port}</Url>
          <SecuritySetting>
            <SecurityPolicy>http://opcfoundation.org/UA/SecurityPolicy#None</SecurityPolicy>
            <MessageSecurityMode>None</MessageSecurityMode>
          </SecuritySetting>
        </UaEndpoint>
        <UserIdentityTokens><EnableAnonymous>true</EnableAnonymous></UserIdentityTokens>
        <MaxSessionCount>100</MaxSessionCount>
      </UaServerConfig>
    </OpcServerConfig>""")
    design, config = write_pair(tmp_path, SIMPLE_CLASS, '<A name="a1" x="5"/>')
    server = KServer(design, config_path=config,
                     server_config_path=tmp_path / "ServerConfig.xml")
    async with server, Client(url=f"opc.tcp://127.0.0.1:{port}/") as client:
        assert await client.get_node(ua.NodeId("a1.x", 2)).read_value() == 5

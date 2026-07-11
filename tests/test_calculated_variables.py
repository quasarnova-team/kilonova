"""M9 — calculated variables and free variables, exercised by a real client."""

import pytest
from asyncua import Client, ua

from tests.test_robustness import boot

DESIGN = (
    '<d:class name="A"><d:devicelogic/>'
    '<d:cachevariable name="x" dataType="OpcUa_Double" addressSpaceWrite="regular"'
    ' initializeWith="configuration" nullPolicy="nullAllowed"/></d:class>'
    '<d:root><d:hasobjects instantiateUsing="configuration" class="A"/></d:root>'
)

# x starts BadWaitingForInitialData and is client-writable: the C++-legal way to
# exercise not-yet-good calculated inputs
VS_DESIGN = (
    '<d:class name="A"><d:devicelogic/>'
    '<d:cachevariable name="x" dataType="OpcUa_Double" addressSpaceWrite="regular"'
    ' initializeWith="valueAndStatus" nullPolicy="nullAllowed"'
    ' initialStatus="OpcUa_BadWaitingForInitialData"/></d:class>'
    '<d:root><d:hasobjects instantiateUsing="configuration" class="A"/></d:root>'
)

CONFIG = (
    '<CalculatedVariableGenericFormula name="Doubled" formula="$thisObjectAddress.fv * 2"/>'
    '<A name="a1" x="3">'
    '<FreeVariable name="fv" type="Double" initialValue="5"/>'
    '<CalculatedVariable name="const7" value="7"/>'
    '<CalculatedVariable name="sum" value="$thisObjectAddress.fv + $thisObjectAddress.const7"/>'
    '<CalculatedVariable name="fv2" value="$applyGenericFormula(Doubled)"/>'
    "</A>"
    '<CalculatedVariable name="grand" value="a1.sum * a1.x"/>'
)


async def test_calculated_variables_evaluate_and_propagate(tmp_path):
    server, url = await boot(tmp_path, DESIGN, CONFIG)
    async with server, Client(url=url) as client:
        def node(path):
            return client.get_node(ua.NodeId(path, 2))

        # initial evaluation, including generic formula and root-level formula
        assert await node("a1.const7").read_value() == pytest.approx(7.0)
        assert await node("a1.sum").read_value() == pytest.approx(12.0)
        assert await node("a1.fv2").read_value() == pytest.approx(10.0)
        assert await node("grand").read_value() == pytest.approx(36.0)

        # free variables are writable; dependents recompute synchronously
        await node("a1.fv").write_value(ua.Variant(10.0, ua.VariantType.Double))
        assert await node("a1.sum").read_value() == pytest.approx(17.0)
        assert await node("a1.fv2").read_value() == pytest.approx(20.0)
        assert await node("grand").read_value() == pytest.approx(51.0)

        # cache variable inputs propagate too
        await node("a1.x").write_value(ua.Variant(4.0, ua.VariantType.Double))
        assert await node("grand").read_value() == pytest.approx(68.0)

        # calculated variables are read-only
        with pytest.raises(ua.UaStatusCodeError):
            await node("a1.sum").write_value(ua.Variant(1.0, ua.VariantType.Double))


async def test_waiting_input_propagates_waiting_status(tmp_path):
    """C++ parity: waiting inputs propagate BadWaitingForInitialData; other bad
    inputs propagate Bad (CalculatedVariablesChangeListener semantics)."""
    config = '<A name="a1"><CalculatedVariable name="calc" value="a1.x + 1"/></A>'
    server, url = await boot(tmp_path, VS_DESIGN, config)
    async with server, Client(url=url) as client:
        calc = client.get_node(ua.NodeId("a1.calc", 2))
        data_value = await calc.read_data_value(raise_on_bad_status=False)
        assert data_value.StatusCode.value == ua.StatusCodes.BadWaitingForInitialData

        # once the input becomes non-null, the value appears
        x = client.get_node(ua.NodeId("a1.x", 2))
        await x.write_value(ua.Variant(41.0, ua.VariantType.Double))
        assert await calc.read_value() == pytest.approx(42.0)


async def test_malformed_formula_rejected(tmp_path):
    config = '<A name="a1" x="1"><CalculatedVariable name="bad" value="__import__(1)"/></A>'
    server, _ = await boot(tmp_path, DESIGN, config)
    from kilonova.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="unsupported construct"):
        await server.init()


async def test_muparser_formula_language(tmp_path):
    """Functions, comparisons, logical ops, ternary, constants (muParser dialect)."""
    config = (
        '<A name="a1" x="4">'
        '<CalculatedVariable name="hyp" value="sqrt(a1.x^2 + 3^2)"/>'
        '<CalculatedVariable name="gate" value="a1.x &gt; 3 &amp;&amp; a1.x &lt; 10"/>'
        '<CalculatedVariable name="pick" value="a1.x &gt; 100 ? 1 : avg(2, 4, 6)"/>'
        '<CalculatedVariable name="tau" value="2 * _pi"/>'
        "</A>"
    )
    server, url = await boot(tmp_path, DESIGN, config)
    async with server, Client(url=url) as client:
        async def value(path):
            return await client.get_node(ua.NodeId(path, 2)).read_value()
        assert await value("a1.hyp") == pytest.approx(5.0)
        assert await value("a1.gate") == pytest.approx(1.0)
        assert await value("a1.pick") == pytest.approx(4.0)
        assert await value("a1.tau") == pytest.approx(6.283185307)


async def test_formula_meta_functions(tmp_path):
    """$_ alias, $parentObjectAddress(numLevelsUp=N)."""
    design_body = (
        '<d:class name="Sub"><d:devicelogic/>'
        '<d:cachevariable name="y" dataType="OpcUa_Double" addressSpaceWrite="regular"'
        ' initializeWith="configuration" nullPolicy="nullAllowed"/></d:class>'
        '<d:class name="A"><d:devicelogic/>'
        '<d:cachevariable name="x" dataType="OpcUa_Double" addressSpaceWrite="regular"'
        ' initializeWith="configuration" nullPolicy="nullAllowed"/>'
        '<d:hasobjects instantiateUsing="configuration" class="Sub"/></d:class>'
        '<d:root><d:hasobjects instantiateUsing="configuration" class="A"/></d:root>'
    )
    config = (
        '<A name="a1" x="10"><Sub name="s1" y="5">'
        '<CalculatedVariable name="c" value="$_.y + $parentObjectAddress(numLevelsUp=1).x"/>'
        "</Sub></A>"
    )
    server, url = await boot(tmp_path, design_body, config)
    async with server, Client(url=url) as client:
        assert await client.get_node(ua.NodeId("a1.s1.c", 2)).read_value() == pytest.approx(15.0)


async def test_cv_initial_value_is_boolean_and_status(tmp_path):
    """C++ parity: initialValue published Good pre-evaluation; status formula
    decides Good/Bad; isBoolean publishes a Bool."""
    config = (
        '<A name="a1">'
        '<CalculatedVariable name="pre" value="a1.x * 2" initialValue="7"/>'
        '<CalculatedVariable name="flag" value="1" isBoolean="true"/>'
        '<CalculatedVariable name="gated" value="42" status="a1.x &gt; 0"/>'
        "</A>"
    )
    server, url = await boot(tmp_path, VS_DESIGN, config)
    async with server, Client(url=url) as client:
        def node(path):
            return client.get_node(ua.NodeId(path, 2))
        # x is still waiting -> value formula cannot evaluate; initialValue holds, Good
        dv = await node("a1.pre").read_data_value(raise_on_bad_status=False)
        assert dv.Value.Value == pytest.approx(7.0)
        assert dv.StatusCode.is_good()

        flag = await node("a1.flag").read_data_value()
        assert flag.Value.Value is True
        assert flag.Value.VariantType == ua.VariantType.Boolean

        gated = await node("a1.gated").read_data_value(raise_on_bad_status=False)
        assert not gated.StatusCode.is_good()  # status formula input not good -> Bad

        await node("a1.x").write_value(ua.Variant(3.0, ua.VariantType.Double))
        assert await node("a1.pre").read_value() == pytest.approx(6.0)
        gated = await node("a1.gated").read_data_value()
        assert gated.Value.Value == pytest.approx(42.0)
        assert gated.StatusCode.is_good()

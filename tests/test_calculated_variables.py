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


async def test_null_input_gives_bad_status(tmp_path):
    """C++ parity: null input -> Bad; only waiting inputs propagate
    BadWaitingForInitialData (CalculatedVariablesChangeListener semantics)."""
    config = '<A name="a1"><CalculatedVariable name="calc" value="a1.x + 1"/></A>'
    server, url = await boot(tmp_path, DESIGN, config)
    async with server, Client(url=url) as client:
        calc = client.get_node(ua.NodeId("a1.calc", 2))
        data_value = await calc.read_data_value(raise_on_bad_status=False)
        assert data_value.StatusCode.value == ua.StatusCodes.Bad

        # once the input becomes non-null, the value appears
        x = client.get_node(ua.NodeId("a1.x", 2))
        await x.write_value(ua.Variant(41.0, ua.VariantType.Double))
        assert await calc.read_value() == pytest.approx(42.0)


async def test_malformed_formula_rejected(tmp_path):
    config = '<A name="a1"><CalculatedVariable name="bad" value="__import__(1)"/></A>'
    server, _ = await boot(tmp_path, DESIGN, config)
    from kilonova.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="unsupported construct"):
        await server.init()

"""quasar CalculatedVariables, pure Python.

Config-level ``<FreeVariable>`` and ``<CalculatedVariable>`` elements become
address-space variables; formulas (C++ quasar uses muParser) are compiled here
to a whitelisted Python AST — no ``eval`` — whose inputs are dotted quasar
addresses (``tc.fv``). Recalculation is wired through asyncua's server-side
datachange callbacks, so a dependent value is recomputed *inside* the write
that changed its input: the very next read is already fresh.

Supported formula syntax: numbers, dotted addresses, ``+ - * / % **`` and
unary minus (muParser's ``^`` is accepted and treated as power),
``$thisObjectAddress`` substitution and ``$applyGenericFormula(Name)``.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field

from asyncua import ua

from kilonova.errors import ConfigurationError

_log = logging.getLogger(__name__)

_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

_GENERIC_CALL = re.compile(r"\$applyGenericFormula\((\w+)\)")


@dataclass
class CompiledFormula:
    text: str
    tree: ast.Expression
    inputs: tuple[str, ...] = field(default_factory=tuple)


def _address_of(node: ast.expr) -> str | None:
    """Reconstruct a dotted quasar address from a Name/Attribute chain."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def compile_formula(text: str) -> CompiledFormula:
    """Parse and validate a formula; muParser's ``^`` is mapped to python ``**``."""
    normalized = text.strip().replace("^", "**")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ConfigurationError(f"cannot parse formula {text!r}: {exc}") from exc

    inputs: list[str] = []

    def validate(node: ast.expr) -> None:
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            validate(node.left)
            validate(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            validate(node.operand)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            pass
        elif (address := _address_of(node)) is not None:
            if address not in inputs:
                inputs.append(address)
        else:
            raise ConfigurationError(
                f"formula {text!r}: unsupported construct {ast.dump(node)[:60]}"
            )

    validate(tree.body)
    return CompiledFormula(text=text, tree=tree, inputs=tuple(inputs))


def evaluate(compiled: CompiledFormula, env: dict[str, float]) -> float:
    def walk(node: ast.expr) -> float:
        if isinstance(node, ast.BinOp):
            return _BINOPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp):
            operand = walk(node.operand)
            return -operand if isinstance(node.op, ast.USub) else operand
        if isinstance(node, ast.Constant):
            return float(node.value)
        return env[_address_of(node)]

    return walk(compiled.tree.body)


_FREE_VARIABLE_PARSERS = {
    "Boolean": lambda text: text in ("true", "1", "OpcUa_True"),
    "Float": float,
    "Double": float,
    "String": str,
}


class CalculatedVariablesEngine:
    """Owns free variables, formulas, the dependency graph, and recomputation."""

    def __init__(self, ua_server, namespace_index: int):
        self._server = ua_server
        self._ns = namespace_index
        self._formulas: dict[str, CompiledFormula] = {}
        self._dependents: dict[str, list[str]] = {}
        self._generic_formulas: dict[str, str] = {}
        self._last: dict[str, object] = {}

    def register_generic_formula(self, name: str, formula: str) -> None:
        self._generic_formulas[name] = formula

    def resolve_formula_text(self, text: str, this_object_address: str) -> str:
        def expand_generic(match: re.Match) -> str:
            try:
                return f"({self._generic_formulas[match.group(1)]})"
            except KeyError:
                raise ConfigurationError(
                    f"unknown generic formula {match.group(1)!r}"
                ) from None

        text = _GENERIC_CALL.sub(expand_generic, text)
        return text.replace("$thisObjectAddress.", f"{this_object_address}." if
                            this_object_address else "")

    async def add_free_variable(
        self, parent_node, parent_address: str, name: str, data_type: str,
        initial_value: str | None, access_level: str = "RW",
    ) -> None:
        address = f"{parent_address}.{name}" if parent_address else name
        try:
            variant_type = ua.VariantType[data_type]
        except KeyError:
            raise ConfigurationError(
                f"free variable {address}: unknown type {data_type!r}"
            ) from None
        parser = _FREE_VARIABLE_PARSERS.get(data_type, int)
        value = parser(initial_value) if initial_value is not None else None
        node = await parent_node.add_variable(
            ua.NodeId(address, self._ns),
            ua.QualifiedName(name, self._ns),
            ua.Variant(value, variant_type if value is not None else ua.VariantType.Null),
            datatype=ua.NodeId(variant_type.value),
        )
        if access_level != "R":  # R | RW | W, as in C++ FreeVariablesEngine
            await node.set_writable(True)

    async def add_calculated_variable(
        self, parent_node, parent_address: str, name: str, formula_text: str
    ) -> None:
        address = f"{parent_address}.{name}" if parent_address else name
        resolved = self.resolve_formula_text(formula_text, parent_address)
        compiled = compile_formula(resolved)
        # like the C++ oracle: calculated variables expose BaseDataType, read-only
        await parent_node.add_variable(
            ua.NodeId(address, self._ns),
            ua.QualifiedName(name, self._ns),
            ua.Variant(None, ua.VariantType.Null),
            datatype=ua.NodeId(ua.ObjectIds.BaseDataType),
        )
        self._formulas[address] = compiled
        for input_address in compiled.inputs:
            self._dependents.setdefault(input_address, []).append(address)

    async def wire_and_evaluate(self) -> None:
        """Subscribe to every input and compute initial values (document order)."""
        aspace = self._server.iserver.aspace
        for input_address in self._dependents:
            status, _handle = aspace.add_datachange_callback(
                ua.NodeId(input_address, self._ns),
                ua.AttributeIds.Value,
                self._make_input_listener(input_address),
            )
            if not status.is_good():
                raise ConfigurationError(
                    f"calculated variables: input {input_address!r} does not exist"
                )
        for address in self._formulas:
            await self._recompute(address)

    def _make_input_listener(self, input_address: str):
        async def on_change(_handle, _data_value) -> None:
            for dependent in self._dependents.get(input_address, ()):
                await self._recompute(dependent)

        return on_change

    async def _recompute(self, address: str) -> None:
        aspace = self._server.iserver.aspace
        compiled = self._formulas[address]
        env: dict[str, float] = {}
        good = True
        # C++ parity: inputs still waiting propagate BadWaitingForInitialData;
        # any other bad/null input propagates plain Bad
        bad_status = ua.StatusCodes.BadWaitingForInitialData
        for input_address in compiled.inputs:
            data_value = aspace.read_attribute_value(
                ua.NodeId(input_address, self._ns), ua.AttributeIds.Value
            )
            value = data_value.Value.Value if data_value.Value is not None else None
            in_status = data_value.StatusCode
            if in_status is not None and not in_status.is_good():
                good = False
                if in_status.value != ua.StatusCodes.BadWaitingForInitialData:
                    bad_status = ua.StatusCodes.Bad
                break
            if value is None:
                good = False
                bad_status = ua.StatusCodes.Bad
                break
            env[input_address] = float(value)

        if good:
            try:
                result = evaluate(compiled, env)
            except ArithmeticError:
                good = False
                bad_status = ua.StatusCodes.Bad
        new = (result, ua.StatusCodes.Good) if good else (None, bad_status)
        if self._last.get(address) == new:
            return  # unchanged: stop propagation (also breaks accidental cycles)
        self._last[address] = new
        data_value = (
            ua.DataValue(ua.Variant(new[0], ua.VariantType.Double), ua.StatusCode(new[1]))
            if good
            else ua.DataValue(ua.Variant(None, ua.VariantType.Null), ua.StatusCode(new[1]))
        )
        await aspace.write_attribute_value(
            ua.NodeId(address, self._ns), ua.AttributeIds.Value, data_value
        )

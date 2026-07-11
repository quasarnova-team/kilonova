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
import math
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

_COMPARES = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
}

#: muParser's built-in function set (quasar Documentation/CalculatedVariables.rst)
#: plus pow(), which quasar adds on top. log and ln are both base e, as in muParser.
_FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "asinh": math.asinh, "acosh": math.acosh, "atanh": math.atanh,
    "log": math.log, "ln": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "sqrt": math.sqrt, "abs": abs,
    "sign": lambda x: (x > 0) - (x < 0), "rint": round,
    "min": min, "max": max, "sum": lambda *a: sum(a),
    "avg": lambda *a: sum(a) / len(a), "pow": math.pow,
}

_CONSTANTS = {"_pi": math.pi, "_e": math.e}

_GENERIC_CALL = re.compile(r"\$applyGenericFormula\((\w+)\)")
_PARENT_ADDR = re.compile(r"\$parentObjectAddress\(numLevelsUp=(\d+)\)")
_ESCAPED_TOKEN = re.compile(r"(?:[\w.]|\\[-/])+")


def _escape_address(address: str) -> str:
    return address.replace("-", "\\-").replace("/", "\\/")


def _translate_ternary(text: str) -> str:
    """muParser 'c ? a : b' -> python '((a) if (c) else (b))', right-associative."""
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "?" and depth == 0:
            cond = text[:i]
            rest = text[i + 1:]
            rdepth = 0
            for j, rc in enumerate(rest):
                if rc == "(":
                    rdepth += 1
                elif rc == ")":
                    rdepth -= 1
                elif rc == ":" and rdepth == 0:
                    a, b = rest[:j], rest[j + 1:]
                    return (f"(({_translate_ternary(a)}) if ({_translate_ternary(cond)})"
                            f" else ({_translate_ternary(b)}))")
            raise ConfigurationError(f"ternary without ':' in formula fragment {text!r}")
    return text


@dataclass
class CompiledFormula:
    text: str
    tree: ast.Expression
    inputs: tuple[str, ...] = field(default_factory=tuple)
    aliases: dict[str, str] = field(default_factory=dict)


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


def compile_formula(text: str, aliases: dict[str, str] | None = None) -> CompiledFormula:
    """Parse and validate a formula in the muParser dialect quasar uses.

    ``^`` maps to python ``**``, ``&&``/``||`` to and/or, ``c ? a : b`` to a
    conditional expression; ``aliases`` maps placeholder identifiers back to
    the real (escaped) input addresses.
    """
    aliases = aliases or {}
    normalized = text.strip().replace("^", "**").replace("&&", " and ").replace("||", " or ")
    normalized = _translate_ternary(normalized)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ConfigurationError(f"cannot parse formula {text!r}: {exc}") from exc

    inputs: list[str] = []

    def validate(node: ast.expr) -> None:
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            validate(node.left)
            validate(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            validate(node.operand)
        elif isinstance(node, ast.Compare) and all(type(op) in _COMPARES for op in node.ops):
            validate(node.left)
            for comparator in node.comparators:
                validate(comparator)
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                validate(value)
        elif isinstance(node, ast.IfExp):
            validate(node.test)
            validate(node.body)
            validate(node.orelse)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _FUNCTIONS and not node.keywords:
            for argument in node.args:
                validate(argument)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))) or (
            isinstance(node, ast.Name) and node.id in _CONSTANTS
        ):
            pass
        elif (address := _address_of(node)) is not None:
            address = aliases.get(address, address)
            if address not in inputs:
                inputs.append(address)
        else:
            raise ConfigurationError(
                f"formula {text!r}: unsupported construct {ast.dump(node)[:60]}"
            )

    validate(tree.body)
    return CompiledFormula(text=text, tree=tree, inputs=tuple(inputs), aliases=dict(aliases))


def evaluate(compiled: CompiledFormula, env: dict[str, float]) -> float:
    def walk(node: ast.expr) -> float:
        if isinstance(node, ast.BinOp):
            return _BINOPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp):
            operand = walk(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.Not):
                return float(not operand)
            return operand
        if isinstance(node, ast.Compare):
            left = walk(node.left)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = walk(comparator)
                if not _COMPARES[type(op)](left, right):
                    return 0.0
                left = right
            return 1.0
        if isinstance(node, ast.BoolOp):
            results = [walk(value) for value in node.values]
            truth = all(results) if isinstance(node.op, ast.And) else any(results)
            return float(truth)
        if isinstance(node, ast.IfExp):
            return walk(node.body) if walk(node.test) else walk(node.orelse)
        if isinstance(node, ast.Call):
            return float(_FUNCTIONS[node.func.id](*[walk(a) for a in node.args]))
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        address = _address_of(node)
        return env[compiled.aliases.get(address, address)]

    return float(walk(compiled.tree.body))


_FREE_VARIABLE_PARSERS = {
    "Boolean": lambda text: text in ("true", "1", "OpcUa_True"),
    "Float": float,
    "Double": float,
    "String": str,
}


@dataclass
class _CalculatedSpec:
    value: CompiledFormula
    status: CompiledFormula | None = None
    is_boolean: bool = False
    initial_pending: bool = False  # initialValue holds until first good evaluation


class CalculatedVariablesEngine:
    """Owns free variables, formulas, the dependency graph, and recomputation."""

    def __init__(self, ua_server, namespace_index: int):
        self._server = ua_server
        self._ns = namespace_index
        self._formulas: dict[str, _CalculatedSpec] = {}
        self._dependents: dict[str, list[str]] = {}
        self._generic_formulas: dict[str, str] = {}
        self._last: dict[str, object] = {}

    def register_generic_formula(self, name: str, formula: str) -> None:
        self._generic_formulas[name] = formula

    def resolve_formula_text(
        self, text: str, this_object_address: str
    ) -> tuple[str, dict[str, str]]:
        """Expand meta-functions and escaped addresses.

        Returns the python-parseable text plus an alias map from placeholder
        identifiers to real input addresses (needed when an address contains
        ``-`` or ``/``, escaped in the muParser dialect as ``\\-`` / ``\\/``).
        """
        def expand_generic(match: re.Match) -> str:
            try:
                return f"({self._generic_formulas[match.group(1)]})"
            except KeyError:
                raise ConfigurationError(
                    f"unknown generic formula {match.group(1)!r}"
                ) from None

        def expand_parent(match: re.Match) -> str:
            levels = int(match.group(1))
            parts = this_object_address.split(".") if this_object_address else []
            if levels > len(parts):
                raise ConfigurationError(
                    f"$parentObjectAddress(numLevelsUp={levels}) goes above the root "
                    f"(this object is {this_object_address!r})"
                )
            return _escape_address(".".join(parts[: len(parts) - levels]))

        text = _GENERIC_CALL.sub(expand_generic, text)
        text = _PARENT_ADDR.sub(expand_parent, text)
        this_escaped = _escape_address(this_object_address)
        for token in ("$thisObjectAddress", "$_"):
            text = text.replace(f"{token}.", f"{this_escaped}." if this_escaped else "")

        aliases: dict[str, str] = {}

        def to_placeholder(match: re.Match) -> str:
            token = match.group(0)
            if "\\" not in token:
                return token
            placeholder = f"__kn{len(aliases)}__"
            aliases[placeholder] = token.replace("\\-", "-").replace("\\/", "/")
            return placeholder

        text = _ESCAPED_TOKEN.sub(to_placeholder, text)
        return text, aliases

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
        self, parent_node, parent_address: str, name: str, formula_text: str,
        initial_value: str | None = None, is_boolean: bool = False,
        status_formula: str | None = None,
    ) -> None:
        address = f"{parent_address}.{name}" if parent_address else name
        resolved, aliases = self.resolve_formula_text(formula_text, parent_address)
        compiled_status = None
        if status_formula is not None:
            resolved_status, status_aliases = self.resolve_formula_text(
                status_formula, parent_address
            )
            compiled_status = compile_formula(resolved_status, status_aliases)
        spec = _CalculatedSpec(
            value=compile_formula(resolved, aliases),
            status=compiled_status,
            is_boolean=is_boolean,
            initial_pending=initial_value is not None,
        )
        # C++ parity: initialValue is published with Good status before the
        # first evaluation; otherwise the variable starts null
        if initial_value is not None:
            raw = float(initial_value)
            initial = ua.Variant(bool(raw) if is_boolean else raw,
                                 ua.VariantType.Boolean if is_boolean
                                 else ua.VariantType.Double)
        else:
            initial = ua.Variant(None, ua.VariantType.Null)
        # like the C++ oracle: calculated variables expose BaseDataType, read-only
        await parent_node.add_variable(
            ua.NodeId(address, self._ns),
            ua.QualifiedName(name, self._ns),
            initial,
            datatype=ua.NodeId(ua.ObjectIds.BaseDataType),
        )
        self._formulas[address] = spec
        inputs = set(spec.value.inputs)
        if compiled_status is not None:
            inputs |= set(compiled_status.inputs)
        for input_address in inputs:
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
        spec = self._formulas[address]
        compiled = spec.value
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
        if good and spec.status is not None:
            # C++ parity: the status formula decides Good/Bad (non-zero = Good)
            status_env: dict[str, float] = {}
            for input_address in spec.status.inputs:
                dv = aspace.read_attribute_value(
                    ua.NodeId(input_address, self._ns), ua.AttributeIds.Value
                )
                value = dv.Value.Value if dv.Value is not None else None
                if value is None or (dv.StatusCode is not None and not dv.StatusCode.is_good()):
                    good = False
                    bad_status = ua.StatusCodes.Bad
                    break
                status_env[input_address] = float(value)
            else:
                try:
                    if evaluate(spec.status, status_env) == 0.0:
                        good = False
                        bad_status = ua.StatusCodes.Bad
                except ArithmeticError:
                    good = False
                    bad_status = ua.StatusCodes.Bad
        if good and spec.is_boolean:
            result = bool(result)
        if not good and spec.initial_pending:
            return  # C++ parity: initialValue (Good) holds until first good evaluation
        if good:
            spec.initial_pending = False
        new = (result, ua.StatusCodes.Good) if good else (None, bad_status)
        if self._last.get(address) == new:
            return  # unchanged: stop propagation (also breaks accidental cycles)
        self._last[address] = new
        if good:
            variant_type = ua.VariantType.Boolean if spec.is_boolean else ua.VariantType.Double
            data_value = ua.DataValue(ua.Variant(new[0], variant_type), ua.StatusCode(new[1]))
        else:
            data_value = ua.DataValue(ua.Variant(None, ua.VariantType.Null),
                                      ua.StatusCode(new[1]))
        await aspace.write_attribute_value(
            ua.NodeId(address, self._ns), ua.AttributeIds.Value, data_value
        )

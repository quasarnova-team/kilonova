"""Mapping between quasar Design data types and OPC UA types.

Named after quasar's own FrameworkInternals Oracle, which plays the same role
for the C++ code generator.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from asyncua import ua

from microquasar.errors import DesignError


def _parse_bool(text: str) -> bool:
    # Design initialValue uses C++ literals (OpcUa_True), config.xml uses xsd:boolean
    if text in ("true", "1", "OpcUa_True"):
        return True
    if text in ("false", "0", "OpcUa_False"):
        return False
    raise ValueError(f"not a quasar boolean: {text!r}")


#: value ranges of the OPC UA integer types, enforced at parse and set_cv time
_INT_RANGES: dict[ua.VariantType, tuple[int, int]] = {
    ua.VariantType.SByte: (-(2**7), 2**7 - 1),
    ua.VariantType.Byte: (0, 2**8 - 1),
    ua.VariantType.Int16: (-(2**15), 2**15 - 1),
    ua.VariantType.UInt16: (0, 2**16 - 1),
    ua.VariantType.Int32: (-(2**31), 2**31 - 1),
    ua.VariantType.UInt32: (0, 2**32 - 1),
    ua.VariantType.Int64: (-(2**63), 2**63 - 1),
    ua.VariantType.UInt64: (0, 2**64 - 1),
}


def _check_int_range(value: int, vt: ua.VariantType) -> int:
    low, high = _INT_RANGES[vt]
    if not low <= value <= high:
        raise ValueError(f"{value} out of range for {vt.name} [{low}, {high}]")
    return value


def _checked_int(vt: ua.VariantType) -> Callable[[str], int]:
    return lambda text: _check_int_range(int(text), vt)


# quasar Design dataType -> (VariantType, parser for XML string values)
_TYPE_MAP: dict[str, tuple[ua.VariantType, Callable[[str], object]]] = {
    "OpcUa_Boolean": (ua.VariantType.Boolean, _parse_bool),
    "OpcUa_SByte": (ua.VariantType.SByte, _checked_int(ua.VariantType.SByte)),
    "OpcUa_Byte": (ua.VariantType.Byte, _checked_int(ua.VariantType.Byte)),
    "OpcUa_Int16": (ua.VariantType.Int16, _checked_int(ua.VariantType.Int16)),
    "OpcUa_UInt16": (ua.VariantType.UInt16, _checked_int(ua.VariantType.UInt16)),
    "OpcUa_Int32": (ua.VariantType.Int32, _checked_int(ua.VariantType.Int32)),
    "OpcUa_UInt32": (ua.VariantType.UInt32, _checked_int(ua.VariantType.UInt32)),
    "OpcUa_Int64": (ua.VariantType.Int64, _checked_int(ua.VariantType.Int64)),
    "OpcUa_UInt64": (ua.VariantType.UInt64, _checked_int(ua.VariantType.UInt64)),
    "OpcUa_Float": (ua.VariantType.Float, float),
    "OpcUa_Double": (ua.VariantType.Double, float),
    "UaString": (ua.VariantType.String, str),
    "UaByteString": (ua.VariantType.ByteString, str.encode),
    # UaVariant cache variables carry values of any type; DataType is BaseDataType.
    "UaVariant": (ua.VariantType.Variant, str),
}

_STATUS_MAP: dict[str, int] = {
    "OpcUa_Good": ua.StatusCodes.Good,
    "OpcUa_Bad": ua.StatusCodes.Bad,
    "OpcUa_BadWaitingForInitialData": ua.StatusCodes.BadWaitingForInitialData,
}

#: NodeId of the BaseDataType (used for UaVariant / typeless variables).
BASE_DATA_TYPE = ua.NodeId(ua.ObjectIds.BaseDataType)


def variant_type(quasar_data_type: str) -> ua.VariantType:
    """VariantType for a quasar Design dataType, e.g. 'OpcUa_Int16' -> Int16."""
    try:
        return _TYPE_MAP[quasar_data_type][0]
    except KeyError:
        raise DesignError(f"unknown quasar dataType: {quasar_data_type!r}") from None


def data_type_node_id(quasar_data_type: str) -> ua.NodeId:
    """DataType attribute NodeId for a quasar dataType.

    Built-in variant type enum values equal their NS0 DataType node ids.
    UaVariant maps to BaseDataType.
    """
    vt = variant_type(quasar_data_type)
    if vt is ua.VariantType.Variant:
        return BASE_DATA_TYPE
    return ua.NodeId(vt.value)


def parse_design_value(text: str, quasar_data_type: str) -> object:
    """Parse an XML attribute string (Design initialValue or config value)."""
    try:
        parser = _TYPE_MAP[quasar_data_type][1]
    except KeyError:
        raise DesignError(f"unknown quasar dataType: {quasar_data_type!r}") from None
    return parser(text)


def parse_design_array(values: list[str], quasar_data_type: str) -> list[object]:
    """Parse an array of XML string values (one per <value> config element)."""
    return [parse_design_value(token, quasar_data_type) for token in values]


def check_restrictions(raw: str, restrictions) -> None:
    """Enforce a Design configRestriction on a raw XML value string.

    Same semantics as quasar's generated Configuration.xsd facets. Raises
    ValueError (callers add the address context).
    """
    if restrictions is None:
        return
    if restrictions.enumeration and raw not in restrictions.enumeration:
        raise ValueError(f"{raw!r} is not one of the enumerated values")
    if restrictions.pattern is not None and re.fullmatch(restrictions.pattern, raw) is None:
        raise ValueError(f"{raw!r} does not match pattern {restrictions.pattern!r}")
    checks = (
        (restrictions.min_inclusive, lambda v, b: v >= b, ">="),
        (restrictions.max_inclusive, lambda v, b: v <= b, "<="),
        (restrictions.min_exclusive, lambda v, b: v > b, ">"),
        (restrictions.max_exclusive, lambda v, b: v < b, "<"),
    )
    for bound, ok, symbol in checks:
        if bound is not None and not ok(float(raw), float(bound)):
            raise ValueError(f"{raw!r} violates bound (must be {symbol} {bound})")


def initial_status(status_text: str) -> int:
    """StatusCode for a Design initialStatus attribute."""
    try:
        return _STATUS_MAP[status_text]
    except KeyError:
        raise DesignError(f"unknown initialStatus: {status_text!r}") from None


def make_variant(value: object, quasar_data_type: str, is_array: bool) -> ua.Variant:
    """Build a ua.Variant of the design-declared type for a python value.

    ``None`` produces a null variant (quasar nullPolicy=nullAllowed semantics).
    """
    if value is None:
        return ua.Variant(None, ua.VariantType.Null)
    vt = variant_type(quasar_data_type)
    if vt is ua.VariantType.Variant:
        return value if isinstance(value, ua.Variant) else ua.Variant(value)
    if is_array and not isinstance(value, (list, tuple)):
        raise TypeError(f"array cache variable expects a list, got {type(value).__name__}")
    if vt in _INT_RANGES:
        if is_array:
            for element in value:
                _check_int_range(element, vt)
        else:
            _check_int_range(value, vt)
    return ua.Variant(list(value) if is_array else value, vt, is_array=is_array)

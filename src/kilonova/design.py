"""Typed, read-only model of a quasar Design file.

Clean-room replacement for quasar's DesignInspector: instead of exposing xpath
queries over the raw XML, the whole Design is parsed once into frozen
dataclasses carrying exactly what a running server needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from kilonova.errors import DesignError

DESIGN_NS = "http://cern.ch/quasar/Design"
_D = f"{{{DESIGN_NS}}}"


def _local(tag: str) -> str:
    return tag.replace(_D, "")


def _required(element: etree._Element, attribute: str) -> str:
    value = element.get(attribute)
    if not value:
        raise DesignError(
            f"<{_local(element.tag)}> (line {element.sourceline}) is missing "
            f"required attribute {attribute!r}"
        )
    return value


@dataclass(frozen=True)
class Restrictions:
    """A d:configRestriction — value constraints the configuration must satisfy,
    mirroring what quasar's generated Configuration.xsd enforces."""

    enumeration: tuple[str, ...] = ()
    pattern: str | None = None
    min_inclusive: str | None = None
    max_inclusive: str | None = None
    min_exclusive: str | None = None
    max_exclusive: str | None = None


@dataclass(frozen=True)
class CacheVariable:
    """A d:cachevariable — an OPC UA variable backed by an in-server cache."""

    name: str
    data_type: str
    address_space_write: str  # forbidden | regular | delegated
    initialize_with: str  # configuration | valueAndStatus
    null_policy: str | None = None  # nullAllowed | nullForbidden
    initial_value: str | None = None
    initial_status: str | None = None
    default_config_initializer_value: str | None = None
    is_array: bool = False
    array_bounds: tuple[int | None, int | None] = (None, None)
    restrictions: Restrictions | None = None

    @property
    def is_writable(self) -> bool:
        return self.address_space_write in ("regular", "delegated")


@dataclass(frozen=True)
class ConfigEntry:
    """A d:configentry — configured data; scalars surface as read-only properties
    in the address space (array entries stay config-only, matching C++ quasar)."""

    name: str
    data_type: str
    is_key: bool = False
    is_array: bool = False
    default_value: str | None = None
    array_bounds: tuple[int | None, int | None] = (None, None)
    restrictions: Restrictions | None = None


@dataclass(frozen=True)
class MethodArgument:
    """A d:argument or d:returnvalue of a method."""

    name: str
    data_type: str
    is_array: bool = False


@dataclass(frozen=True)
class Method:
    """A d:method with its input arguments and return values."""

    name: str
    arguments: tuple[MethodArgument, ...] = ()
    return_values: tuple[MethodArgument, ...] = ()
    execution_synchronicity: str = "synchronous"  # both map to awaited async dispatch
    call_use_mutex: str = "no"  # no | of_this_method | of_containing_object


@dataclass(frozen=True)
class SourceVariable:
    """A d:sourcevariable — reads/writes are delegated to device logic."""

    name: str
    data_type: str
    address_space_read: str = "forbidden"  # forbidden | synchronous | asynchronous
    address_space_write: str = "forbidden"
    # no | of_this_operation | of_this_variable | of_containing_object |
    # of_parent_of_containing_object | handpicked
    read_use_mutex: str = "no"
    write_use_mutex: str = "no"
    is_array: bool = False

    @property
    def is_readable(self) -> bool:
        return self.address_space_read != "forbidden"

    @property
    def is_writable(self) -> bool:
        return self.address_space_write != "forbidden"


@dataclass(frozen=True)
class CalculatedVariable:
    """A d:calculatedvariable — parsed for totality, not served yet (see PLAN M9)."""

    name: str
    value: str | None = None


@dataclass(frozen=True)
class HasObjects:
    """A d:hasobjects parent-child relation."""

    class_name: str
    instantiate_using: str  # configuration | design
    design_instance_names: tuple[str, ...] = ()
    min_occurs: int = 0
    max_occurs: int | None = None  # None = unbounded


@dataclass(frozen=True)
class QuasarClass:
    """A d:class of the Design."""

    name: str
    cache_variables: tuple[CacheVariable, ...] = ()
    config_entries: tuple[ConfigEntry, ...] = ()
    methods: tuple[Method, ...] = ()
    has_objects: tuple[HasObjects, ...] = ()
    source_variables: tuple[SourceVariable, ...] = ()
    calculated_variables: tuple[CalculatedVariable, ...] = ()
    default_instance_name: str | None = None
    single_variable_node: bool = False
    has_device_logic: bool = False

    def cache_variable(self, name: str) -> CacheVariable:
        for cv in self.cache_variables:
            if cv.name == name:
                return cv
        raise KeyError(f"class {self.name} has no cache variable {name!r}")

    @property
    def the_single_variable(self) -> CacheVariable:
        """The one cache variable of a singleVariableNode class."""
        if not self.single_variable_node or len(self.cache_variables) != 1:
            raise DesignError(
                f"class {self.name} is not a valid singleVariableNode class"
            )
        return self.cache_variables[0]


@dataclass(frozen=True)
class Design:
    """A parsed quasar Design file."""

    project_short_name: str
    classes: dict[str, QuasarClass] = field(default_factory=dict)
    root_has_objects: tuple[HasObjects, ...] = ()

    @classmethod
    def from_file(cls, path: str | Path) -> Design:
        tree = etree.parse(str(path))
        root = tree.getroot()
        if root.tag != f"{_D}design":
            raise DesignError(f"{path}: not a quasar Design file (root is {root.tag})")

        classes: dict[str, QuasarClass] = {}
        root_has_objects: tuple[HasObjects, ...] = ()
        for element in root:
            if not isinstance(element.tag, str):
                continue
            tag = _local(element.tag)
            if tag == "class":
                klass = _parse_class(element)
                if klass.name in classes:
                    raise DesignError(f"duplicate class {klass.name!r} in the Design")
                classes[klass.name] = klass
            elif tag == "root":
                root_has_objects = tuple(
                    _parse_has_objects(child)
                    for child in element
                    if isinstance(child.tag, str) and _local(child.tag) == "hasobjects"
                )

        design = cls(
            project_short_name=root.get("projectShortName", ""),
            classes=classes,
            root_has_objects=root_has_objects,
        )
        _validate(design)
        return design


def _parse_class(element: etree._Element) -> QuasarClass:
    cache_variables: list[CacheVariable] = []
    config_entries: list[ConfigEntry] = []
    methods: list[Method] = []
    has_objects: list[HasObjects] = []
    source_variables: list[SourceVariable] = []
    calculated_variables: list[CalculatedVariable] = []
    has_device_logic = False

    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = _local(child.tag)
        if tag == "cachevariable":
            cache_variables.append(_parse_cache_variable(child))
        elif tag == "configentry":
            config_entries.append(
                ConfigEntry(
                    name=_required(child, "name"),
                    data_type=_required(child, "dataType"),
                    is_key=child.get("isKey") == "true",
                    is_array=any(_local(g.tag) == "array" for g in child
                                 if isinstance(g.tag, str)),
                    default_value=child.get("defaultValue"),
                    restrictions=_parse_restrictions(child),
                    array_bounds=_parse_array_bounds(child),
                )
            )
        elif tag == "method":
            methods.append(_parse_method(child))
        elif tag == "hasobjects":
            has_objects.append(_parse_has_objects(child))
        elif tag == "devicelogic":
            has_device_logic = True
        elif tag == "sourcevariable":
            source_variables.append(
                SourceVariable(
                    name=_required(child, "name"),
                    data_type=_required(child, "dataType"),
                    address_space_read=child.get("addressSpaceRead", "forbidden"),
                    address_space_write=child.get("addressSpaceWrite", "forbidden"),
                    read_use_mutex=child.get("addressSpaceReadUseMutex", "no"),
                    write_use_mutex=child.get("addressSpaceWriteUseMutex", "no"),
                    is_array=any(
                        isinstance(g.tag, str) and _local(g.tag) == "array" for g in child
                    ),
                )
            )
        elif tag == "calculatedvariable":
            calculated_variables.append(
                CalculatedVariable(name=child.get("name"), value=child.get("value"))
            )

    return QuasarClass(
        name=_required(element, "name"),
        cache_variables=tuple(cache_variables),
        config_entries=tuple(config_entries),
        methods=tuple(methods),
        has_objects=tuple(has_objects),
        source_variables=tuple(source_variables),
        calculated_variables=tuple(calculated_variables),
        default_instance_name=element.get("defaultInstanceName"),
        single_variable_node=element.get("singleVariableNode") == "true",
        has_device_logic=has_device_logic,
    )


def _parse_cache_variable(element: etree._Element) -> CacheVariable:
    is_array = any(
        isinstance(child.tag, str) and _local(child.tag) == "array" for child in element
    )
    return CacheVariable(
        name=_required(element, "name"),
        data_type=_required(element, "dataType"),
        address_space_write=element.get("addressSpaceWrite", "forbidden"),
        initialize_with=_required(element, "initializeWith"),
        null_policy=element.get("nullPolicy"),
        initial_value=element.get("initialValue"),
        initial_status=element.get("initialStatus"),
        default_config_initializer_value=element.get("defaultConfigInitializerValue"),
        is_array=is_array,
        array_bounds=_parse_array_bounds(element),
        restrictions=_parse_restrictions(element),
    )


def _parse_array_bounds(element: etree._Element) -> tuple[int | None, int | None]:
    for child in element:
        if isinstance(child.tag, str) and _local(child.tag) == "array":
            low = child.get("minimumSize")
            high = child.get("maximumSize")
            return (int(low) if low is not None else None,
                    int(high) if high is not None else None)
    return (None, None)


def _parse_restrictions(element: etree._Element) -> Restrictions | None:
    for child in element:
        if isinstance(child.tag, str) and _local(child.tag) == "configRestriction":
            enumeration: list[str] = []
            pattern = None
            bounds: dict[str, str | None] = {}
            for restriction in child:
                if not isinstance(restriction.tag, str):
                    continue
                kind = _local(restriction.tag)
                if kind == "restrictionByEnumeration":
                    enumeration.extend(
                        value.get("value")
                        for value in restriction
                        if isinstance(value.tag, str)
                        and _local(value.tag) == "enumerationValue"
                    )
                elif kind == "restrictionByPattern":
                    pattern = restriction.get("pattern")
                elif kind == "restrictionByBounds":
                    for bound in ("minInclusive", "maxInclusive",
                                  "minExclusive", "maxExclusive"):
                        if restriction.get(bound) is not None:
                            bounds[bound] = restriction.get(bound)
            return Restrictions(
                enumeration=tuple(enumeration),
                pattern=pattern,
                min_inclusive=bounds.get("minInclusive"),
                max_inclusive=bounds.get("maxInclusive"),
                min_exclusive=bounds.get("minExclusive"),
                max_exclusive=bounds.get("maxExclusive"),
            )
    return None


def _parse_method(element: etree._Element) -> Method:
    arguments: list[MethodArgument] = []
    return_values: list[MethodArgument] = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = _local(child.tag)
        if tag not in ("argument", "returnvalue"):
            continue
        argument = MethodArgument(
            name=_required(child, "name"),
            data_type=_required(child, "dataType"),
            is_array=any(
                isinstance(g.tag, str) and _local(g.tag) == "array" for g in child
            ),
        )
        (arguments if tag == "argument" else return_values).append(argument)
    return Method(
        name=_required(element, "name"),
        arguments=tuple(arguments),
        return_values=tuple(return_values),
        execution_synchronicity=element.get("executionSynchronicity", "synchronous"),
        call_use_mutex=element.get("addressSpaceCallUseMutex", "no"),
    )


def _parse_has_objects(element: etree._Element) -> HasObjects:
    instantiate_using = element.get("instantiateUsing", "configuration")
    design_names: tuple[str, ...] = ()
    if instantiate_using == "design":
        design_names = tuple(
            _required(child, "name")
            for child in element
            if isinstance(child.tag, str) and _local(child.tag) == "object"
        )
    max_occurs_text = element.get("maxOccurs")
    return HasObjects(
        class_name=_required(element, "class"),
        instantiate_using=instantiate_using,
        design_instance_names=design_names,
        min_occurs=int(element.get("minOccurs", 0)),
        max_occurs=None if max_occurs_text in (None, "unbounded") else int(max_occurs_text),
    )


def _validate(design: Design) -> None:
    for klass in design.classes.values():
        for rel in klass.has_objects:
            if rel.class_name not in design.classes:
                raise DesignError(
                    f"class {klass.name}: hasobjects refers to unknown class {rel.class_name}"
                )
        if klass.single_variable_node and (
            len(klass.cache_variables) + len(klass.source_variables) != 1
        ):
            raise DesignError(
                f"class {klass.name}: singleVariableNode requires exactly one "
                "cache variable or source variable"
            )
        for cv in klass.cache_variables:
            if cv.is_array and cv.initial_value is not None:
                raise DesignError(
                    f"class {klass.name}, cache variable {cv.name}: initialValue is not "
                    "supported on array cache variables"
                )
    for rel in design.root_has_objects:
        if rel.class_name not in design.classes:
            raise DesignError(f"root: hasobjects refers to unknown class {rel.class_name}")

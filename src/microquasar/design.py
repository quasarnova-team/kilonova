"""Typed, read-only model of a quasar Design file.

Clean-room replacement for quasar's DesignInspector: instead of exposing xpath
queries over the raw XML, the whole Design is parsed once into frozen
dataclasses carrying exactly what a running server needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from microquasar.errors import DesignError

DESIGN_NS = "http://cern.ch/quasar/Design"
_D = f"{{{DESIGN_NS}}}"


def _local(tag: str) -> str:
    return tag.replace(_D, "")


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
    is_array: bool = False

    @property
    def is_writable(self) -> bool:
        return self.address_space_write in ("regular", "delegated")


@dataclass(frozen=True)
class ConfigEntry:
    """A d:configentry — configuration-only data, not present in the address space."""

    name: str
    data_type: str
    is_key: bool = False
    is_array: bool = False


@dataclass(frozen=True)
class Method:
    """A d:method. Only the node identity for now; argument support comes with handlers."""

    name: str


@dataclass(frozen=True)
class SourceVariable:
    """A d:sourcevariable — parsed for totality, not served yet (see PLAN M8)."""

    name: str


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
                    name=child.get("name"),
                    data_type=child.get("dataType"),
                    is_key=child.get("isKey") == "true",
                    is_array=any(_local(g.tag) == "array" for g in child
                                 if isinstance(g.tag, str)),
                )
            )
        elif tag == "method":
            methods.append(Method(name=child.get("name")))
        elif tag == "hasobjects":
            has_objects.append(_parse_has_objects(child))
        elif tag == "devicelogic":
            has_device_logic = True
        elif tag == "sourcevariable":
            source_variables.append(SourceVariable(name=child.get("name")))
        elif tag == "calculatedvariable":
            calculated_variables.append(
                CalculatedVariable(name=child.get("name"), value=child.get("value"))
            )

    return QuasarClass(
        name=element.get("name"),
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
        name=element.get("name"),
        data_type=element.get("dataType"),
        address_space_write=element.get("addressSpaceWrite", "forbidden"),
        initialize_with=element.get("initializeWith"),
        null_policy=element.get("nullPolicy"),
        initial_value=element.get("initialValue"),
        initial_status=element.get("initialStatus"),
        is_array=is_array,
    )


def _parse_has_objects(element: etree._Element) -> HasObjects:
    instantiate_using = element.get("instantiateUsing", "configuration")
    design_names: tuple[str, ...] = ()
    if instantiate_using == "design":
        design_names = tuple(
            child.get("name")
            for child in element
            if isinstance(child.tag, str) and _local(child.tag) == "object"
        )
    return HasObjects(
        class_name=element.get("class"),
        instantiate_using=instantiate_using,
        design_instance_names=design_names,
    )


def _validate(design: Design) -> None:
    for klass in design.classes.values():
        for rel in klass.has_objects:
            if rel.class_name not in design.classes:
                raise DesignError(
                    f"class {klass.name}: hasobjects refers to unknown class {rel.class_name}"
                )
        if klass.single_variable_node and len(klass.cache_variables) != 1:
            raise DesignError(
                f"class {klass.name}: singleVariableNode requires exactly one cache variable"
            )
    for rel in design.root_has_objects:
        if rel.class_name not in design.classes:
            raise DesignError(f"root: hasobjects refers to unknown class {rel.class_name}")

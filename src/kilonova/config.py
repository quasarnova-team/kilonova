"""Loading of quasar config.xml files into an instance tree.

The configuration schema of a quasar server is derived from its Design:
elements are class names, scalar cache variables / config entries are
attributes, array values are ``<value>`` child elements (quasar's generated
Configuration.xsd encoding), and child objects are child elements named after
their class. Validation mirrors what the C++ Configurator's XSD layer rejects:
unknown attributes, unknown children, and children not declared in hasobjects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from kilonova.design import Design, QuasarClass
from kilonova.errors import ConfigurationError

CONFIG_NS = "http://cern.ch/quasar/Configuration"
_C = f"{{{CONFIG_NS}}}"

_log = logging.getLogger(__name__)

# Config elements that configure the framework rather than instantiate objects.
_FRAMEWORK_ELEMENTS = {"StandardMetaData", "CalculatedVariables"}


@dataclass
class FreeVariable:
    """A config-level <FreeVariable> — a standalone writable variable."""

    name: str
    data_type: str  # plain OPC UA type name: Double, Int32, ...
    initial_value: str | None = None
    access_level: str = "RW"  # R | RW | W


@dataclass
class CalculatedVariableConfig:
    """A config-level <CalculatedVariable> — a formula over other variables."""

    name: str
    formula: str
    initial_value: str | None = None
    is_boolean: bool = False
    status_formula: str | None = None


@dataclass
class Instance:
    """One object instance declared in config.xml (or defaulted from the Design)."""

    class_name: str
    name: str
    attributes: dict[str, str] = field(default_factory=dict)
    array_values: dict[str, list[str]] = field(default_factory=dict)
    children: list[Instance] = field(default_factory=list)
    free_variables: list[FreeVariable] = field(default_factory=list)
    calculated_variables: list[CalculatedVariableConfig] = field(default_factory=list)


@dataclass
class Configuration:
    """A fully parsed config.xml."""

    instances: list[Instance] = field(default_factory=list)
    free_variables: list[FreeVariable] = field(default_factory=list)
    calculated_variables: list[CalculatedVariableConfig] = field(default_factory=list)
    generic_formulas: dict[str, str] = field(default_factory=dict)
    general_log_level: str | None = None
    component_log_levels: dict[str, str] = field(default_factory=dict)


def load_config(path: str | Path, design: Design) -> Configuration:
    """Parse config.xml into instances plus calculated/free variables."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    if root.tag != f"{_C}configuration":
        raise ConfigurationError(f"{path}: not a quasar configuration file ({root.tag})")
    allowed = {
        rel.class_name
        for rel in design.root_has_objects
        if rel.instantiate_using == "configuration"
    }
    configuration = Configuration()
    for child in root:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.replace(_C, "")
        if tag == "StandardMetaData":
            _parse_standard_meta_data(child, configuration)
        elif tag in _FRAMEWORK_ELEMENTS:
            _log.info("config: skipping framework element %s (not instantiable)", tag)
        elif tag == "FreeVariable":
            configuration.free_variables.append(_parse_free_variable(child))
        elif tag == "CalculatedVariable":
            configuration.calculated_variables.append(_parse_calculated_variable(child))
        elif tag == "CalculatedVariableGenericFormula":
            configuration.generic_formulas[child.get("name")] = child.get("formula")
        elif tag in design.classes:
            if tag not in allowed:
                raise ConfigurationError(
                    f"configuration root: <{tag}> is not declared in hasobjects "
                    f"(allowed here: {sorted(allowed) or 'none'})"
                )
            configuration.instances.append(
                _parse_instance(child, design.classes[tag], design)
            )
        else:
            raise ConfigurationError(
                f"configuration root: <{tag}> is not a class of the Design"
            )
    return configuration


def _parse_standard_meta_data(element: etree._Element, configuration: Configuration) -> None:
    """Initial log levels: <Log><GeneralLogLevel logLevel=../> + <ComponentLogLevel .../>."""
    for general in element.iter(f"{_C}GeneralLogLevel"):
        configuration.general_log_level = general.get("logLevel")
    for component in element.iter(f"{_C}ComponentLogLevel"):
        configuration.component_log_levels[component.get("componentName")] = (
            component.get("logLevel")
        )


def _parse_free_variable(element: etree._Element) -> FreeVariable:
    return FreeVariable(
        name=element.get("name"),
        data_type=element.get("type", "Double"),
        initial_value=element.get("initialValue"),
        access_level=element.get("accessLevel", "RW"),
    )


def _parse_calculated_variable(element: etree._Element) -> CalculatedVariableConfig:
    return CalculatedVariableConfig(
        name=element.get("name"),
        formula=element.get("value"),
        initial_value=element.get("initialValue"),
        is_boolean=element.get("isBoolean") == "true",
        status_formula=element.get("status"),
    )


def _parse_instance(
    element: etree._Element, klass: QuasarClass, design: Design
) -> Instance:
    name = element.get("name") or klass.default_instance_name
    if not name:
        raise ConfigurationError(
            f"<{klass.name}> instance has no name and the class declares no defaultInstanceName"
        )
    where = f"<{klass.name} name={name!r}>"

    scalar_names = {
        cv.name for cv in klass.cache_variables
        if not cv.is_array and cv.initialize_with == "configuration"
    } | {ce.name for ce in klass.config_entries if not ce.is_array}
    array_names = {
        cv.name for cv in klass.cache_variables
        if cv.is_array and cv.initialize_with == "configuration"
    } | {ce.name for ce in klass.config_entries if ce.is_array}
    child_classes = {
        rel.class_name for rel in klass.has_objects
        if rel.instantiate_using == "configuration"
    }

    attributes: dict[str, str] = {}
    for key, value in element.attrib.items():
        if key == "name" or key.startswith("{"):  # skip name + namespaced (xsi:...) attrs
            continue
        if key not in scalar_names:
            raise ConfigurationError(
                f"{where}: unknown attribute {key!r} "
                f"(configurable scalars: {sorted(scalar_names) or 'none'})"
            )
        attributes[key] = value

    instance = Instance(class_name=klass.name, name=name, attributes=attributes)

    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.replace(_C, "")
        if tag in array_names:
            instance.array_values[tag] = _parse_array_values(child, where)
        elif tag in _FRAMEWORK_ELEMENTS:
            _log.info("config: skipping framework element %s inside %s", tag, where)
        elif tag == "FreeVariable":
            instance.free_variables.append(_parse_free_variable(child))
        elif tag == "CalculatedVariable":
            instance.calculated_variables.append(_parse_calculated_variable(child))
        elif tag in child_classes:
            child_instance = _parse_instance(child, design.classes[tag], design)
            if any(sibling.name == child_instance.name for sibling in instance.children):
                raise ConfigurationError(
                    f"{where}: duplicate child instance name {child_instance.name!r}"
                )
            instance.children.append(child_instance)
        elif tag in design.classes:
            raise ConfigurationError(
                f"{where}: <{tag}> is not declared in this class's hasobjects "
                f"(allowed children: {sorted(child_classes) or 'none'})"
            )
        else:
            raise ConfigurationError(f"{where}: unexpected child element <{tag}>")
    _check_key_uniqueness(instance, design, where)
    return instance


def _check_key_uniqueness(instance: Instance, design: Design, where: str) -> None:
    """isKey config entries must be unique among same-class siblings (xs:unique)."""
    seen: dict[tuple[str, str], set[str]] = {}
    for child in instance.children:
        child_class = design.classes[child.class_name]
        for entry in child_class.config_entries:
            if not entry.is_key:
                continue
            value = child.attributes.get(entry.name, entry.default_value)
            if value is None:
                continue
            bucket = seen.setdefault((child.class_name, entry.name), set())
            if value in bucket:
                raise ConfigurationError(
                    f"{where}: duplicate key {entry.name}={value!r} among "
                    f"<{child.class_name}> children"
                )
            bucket.add(value)


def _parse_array_values(element: etree._Element, where: str) -> list[str]:
    """Arrays are sequences of <value> elements, per quasar's Configuration.xsd."""
    values = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.replace(_C, "")
        if tag != "value":
            raise ConfigurationError(
                f"{where}: array <{element.tag.replace(_C, '')}> may only contain "
                f"<value> elements, got <{tag}>"
            )
        values.append(child.text or "")
    if not values and element.text and element.text.strip():
        raise ConfigurationError(
            f"{where}: array <{element.tag.replace(_C, '')}> uses text content; quasar "
            "configurations encode arrays as <value>...</value> child elements"
        )
    return values

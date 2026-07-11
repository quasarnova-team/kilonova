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

from microquasar.design import Design, QuasarClass
from microquasar.errors import ConfigurationError

CONFIG_NS = "http://cern.ch/quasar/Configuration"
_C = f"{{{CONFIG_NS}}}"

_log = logging.getLogger(__name__)

# Config elements that configure the framework rather than instantiate objects.
_FRAMEWORK_ELEMENTS = {"StandardMetaData", "CalculatedVariables"}


@dataclass
class Instance:
    """One object instance declared in config.xml (or defaulted from the Design)."""

    class_name: str
    name: str
    attributes: dict[str, str] = field(default_factory=dict)
    array_values: dict[str, list[str]] = field(default_factory=dict)
    children: list[Instance] = field(default_factory=list)


def load_config(path: str | Path, design: Design) -> list[Instance]:
    """Parse config.xml into a list of top-level instances."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    if root.tag != f"{_C}configuration":
        raise ConfigurationError(f"{path}: not a quasar configuration file ({root.tag})")
    allowed = {
        rel.class_name
        for rel in design.root_has_objects
        if rel.instantiate_using == "configuration"
    }
    return _parse_children(root, design, allowed, where="configuration root")


def _parse_children(
    element: etree._Element, design: Design, allowed_classes: set[str], where: str
) -> list[Instance]:
    instances = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.replace(_C, "")
        if tag in _FRAMEWORK_ELEMENTS:
            _log.info("config: skipping framework element %s (not instantiable)", tag)
            continue
        if tag not in design.classes:
            raise ConfigurationError(f"{where}: <{tag}> is not a class of the Design")
        if tag not in allowed_classes:
            raise ConfigurationError(
                f"{where}: <{tag}> is not declared in hasobjects "
                f"(allowed here: {sorted(allowed_classes) or 'none'})"
            )
        instances.append(_parse_instance(child, design.classes[tag], design))
    return instances


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
        elif tag in child_classes:
            instance.children.append(_parse_instance(child, design.classes[tag], design))
        elif tag in design.classes:
            raise ConfigurationError(
                f"{where}: <{tag}> is not declared in this class's hasobjects "
                f"(allowed children: {sorted(child_classes) or 'none'})"
            )
        else:
            raise ConfigurationError(f"{where}: unexpected child element <{tag}>")
    return instance


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

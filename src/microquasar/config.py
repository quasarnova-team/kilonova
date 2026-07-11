"""Loading of quasar config.xml files into an instance tree.

The configuration schema of a quasar server is derived from its Design:
elements are class names, scalar cache variables / config entries are
attributes, array cache variables and child objects are child elements.
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
    array_values: dict[str, str | None] = field(default_factory=dict)
    children: list[Instance] = field(default_factory=list)


def load_config(path: str | Path, design: Design) -> list[Instance]:
    """Parse config.xml into a list of top-level instances."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    if root.tag != f"{_C}configuration":
        raise ConfigurationError(f"{path}: not a quasar configuration file ({root.tag})")
    return _parse_children(root, design)


def _parse_children(element: etree._Element, design: Design) -> list[Instance]:
    instances = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.replace(_C, "")
        if tag in _FRAMEWORK_ELEMENTS:
            _log.info("config: skipping framework element %s (not instantiable)", tag)
            continue
        if tag not in design.classes:
            raise ConfigurationError(f"config element <{tag}> is not a class of the Design")
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

    array_names = {cv.name for cv in klass.cache_variables if cv.is_array}
    array_names |= {ce.name for ce in klass.config_entries if ce.is_array}
    instance = Instance(
        class_name=klass.name,
        name=name,
        attributes={k: v for k, v in element.attrib.items() if k != "name"},
    )

    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.replace(_C, "")
        if tag in array_names:
            instance.array_values[tag] = child.text
        elif tag in design.classes:
            instance.children.append(_parse_instance(child, design.classes[tag], design))
        elif tag in _FRAMEWORK_ELEMENTS:
            _log.info("config: skipping framework element %s inside <%s>", tag, klass.name)
        else:
            raise ConfigurationError(
                f"<{klass.name} name={name!r}>: unexpected child element <{tag}>"
            )
    return instance

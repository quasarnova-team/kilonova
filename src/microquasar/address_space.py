"""Building the quasar address space inside an asyncua server.

Address rules match C++ quasar exactly: instances live in namespace 2 with
string NodeIds of dotted paths (``sca1.online``), object types get numeric ids
from 1000 upward.
"""

from __future__ import annotations

import logging

import asyncua
from asyncua import ua
from asyncua.common.node import Node

from microquasar import oracle
from microquasar.config import Instance
from microquasar.design import (
    CacheVariable,
    ConfigEntry,
    Design,
    Method,
    MethodArgument,
    QuasarClass,
)
from microquasar.errors import ConfigurationError, DesignError
from microquasar.objects import QuasarObject

_log = logging.getLogger(__name__)

FIRST_TYPE_ID = 1000


async def _not_implemented_method(parent, *args):
    return ua.StatusCode(ua.StatusCodes.BadNotImplemented)


class AddressSpaceBuilder:
    """Creates types and instances for one Design inside one asyncua server."""

    def __init__(
        self,
        ua_server: asyncua.Server,
        design: Design,
        namespace_index: int,
        method_dispatcher_factory=None,
    ):
        self._server = ua_server
        self._design = design
        self._ns = namespace_index
        self._make_dispatcher = method_dispatcher_factory
        self._type_nodes: dict[str, Node] = {}
        #: All instantiated objects keyed by their dotted string address.
        self.objects: dict[str, QuasarObject] = {}

    # -- types ---------------------------------------------------------------

    async def build_types(self) -> None:
        """One bare ObjectType per Design class, numeric ids from 1000 up."""
        base = self._server.get_node(ua.NodeId(ua.ObjectIds.BaseObjectType))
        for offset, klass in enumerate(self._design.classes.values()):
            type_node = await base.add_object_type(
                ua.NodeId(FIRST_TYPE_ID + offset, self._ns),
                ua.QualifiedName(klass.name, self._ns),
            )
            self._type_nodes[klass.name] = type_node

    # -- instances -----------------------------------------------------------

    async def instantiate_root_design_objects(self) -> None:
        """Objects the Design itself mandates at the root (instantiateUsing="design")."""
        objects_folder = self._server.nodes.objects
        for rel in self._design.root_has_objects:
            if rel.instantiate_using != "design":
                continue
            klass = self._design.classes[rel.class_name]
            for instance_name in rel.design_instance_names:
                await self._instantiate(
                    Instance(class_name=klass.name, name=instance_name),
                    objects_folder,
                    parent_address=None,
                )

    async def instantiate_from_config(self, instances: list[Instance]) -> None:
        objects_folder = self._server.nodes.objects
        for instance in instances:
            await self._instantiate(instance, objects_folder, parent_address=None)

    async def _instantiate(
        self, instance: Instance, parent_node: Node, parent_address: str | None
    ) -> QuasarObject:
        klass = self._design.classes[instance.class_name]
        if klass.source_variables:
            raise DesignError(f"class {klass.name}: source variables not supported yet (M8)")
        if klass.calculated_variables:
            raise DesignError(f"class {klass.name}: calculated variables not supported yet (M9)")
        address = instance.name if parent_address is None else f"{parent_address}.{instance.name}"
        node_id = ua.NodeId(address, self._ns)
        browse_name = ua.QualifiedName(instance.name, self._ns)
        _log.debug("instantiating %s %r", klass.name, address)

        if klass.single_variable_node:
            node = await self._add_single_variable_node(parent_node, node_id, browse_name, klass)
            quasar_object = QuasarObject(self._server, klass, node, address)
            quasar_object.cache_variables[klass.the_single_variable.name] = node
        else:
            node = await parent_node.add_object(
                node_id, browse_name, objecttype=self._type_nodes[klass.name].nodeid
            )
            quasar_object = QuasarObject(self._server, klass, node, address)
            for cv in klass.cache_variables:
                var_node = await self._add_cache_variable(node, address, cv, instance)
                quasar_object.cache_variables[cv.name] = var_node
            for entry in klass.config_entries:
                await self._add_config_entry(node, address, entry, instance)
            for method in klass.methods:
                await self._add_method(node, address, method)

        self.objects[address] = quasar_object

        # children from the configuration...
        for child in instance.children:
            await self._instantiate(child, node, address)
        # ...and children the Design mandates on every instance of this class
        for rel in klass.has_objects:
            if rel.instantiate_using != "design":
                continue
            for child_name in rel.design_instance_names:
                await self._instantiate(
                    Instance(class_name=rel.class_name, name=child_name), node, address
                )
        return quasar_object

    # -- variables -----------------------------------------------------------

    async def _add_single_variable_node(
        self, parent_node: Node, node_id: ua.NodeId, browse_name: ua.QualifiedName,
        klass: QuasarClass,
    ) -> Node:
        """singleVariableNode classes collapse to one variable named as the instance."""
        cv = klass.the_single_variable
        data_value = self._initial_data_value(cv, instance=None)
        node = await parent_node.add_variable(
            node_id, browse_name, data_value.Value, datatype=oracle.data_type_node_id(cv.data_type)
        )
        await self._finalize_variable(node, cv, data_value)
        return node

    async def _add_cache_variable(
        self, object_node: Node, parent_address: str, cv: CacheVariable, instance: Instance
    ) -> Node:
        node_id = ua.NodeId(f"{parent_address}.{cv.name}", self._ns)
        data_value = self._initial_data_value(cv, instance)
        node = await object_node.add_variable(
            node_id,
            ua.QualifiedName(cv.name, self._ns),
            data_value.Value,
            datatype=oracle.data_type_node_id(cv.data_type),
        )
        await self._finalize_variable(node, cv, data_value)
        return node

    async def _add_config_entry(
        self, object_node: Node, parent_address: str, entry: ConfigEntry, instance: Instance
    ) -> None:
        """Config entries surface as read-only properties, like C++ quasar exposes them."""
        if entry.is_array:
            raw_text = instance.array_values.get(entry.name)
            value = (
                oracle.parse_design_array(raw_text, entry.data_type)
                if entry.name in instance.array_values
                else None
            )
        else:
            raw = instance.attributes.get(entry.name)
            value = oracle.parse_design_value(raw, entry.data_type) if raw is not None else None
        variant = oracle.make_variant(value, entry.data_type, entry.is_array)
        node = await object_node.add_property(
            ua.NodeId(f"{parent_address}.{entry.name}", self._ns),
            ua.QualifiedName(entry.name, self._ns),
            variant,
            datatype=oracle.data_type_node_id(entry.data_type),
        )
        await self._write_value_rank(node, self._value_rank(entry.is_array, entry.data_type))

    async def _add_method(self, object_node: Node, parent_address: str, method: Method) -> None:
        address = f"{parent_address}.{method.name}"
        callback = (
            self._make_dispatcher(parent_address, method)
            if self._make_dispatcher is not None
            else _not_implemented_method
        )
        method_node = await object_node.add_method(
            ua.NodeId(address, self._ns),
            ua.QualifiedName(method.name, self._ns),
            callback,
        )
        # quasar publishes argument properties at <method>.args / <method>.return_values
        if method.arguments:
            await self._add_argument_property(
                method_node, f"{address}.args", "InputArguments", method.arguments
            )
        if method.return_values:
            await self._add_argument_property(
                method_node, f"{address}.return_values", "OutputArguments", method.return_values
            )

    async def _add_argument_property(
        self, method_node: Node, address: str, browse_name: str,
        arguments: tuple[MethodArgument, ...],
    ) -> None:
        value = [
            ua.Argument(
                Name=arg.name,
                DataType=oracle.data_type_node_id(arg.data_type),
                ValueRank=self._value_rank(arg.is_array, arg.data_type),
                ArrayDimensions=[],
                Description=ua.LocalizedText(""),
            )
            for arg in arguments
        ]
        node = await method_node.add_property(
            ua.NodeId(address, self._ns),
            ua.QualifiedName(browse_name, 0),
            value,
            datatype=ua.NodeId(ua.ObjectIds.Argument),
        )
        await self._write_value_rank(node, 1)

    @staticmethod
    def _value_rank(is_array: bool, data_type: str) -> int:
        """quasar semantics: arrays are one-dimensional; UaVariant is ScalarOrOneDimension."""
        if is_array:
            return 1
        if data_type == "UaVariant":
            return -3
        return -1

    async def _write_value_rank(self, node: Node, rank: int) -> None:
        await self._server.write_attribute_value(
            node.nodeid,
            ua.DataValue(ua.Variant(rank, ua.VariantType.Int32)),
            ua.AttributeIds.ValueRank,
        )

    async def _finalize_variable(self, node: Node, cv: CacheVariable, dv: ua.DataValue) -> None:
        rank = self._value_rank(cv.is_array, cv.data_type)
        await self._server.write_attribute_value(
            node.nodeid,
            ua.DataValue(ua.Variant(rank, ua.VariantType.Int32)),
            ua.AttributeIds.ValueRank,
        )
        if cv.is_writable:
            await node.set_writable(True)
        # write the full DataValue (value + status) after creation: add_variable
        # alone would leave status Good even for BadWaitingForInitialData designs
        await self._server.write_attribute_value(node.nodeid, dv)

    def _initial_data_value(self, cv: CacheVariable, instance: Instance | None) -> ua.DataValue:
        if cv.initialize_with == "valueAndStatus":
            if cv.initial_value is not None:
                value = oracle.parse_design_value(cv.initial_value, cv.data_type)
                variant = oracle.make_variant(value, cv.data_type, cv.is_array)
            else:
                variant = ua.Variant(None, ua.VariantType.Null)
            if cv.initial_status is None:
                raise DesignError(f"cache variable {cv.name}: valueAndStatus needs initialStatus")
            status = oracle.initial_status(cv.initial_status)
            return ua.DataValue(variant, ua.StatusCode(status))

        if cv.initialize_with == "configuration":
            raw: str | None = None
            if instance is not None and cv.is_array:
                if cv.name in instance.array_values:
                    values = oracle.parse_design_array(
                        instance.array_values[cv.name], cv.data_type
                    )
                    variant = oracle.make_variant(values, cv.data_type, is_array=True)
                    return ua.DataValue(variant, ua.StatusCode(ua.StatusCodes.Good))
            elif instance is not None:
                raw = instance.attributes.get(cv.name)

            if raw is None:
                if cv.null_policy == "nullForbidden":
                    where = instance.name if instance else "<design>"
                    raise ConfigurationError(
                        f"{where}: cache variable {cv.name} is nullForbidden but the "
                        "configuration provides no value"
                    )
                return ua.DataValue(
                    ua.Variant(None, ua.VariantType.Null),
                    ua.StatusCode(ua.StatusCodes.Good),
                )
            value = oracle.parse_design_value(raw, cv.data_type)
            variant = oracle.make_variant(value, cv.data_type, cv.is_array)
            return ua.DataValue(variant, ua.StatusCode(ua.StatusCodes.Good))

        raise DesignError(f"cache variable {cv.name}: unsupported initializeWith "
                          f"{cv.initialize_with!r}")

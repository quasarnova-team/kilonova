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

from kilonova import oracle
from kilonova.config import Instance
from kilonova.design import (
    CacheVariable,
    ConfigEntry,
    Design,
    Method,
    MethodArgument,
    QuasarClass,
    SourceVariable,
)
from kilonova.errors import ConfigurationError, DesignError
from kilonova.objects import QuasarObject

_log = logging.getLogger(__name__)

FIRST_TYPE_ID = 1000


async def _not_implemented_method(parent, *args):
    return ua.StatusCode(ua.StatusCodes.BadNotImplemented)


async def blank_description(ua_server, node) -> None:
    """C++ quasar serves null Description; asyncua auto-fills the browse name."""
    await ua_server.write_attribute_value(
        node.nodeid,
        ua.DataValue(ua.Variant(ua.LocalizedText(None), ua.VariantType.LocalizedText)),
        ua.AttributeIds.Description,
    )


def _check_array_bounds(bounds: tuple[int | None, int | None], count: int, where: str) -> None:
    """d:array minimumSize/maximumSize, enforced like the generated Configuration.xsd."""
    low, high = bounds
    if low is not None and count < low:
        raise ConfigurationError(f"{where}: array has {count} value(s), minimumSize is {low}")
    if high is not None and count > high:
        raise ConfigurationError(f"{where}: array has {count} value(s), maximumSize is {high}")


def _check_cardinality(relations, child_class_names: list[str], where: str) -> None:
    """Enforce hasobjects minOccurs/maxOccurs, as quasar's Configuration.xsd does."""
    for rel in relations:
        if rel.instantiate_using != "configuration":
            continue
        count = child_class_names.count(rel.class_name)
        if count < rel.min_occurs:
            raise ConfigurationError(
                f"{where}: needs at least {rel.min_occurs} <{rel.class_name}> "
                f"instance(s), got {count}"
            )
        if rel.max_occurs is not None and count > rel.max_occurs:
            raise ConfigurationError(
                f"{where}: allows at most {rel.max_occurs} <{rel.class_name}> "
                f"instance(s), got {count}"
            )


class AddressSpaceBuilder:
    """Creates types and instances for one Design inside one asyncua server."""

    def __init__(
        self,
        ua_server: asyncua.Server,
        design: Design,
        namespace_index: int,
        method_dispatcher_factory=None,
        calculated_engine=None,
    ):
        self._server = ua_server
        self._design = design
        self._ns = namespace_index
        self._make_dispatcher = method_dispatcher_factory
        self._calculated = calculated_engine
        self._type_nodes: dict[str, Node] = {}
        #: All instantiated objects keyed by their dotted string address.
        self.objects: dict[str, QuasarObject] = {}
        #: Source variable specs keyed by full dotted address.
        self.source_variables: dict[str, SourceVariable] = {}
        #: Full addresses of cache variables with addressSpaceWrite="delegated".
        self.delegated_cache_variables: set[str] = set()

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
        _check_cardinality(
            self._design.root_has_objects,
            [instance.class_name for instance in instances],
            where="configuration root",
        )
        for instance in instances:
            await self._instantiate(instance, objects_folder, parent_address=None)

    async def _instantiate(
        self, instance: Instance, parent_node: Node, parent_address: str | None
    ) -> QuasarObject:
        klass = self._design.classes[instance.class_name]
        if klass.calculated_variables:
            raise DesignError(
                f"class {klass.name}: Design-level calculated variables are not supported"
                " yet — declare them in the configuration instead"
            )
        address = instance.name if parent_address is None else f"{parent_address}.{instance.name}"
        node_id = ua.NodeId(address, self._ns)
        browse_name = ua.QualifiedName(instance.name, self._ns)
        _log.debug("instantiating %s %r", klass.name, address)

        if klass.single_variable_node and klass.methods:
            method = klass.methods[0]
            callback = (
                self._make_dispatcher(parent_address or "", method)
                if self._make_dispatcher is not None
                else _not_implemented_method
            )
            node = await parent_node.add_method(node_id, browse_name, callback)
            quasar_object = QuasarObject(self._server, klass, node, address)
        elif klass.single_variable_node and klass.source_variables:
            sv = klass.source_variables[0]
            node = await self._add_source_variable_node(
                parent_node, node_id, browse_name, address, sv
            )
            quasar_object = QuasarObject(self._server, klass, node, address)
            quasar_object.source_variables[sv.name] = node
        elif klass.single_variable_node:
            node = await self._add_single_variable_node(
                parent_node, node_id, browse_name, klass, instance
            )
            quasar_object = QuasarObject(self._server, klass, node, address)
            quasar_object.cache_variables[klass.the_single_variable.name] = node
        else:
            node = await parent_node.add_object(
                node_id, browse_name, objecttype=self._type_nodes[klass.name].nodeid
            )
            await blank_description(self._server, node)
            quasar_object = QuasarObject(self._server, klass, node, address)
            for cv in klass.cache_variables:
                var_node = await self._add_cache_variable(node, address, cv, instance)
                quasar_object.cache_variables[cv.name] = var_node
                if cv.address_space_write == "delegated":
                    self.delegated_cache_variables.add(f"{address}.{cv.name}")
            for sv in klass.source_variables:
                sv_node = await self._add_source_variable(node, address, sv)
                quasar_object.source_variables[sv.name] = sv_node
            for entry in klass.config_entries:
                await self._add_config_entry(node, address, entry, instance)
            for method in klass.methods:
                await self._add_method(node, address, method)

        self.objects[address] = quasar_object
        _check_cardinality(
            klass.has_objects,
            [child.class_name for child in instance.children],
            where=f"<{klass.name} name={instance.name!r}>",
        )

        if self._calculated is not None:
            for fv in instance.free_variables:
                await self._calculated.add_free_variable(
                    node, address, fv.name, fv.data_type, fv.initial_value,
                    fv.access_level,
                )
            for calc in instance.calculated_variables:
                await self._calculated.add_calculated_variable(
                    node, address, calc.name, calc.formula,
                    calc.initial_value, calc.is_boolean, calc.status_formula,
                )

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
        klass: QuasarClass, instance: Instance,
    ) -> Node:
        """singleVariableNode classes collapse to one variable named as the instance."""
        cv = klass.the_single_variable
        data_value = self._initial_data_value(cv, instance)
        node = await parent_node.add_variable(
            node_id, browse_name, data_value.Value, datatype=self._data_type_attribute(cv)
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
            datatype=self._data_type_attribute(cv),
        )
        await self._finalize_variable(node, cv, data_value)
        return node

    @staticmethod
    def _data_type_attribute(cv: CacheVariable) -> ua.NodeId:
        """C++ quasar sets the concrete DataType only for nullForbidden variables;
        nullAllowed ones keep BaseDataType so null writes stay legal."""
        if cv.null_policy == "nullForbidden":
            return oracle.data_type_node_id(cv.data_type)
        return oracle.BASE_DATA_TYPE

    async def _add_source_variable(
        self, object_node: Node, parent_address: str, sv: SourceVariable
    ) -> Node:
        address = f"{parent_address}.{sv.name}"
        return await self._add_source_variable_node(
            object_node, ua.NodeId(address, self._ns),
            ua.QualifiedName(sv.name, self._ns), address, sv,
        )

    async def _add_source_variable_node(
        self, parent_node: Node, node_id: ua.NodeId, browse_name: ua.QualifiedName,
        address: str, sv: SourceVariable,
    ) -> Node:
        """Source variables delegate reads/writes to device logic; until the first
        interaction they hold a null value with BadWaitingForInitialData."""
        initial = ua.DataValue(
            ua.Variant(None, ua.VariantType.Null),
            ua.StatusCode(ua.StatusCodes.BadWaitingForInitialData),
        )
        node = await parent_node.add_variable(
            node_id,
            browse_name,
            initial.Value,
            # source variables always expose the concrete design type (per oracle)
            datatype=oracle.data_type_node_id(sv.data_type),
        )
        await self._write_value_rank(node, self._value_rank(sv.is_array, sv.data_type))
        access = (1 if sv.is_readable else 0) | (2 if sv.is_writable else 0)
        for attribute in (ua.AttributeIds.AccessLevel, ua.AttributeIds.UserAccessLevel):
            await self._server.write_attribute_value(
                node.nodeid,
                ua.DataValue(ua.Variant(access, ua.VariantType.Byte)),
                attribute,
            )
        await self._server.write_attribute_value(node.nodeid, initial)
        await blank_description(self._server, node)
        self.source_variables[address] = sv
        return node

    async def _add_config_entry(
        self, object_node: Node, parent_address: str, entry: ConfigEntry, instance: Instance
    ) -> None:
        """Scalar config entries surface as read-only properties, like C++ quasar
        exposes them; array entries stay config-only (C++ parity)."""
        if entry.is_array:
            return
        raw = instance.attributes.get(entry.name)
        if raw is None:
            raw = entry.default_value
        if raw is None:
            # C++ quasar's generated Configuration.xsd marks entries without a
            # defaultValue as required - an omitted attribute fails config load
            raise ConfigurationError(
                f"{instance.name}: config entry {entry.name!r} is required "
                "(no defaultValue in the Design) but missing from the configuration"
            )
        try:
            oracle.check_restrictions(raw, entry.restrictions)
            value = oracle.parse_design_value(raw, entry.data_type)
        except ValueError as exc:
            raise ConfigurationError(f"{instance.name}.{entry.name}: {exc}") from exc
        variant = oracle.make_variant(value, entry.data_type, is_array=False)
        node = await object_node.add_property(
            ua.NodeId(f"{parent_address}.{entry.name}", self._ns),
            ua.QualifiedName(entry.name, self._ns),
            variant,
            datatype=oracle.data_type_node_id(entry.data_type),
        )
        await self._write_value_rank(node, self._value_rank(False, entry.data_type))
        await blank_description(self._server, node)

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
        await blank_description(self._server, method_node)
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
                # C++ argument scalars are always -1 (no UaVariant special case)
                ValueRank=1 if arg.is_array else -1,
                ArrayDimensions=[],
                # C++ serves the argument name as its description
                Description=ua.LocalizedText(arg.name),
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
        await blank_description(self._server, node)
        if cv.is_array:
            # C++ quasar sets a one-element ArrayDimensions on every array variable
            await self._server.write_attribute_value(
                node.nodeid,
                ua.DataValue(ua.Variant([0], ua.VariantType.UInt32)),
                ua.AttributeIds.ArrayDimensions,
            )
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
            where = instance.name if instance is not None else "<design>"
            try:
                if cv.is_array:
                    if instance is not None and cv.name in instance.array_values:
                        raw_values = instance.array_values[cv.name]
                        _check_array_bounds(cv.array_bounds, len(raw_values),
                                            f"{where}.{cv.name}")
                        for raw_element in raw_values:
                            oracle.check_restrictions(raw_element, cv.restrictions)
                        values = oracle.parse_design_array(raw_values, cv.data_type)
                        variant = oracle.make_variant(values, cv.data_type, is_array=True)
                        return ua.DataValue(variant, ua.StatusCode(ua.StatusCodes.Good))
                    raw = None
                else:
                    raw = instance.attributes.get(cv.name) if instance is not None else None
                    if raw is None:
                        raw = cv.default_config_initializer_value
                    if raw is not None:
                        oracle.check_restrictions(raw, cv.restrictions)

                if raw is None:
                    if not cv.is_array and instance is not None:
                        # C++ parity: the generated Configuration.xsd marks scalar
                        # config-initialized cache variables without a
                        # defaultConfigInitializerValue as required
                        raise ConfigurationError(
                            f"{where}: cache variable {cv.name} is required by the "
                            "configuration schema but missing (no "
                            "defaultConfigInitializerValue in the Design)"
                        )
                    return ua.DataValue(
                        ua.Variant(None, ua.VariantType.Null),
                        ua.StatusCode(ua.StatusCodes.Good),
                    )
                value = oracle.parse_design_value(raw, cv.data_type)
                variant = oracle.make_variant(value, cv.data_type, cv.is_array)
            except ValueError as exc:
                raise ConfigurationError(f"{where}.{cv.name}: {exc}") from exc
            return ua.DataValue(variant, ua.StatusCode(ua.StatusCodes.Good))

        raise DesignError(f"cache variable {cv.name}: unsupported initializeWith "
                          f"{cv.initialize_with!r}")

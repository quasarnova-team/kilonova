"""The microquasar server: a quasar Design served over OPC UA, pure Python."""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from pathlib import Path

import asyncua
from asyncua import ua
from asyncua.common.callback import CallbackType

from microquasar import oracle
from microquasar.address_space import AddressSpaceBuilder
from microquasar.calculated import CalculatedVariablesEngine
from microquasar.config import Configuration, load_config
from microquasar.design import Design, Method
from microquasar.errors import MicroquasarError
from microquasar.objects import QuasarObject

_log = logging.getLogger(__name__)

#: quasar servers expose their design namespace at index 2.
QUASAR_NAMESPACE_INDEX = 2
DEFAULT_ENDPOINT = "opc.tcp://0.0.0.0:4841/"


class Server:
    """An OPC UA server serving a quasar Design.

    Usage::

        server = Server("Design.xml", config_path="config.xml")
        async with server:
            await server.objects["sca1"].setOnline(1)
    """

    def __init__(
        self,
        design_path: str | Path,
        config_path: str | Path | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        namespace_uri: str = "urn:cern:quasar:opcua",
    ) -> None:
        self._design_path = Path(design_path)
        self._config_path = Path(config_path) if config_path else None
        self._endpoint = endpoint
        self._namespace_uri = namespace_uri
        self.design: Design | None = None
        self.ua_server: asyncua.Server | None = None
        self.objects: dict[str, QuasarObject] = {}
        self._method_handlers: dict[str, object] = {}
        self._read_handlers: dict[str, object] = {}
        self._write_handlers: dict[str, object] = {}
        self._source_specs: dict[str, object] = {}
        self._delegated_addresses: set[str] = set()
        self._source_locks: dict[str, asyncio.Lock] = {}
        self._initialized = False

    def method(self, address: str):
        """Register an async handler for a method node, by dotted address.

        Usage::

            @server.method("sca1.reset")
            async def reset(obj):        # obj is the owning QuasarObject
                ...
            @server.method("sca1.scale")
            async def scale(obj, factor):
                return factor * 2.0      # mapped to the Design's return values

        Registration works before or after ``start()``; unregistered methods
        answer ``BadNotImplemented``.
        """

        def decorator(handler):
            self._method_handlers[address] = handler
            return handler

        return decorator

    def read(self, address: str):
        """Register an async read handler for a source variable, by dotted address.

        The handler runs *inside* the client's read transaction (quasar's
        synchronous read mode)::

            @server.read("sca1.adc")
            async def read_adc(obj):
                return await hardware.read_adc()          # value, or
                # return value, ua.StatusCodes.Good        # (value, status), or
                # return ua.DataValue(...)                 # full control
        """

        def decorator(handler):
            self._read_handlers[address] = handler
            return handler

        return decorator

    def write(self, address: str):
        """Register an async write handler for a source variable or a
        ``addressSpaceWrite="delegated"`` cache variable.

        The handler runs before the value is stored; raise
        ``ua.UaStatusCodeError`` to refuse the write with that status::

            @server.write("sca1.dac")
            async def write_dac(obj, value):
                if not 0 <= value <= 10:
                    raise ua.UaStatusCodeError(ua.StatusCodes.BadOutOfRange)
                await hardware.write_dac(value)
        """

        def decorator(handler):
            self._write_handlers[address] = handler
            return handler

        return decorator

    def _string_address(self, node_id: ua.NodeId) -> str | None:
        if node_id.NamespaceIndex == QUASAR_NAMESPACE_INDEX and isinstance(
            node_id.Identifier, str
        ):
            return node_id.Identifier
        return None

    async def _on_pre_read(self, event, _dispatcher=None) -> None:
        """asyncua PreRead callback: refresh source variables through device logic
        before the read transaction answers (quasar synchronous read semantics)."""
        params = event.request_params
        if params is None or not params.NodesToRead:
            return
        refreshed = set()
        for read_value in params.NodesToRead:
            if read_value.AttributeId != ua.AttributeIds.Value:
                continue
            address = self._string_address(read_value.NodeId)
            if not address or address in refreshed or address not in self._source_specs:
                continue
            handler = self._read_handlers.get(address)
            if handler is None:
                continue
            refreshed.add(address)
            await self._refresh_source_variable(address, handler)

    async def _refresh_source_variable(self, address: str, handler) -> None:
        lock = self._source_locks.setdefault(address, asyncio.Lock())
        async with lock:
            spec = self._source_specs[address]
            owner = self.objects[address.rsplit(".", 1)[0]]
            now = datetime.now(timezone.utc)
            try:
                result = handler(owner)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, ua.DataValue):
                    data_value = result
                else:
                    if (
                        isinstance(result, tuple)
                        and len(result) == 2
                        and isinstance(result[1], int)
                    ):
                        value, status = result
                    else:
                        value, status = result, ua.StatusCodes.Good
                    data_value = ua.DataValue(
                        oracle.make_variant(value, spec.data_type, spec.is_array),
                        ua.StatusCode(status),
                        SourceTimestamp=now,
                    )
            except ua.UaStatusCodeError as exc:
                data_value = ua.DataValue(
                    ua.Variant(None, ua.VariantType.Null),
                    ua.StatusCode(exc.code),
                    SourceTimestamp=now,
                )
            except Exception:
                _log.exception("source variable %s: read handler failed", address)
                data_value = ua.DataValue(
                    ua.Variant(None, ua.VariantType.Null),
                    ua.StatusCode(ua.StatusCodes.BadInternalError),
                    SourceTimestamp=now,
                )
            await self.ua_server.iserver.aspace.write_attribute_value(
                ua.NodeId(address, QUASAR_NAMESPACE_INDEX), ua.AttributeIds.Value, data_value
            )

    def _install_write_hook(self) -> None:
        """Intercept client writes to delegated/source variables so device logic
        decides the per-item status before anything is stored."""
        service = self.ua_server.iserver.attribute_service
        original_write = service.write

        async def write_one(write_value, *args, **kwargs) -> ua.StatusCode:
            params = ua.WriteParameters(NodesToWrite=[write_value])
            return (await original_write(params, *args, **kwargs))[0]

        async def write_hook(params, *args, **kwargs):
            results = []
            for write_value in params.NodesToWrite:
                address = (
                    self._string_address(write_value.NodeId)
                    if write_value.AttributeId == ua.AttributeIds.Value
                    else None
                )
                delegated = address is not None and (
                    address in self._delegated_addresses
                    or (
                        address in self._source_specs
                        and self._source_specs[address].is_writable
                    )
                )
                if not delegated:
                    results.append(await write_one(write_value, *args, **kwargs))
                    continue
                handler = self._write_handlers.get(address)
                if handler is None:
                    results.append(ua.StatusCode(ua.StatusCodes.BadNotImplemented))
                    continue
                owner = self.objects[address.rsplit(".", 1)[0]]
                raw = write_value.Value
                value = raw.Value.Value if raw is not None and raw.Value is not None else None
                try:
                    outcome = handler(owner, value)
                    if inspect.isawaitable(outcome):
                        await outcome
                except ua.UaStatusCodeError as exc:
                    results.append(ua.StatusCode(exc.code))
                    continue
                except Exception:
                    _log.exception("delegated write %s: handler failed", address)
                    results.append(ua.StatusCode(ua.StatusCodes.BadInternalError))
                    continue
                # device logic accepted: store through the normal service path
                # (type checks, timestamps, datachange notifications)
                results.append(await write_one(write_value, *args, **kwargs))
            return results

        service.write = write_hook

    def _make_method_dispatcher(self, parent_address: str, method: Method):
        method_address = f"{parent_address}.{method.name}"

        async def dispatch(_parent_nodeid, *variants):
            handler = self._method_handlers.get(method_address)
            if handler is None:
                # asyncua contract: return (not raise) a StatusCode for a clean failure
                return ua.StatusCode(ua.StatusCodes.BadNotImplemented)
            if len(variants) < len(method.arguments):
                return ua.StatusCode(ua.StatusCodes.BadArgumentsMissing)
            if len(variants) > len(method.arguments):
                return ua.StatusCode(ua.StatusCodes.BadTooManyArguments)
            arguments = [variant.Value for variant in variants]
            result = handler(self.objects[parent_address], *arguments)
            if inspect.isawaitable(result):
                result = await result
            returns = method.return_values
            if not returns:
                return []
            # a single declared return value is never unpacked, so an array-valued
            # return may be given as a tuple/list without being misread as N values
            if len(returns) == 1:
                values = (result,)
            else:
                values = result if isinstance(result, tuple) else (result,)
            if len(values) != len(returns):
                _log.error(
                    "method %s: handler returned %d value(s), design declares %d",
                    method_address, len(values), len(returns),
                )
                return ua.StatusCode(ua.StatusCodes.BadInternalError)
            return [
                oracle.make_variant(value, spec.data_type, spec.is_array)
                for value, spec in zip(values, returns, strict=True)
            ]

        return dispatch

    async def init(self) -> None:
        """Parse Design/config and build the address space (idempotent)."""
        if self._initialized:
            return
        self.design = Design.from_file(self._design_path)

        self.ua_server = asyncua.Server()
        await self.ua_server.init()
        self._allow_writes_to_base_datatype_nodes()
        self.ua_server.set_endpoint(self._endpoint)
        self.ua_server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        namespace_index = await self.ua_server.register_namespace(self._namespace_uri)
        if namespace_index != QUASAR_NAMESPACE_INDEX:
            raise MicroquasarError(
                f"expected quasar namespace at index {QUASAR_NAMESPACE_INDEX}, "
                f"got {namespace_index}"
            )

        engine = CalculatedVariablesEngine(self.ua_server, namespace_index)
        builder = AddressSpaceBuilder(
            self.ua_server,
            self.design,
            namespace_index,
            method_dispatcher_factory=self._make_method_dispatcher,
            calculated_engine=engine,
        )
        await builder.build_types()
        await builder.instantiate_root_design_objects()

        configuration = Configuration()
        if self._config_path is not None:
            configuration = load_config(self._config_path, self.design)
        for name, formula in configuration.generic_formulas.items():
            engine.register_generic_formula(name, formula)
        await builder.instantiate_from_config(configuration.instances)

        objects_folder = self.ua_server.nodes.objects
        for fv in configuration.free_variables:
            await engine.add_free_variable(
                objects_folder, "", fv.name, fv.data_type, fv.initial_value
            )
        for calc in configuration.calculated_variables:
            await engine.add_calculated_variable(objects_folder, "", calc.name, calc.formula)
        await engine.wire_and_evaluate()

        self.objects = builder.objects
        self._source_specs = builder.source_variables
        self._delegated_addresses = builder.delegated_cache_variables
        self.ua_server.subscribe_server_callback(CallbackType.PreRead, self._on_pre_read)
        self._install_write_hook()
        self._initialized = True
        _log.info(
            "microquasar: design %r, %d classes, %d objects",
            self.design.project_short_name,
            len(self.design.classes),
            len(self.objects),
        )

    def _allow_writes_to_base_datatype_nodes(self) -> None:
        """Make BaseDataType variables accept any concrete value type.

        quasar's nullAllowed cache variables carry DataType=BaseDataType, which per
        OPC UA Part 3 is a supertype of every data type — any value (and null) is a
        legal write. asyncua's heuristic (`_is_expected_variant_type`, marked FIXME
        upstream) instead demands variant type == 24 and refuses such writes, so we
        override it for this server instance only, falling back to the original
        check for every concretely-typed node.
        """
        aspace = self.ua_server.iserver.aspace
        original = aspace._is_expected_variant_type

        def base_datatype_tolerant(value, attval, node) -> bool:
            data_type_attr = node.attributes.get(ua.AttributeIds.DataType)
            if data_type_attr is not None and data_type_attr.value is not None:
                data_type = data_type_attr.value.Value
                if (
                    data_type is not None
                    and isinstance(data_type.Value, ua.NodeId)
                    and data_type.Value == ua.NodeId(ua.ObjectIds.BaseDataType)
                ):
                    return True
            return original(value, attval, node)

        aspace._is_expected_variant_type = base_datatype_tolerant

    async def start(self) -> None:
        await self.init()
        await self.ua_server.start()
        _log.info("microquasar: serving on %s", self._endpoint)

    async def stop(self) -> None:
        if self.ua_server is not None:
            await self.ua_server.stop()

    async def __aenter__(self) -> Server:
        await self.start()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.stop()

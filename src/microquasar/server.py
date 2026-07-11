"""The microquasar server: a quasar Design served over OPC UA, pure Python."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path

import asyncua
from asyncua import ua

from microquasar import oracle
from microquasar.address_space import AddressSpaceBuilder
from microquasar.config import Instance, load_config
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

    def _make_method_dispatcher(self, parent_address: str, method: Method):
        method_address = f"{parent_address}.{method.name}"

        async def dispatch(_parent_nodeid, *variants):
            handler = self._method_handlers.get(method_address)
            if handler is None:
                # asyncua contract: return (not raise) a StatusCode for a clean failure
                return ua.StatusCode(ua.StatusCodes.BadNotImplemented)
            arguments = [variant.Value for variant in variants]
            result = handler(self.objects[parent_address], *arguments)
            if inspect.isawaitable(result):
                result = await result
            returns = method.return_values
            if not returns:
                return []
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
        self.ua_server.set_endpoint(self._endpoint)
        self.ua_server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        namespace_index = await self.ua_server.register_namespace(self._namespace_uri)
        if namespace_index != QUASAR_NAMESPACE_INDEX:
            raise MicroquasarError(
                f"expected quasar namespace at index {QUASAR_NAMESPACE_INDEX}, "
                f"got {namespace_index}"
            )

        builder = AddressSpaceBuilder(
            self.ua_server,
            self.design,
            namespace_index,
            method_dispatcher_factory=self._make_method_dispatcher,
        )
        await builder.build_types()
        await builder.instantiate_root_design_objects()

        instances: list[Instance] = []
        if self._config_path is not None:
            instances = load_config(self._config_path, self.design)
        await builder.instantiate_from_config(instances)

        self.objects = builder.objects
        self._initialized = True
        _log.info(
            "microquasar: design %r, %d classes, %d objects",
            self.design.project_short_name,
            len(self.design.classes),
            len(self.objects),
        )

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

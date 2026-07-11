"""Runtime handles for instantiated quasar objects."""

from __future__ import annotations

import typing
from datetime import datetime, timezone

from asyncua import ua

from microquasar import oracle
from microquasar.design import QuasarClass

if typing.TYPE_CHECKING:
    import asyncua
    from asyncua.common.node import Node


def setter_name(cache_variable_name: str) -> str:
    """quasar C++ setter convention: online -> setOnline, myVar -> setMyVar."""
    return "set" + cache_variable_name[0].upper() + cache_variable_name[1:]


class QuasarObject:
    """A live object in the address space, with quasar-style typed setters.

    Cache variables are updated with ``await obj.set_cv("online", 3)`` or the
    generated setter ``await obj.setOnline(3)``.
    """

    def __init__(
        self,
        ua_server: asyncua.Server,
        quasar_class: QuasarClass,
        node: Node,
        address: str,
    ) -> None:
        self._ua_server = ua_server
        self.quasar_class = quasar_class
        self.node = node
        self.address = address
        self.cache_variables: dict[str, Node] = {}
        self._setters = {setter_name(cv.name): cv.name for cv in quasar_class.cache_variables}

    @property
    def nodeid(self) -> ua.NodeId:
        return self.node.nodeid

    async def set_cv(
        self,
        name: str,
        value: object,
        status: int | None = None,
        source_timestamp: datetime | None = None,
    ) -> None:
        """Write a cache variable's value (and optionally status / source timestamp)."""
        cv = self.quasar_class.cache_variable(name)
        node = self.cache_variables[name]
        variant = oracle.make_variant(value, cv.data_type, cv.is_array)
        data_value = ua.DataValue(
            variant,
            ua.StatusCode(status if status is not None else ua.StatusCodes.Good),
            SourceTimestamp=source_timestamp or datetime.now(timezone.utc),
        )
        # Server.write_attribute_value discards the address-space StatusCode, so go
        # one layer down: a refused write (e.g. null into a nullForbidden variable)
        # must raise, not silently keep the old value.
        result = await self._ua_server.iserver.aspace.write_attribute_value(
            node.nodeid, ua.AttributeIds.Value, data_value
        )
        if result is not None and not result.is_good():
            raise ua.UaStatusCodeError(result.value)

    async def get_cv(self, name: str) -> object:
        """Read a cache variable's current value (None while its status is bad)."""
        data_value = await self.cache_variables[name].read_data_value(
            raise_on_bad_status=False
        )
        return data_value.Value.Value

    def __getattr__(self, name: str):
        setters = self.__dict__.get("_setters", {})
        if name in setters:
            cv_name = setters[name]
            return lambda value, **kwargs: self.set_cv(cv_name, value, **kwargs)
        raise AttributeError(f"{type(self).__name__!s} object has no attribute {name!r}")

    def __repr__(self) -> str:
        return f"QuasarObject({self.quasar_class.name}, {self.address!r})"

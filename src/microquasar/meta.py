"""The quasar StandardMetaData subtree, served live.

Same shape as C++ quasar's Meta module (the conformance oracle): Log levels,
SourceVariableThreadPool, Quasar/Server info, BuildInformation. The log-level
variables are functional — writing "DBG" to GeneralLogLevel.logLevel changes
the Python logging level of the microquasar loggers, exactly as the C++
server drives LogIt.
"""

from __future__ import annotations

import logging
import platform
from datetime import datetime, timezone

from asyncua import ua

import microquasar

_log = logging.getLogger(__name__)

#: quasar/LogIt level names -> python logging levels
LOG_LEVELS = {
    "TRC": 5, "DBG": logging.DEBUG, "INF": logging.INFO,
    "WRN": logging.WARNING, "ERR": logging.ERROR,
}

#: LogIt component -> python logger it controls (same names as the C++ oracle)
COMPONENTS = {
    "CalcVars": "microquasar.calculated",
    "AddressSpace": "microquasar.address_space",
}

_ROOT_LOGGER = "microquasar"


def _level_name(logger_name: str) -> str:
    level = logging.getLogger(logger_name).getEffectiveLevel()
    for name, value in LOG_LEVELS.items():
        if value == level:
            return name
    return "INF"


async def build_standard_meta_data(
    ua_server, namespace_index: int,
    general_log_level: str | None = None,
    component_log_levels: dict[str, str] | None = None,
) -> None:
    ns = namespace_index
    string_t = ua.NodeId(ua.VariantType.String.value)
    uint32_t = ua.NodeId(ua.VariantType.UInt32.value)

    async def add_object(parent, address: str, name: str):
        return await parent.add_object(ua.NodeId(address, ns), ua.QualifiedName(name, ns))

    async def add_var(parent, address, name, value, datatype, writable=False):
        node = await parent.add_variable(
            ua.NodeId(address, ns), ua.QualifiedName(name, ns),
            ua.Variant(value, ua.VariantType.String if datatype is string_t
                       else ua.VariantType.UInt32),
            datatype=datatype,
        )
        if writable:
            await node.set_writable(True)
        return node

    for name, level in (component_log_levels or {}).items():
        if name in COMPONENTS and level in LOG_LEVELS:
            logging.getLogger(COMPONENTS[name]).setLevel(LOG_LEVELS[level])
    if general_log_level in LOG_LEVELS:
        logging.getLogger(_ROOT_LOGGER).setLevel(LOG_LEVELS[general_log_level])

    objects = ua_server.nodes.objects
    smd = await add_object(objects, "StandardMetaData", "StandardMetaData")

    log_obj = await add_object(smd, "StandardMetaData.Log", "Log")
    general = await add_object(log_obj, "StandardMetaData.Log.GeneralLogLevel",
                               "GeneralLogLevel")
    await _add_log_level_var(
        ua_server, general, "StandardMetaData.Log.GeneralLogLevel.logLevel",
        ns, _ROOT_LOGGER, add_var, string_t)

    components = await add_object(log_obj, "StandardMetaData.Log.ComponentLogLevels",
                                  "ComponentLogLevels")
    for component, logger_name in COMPONENTS.items():
        address = f"StandardMetaData.Log.ComponentLogLevels.{component}"
        component_obj = await add_object(components, address, component)
        await _add_log_level_var(ua_server, component_obj, f"{address}.logLevel",
                                 ns, logger_name, add_var, string_t)

    pool = await add_object(smd, "StandardMetaData.SourceVariableThreadPool",
                            "SourceVariableThreadPool")
    for var in ("minThreads", "maxThreads"):
        # asyncio has no source-variable thread pool: served as 0
        await add_var(pool, f"StandardMetaData.SourceVariableThreadPool.{var}",
                      var, 0, uint32_t)

    quasar_obj = await add_object(smd, "StandardMetaData.Quasar", "Quasar")
    await add_var(quasar_obj, "StandardMetaData.Quasar.version", "version",
                  f"microquasar {microquasar.__version__}", string_t)

    server_obj = await add_object(smd, "StandardMetaData.Server", "Server")
    await add_var(server_obj, "StandardMetaData.Server.remainingCertificateValidity",
                  "remainingCertificateValidity", "N/A (NoSecurity)", string_t)

    build = await add_object(smd, "StandardMetaData.BuildInformation", "BuildInformation")
    build_info = {
        "BuildHost": platform.node(),
        "BuildTimestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "CommitID": "N/A (pure python, no build)",
        "ToolkitLibs": "asyncua",
    }
    for name, value in build_info.items():
        await add_var(build, f"StandardMetaData.BuildInformation.{name}", name,
                      value, string_t)


async def _add_log_level_var(ua_server, parent, address, ns, logger_name, add_var,
                             string_t) -> None:
    node = await add_var(parent, address, "logLevel", _level_name(logger_name),
                         string_t, writable=True)

    async def on_change(_handle, data_value) -> None:
        level = data_value.Value.Value
        if level in LOG_LEVELS:
            logging.getLogger(logger_name).setLevel(LOG_LEVELS[level])
            _log.info("log level of %s set to %s", logger_name, level)
        else:
            _log.warning("ignoring unknown log level %r for %s", level, logger_name)

    ua_server.iserver.aspace.add_datachange_callback(
        node.nodeid, ua.AttributeIds.Value, on_change
    )

"""v1.1 — blocking device logic: plain 'def' handlers run in the thread pool.

Effectiveness is proven by contrast: the same blocking driver call is measured
once as a plain function (offloaded — the server stays responsive) and once
inside a coroutine (blocking the loop — every other client stalls and the
watchdog names the culprit).
"""

import asyncio
import logging
import threading
import time

import pytest
from asyncua import Client, ua

from tests.test_robustness import boot

SLOW_FAST_DESIGN = (
    '<d:class name="Dev"><d:devicelogic/>'
    '<d:sourcevariable name="slow" dataType="OpcUa_Double" addressSpaceRead="synchronous"'
    ' addressSpaceWrite="forbidden" addressSpaceReadUseMutex="no"'
    ' addressSpaceWriteUseMutex="no"/>'
    '<d:sourcevariable name="fast" dataType="OpcUa_Double" addressSpaceRead="synchronous"'
    ' addressSpaceWrite="forbidden" addressSpaceReadUseMutex="no"'
    ' addressSpaceWriteUseMutex="no"/>'
    "</d:class>"
    '<d:root><d:hasobjects instantiateUsing="configuration" class="Dev"/></d:root>'
)


def node(client, path: str):
    return client.get_node(ua.NodeId(path, 2))


async def test_blocking_def_read_does_not_stall_the_server(tmp_path, caplog):
    """The headline: a 1-second blocking driver read delays its own transaction
    only — a second client's reads stay fast, and the watchdog stays quiet."""
    server, url = await boot(tmp_path, SLOW_FAST_DESIGN, '<Dev name="d1"/>')
    seen = {}

    @server.read("d1.slow")
    def read_slow(obj):  # plain def: kilonova offloads it
        seen["thread"] = threading.current_thread().name
        time.sleep(1.0)
        return 42.0

    @server.read("d1.fast")
    async def read_fast(obj):
        return 1.0

    with caplog.at_level(logging.WARNING, logger="kilonova.server"):
        async with server, Client(url=url) as c1, Client(url=url) as c2:
            slow_read = asyncio.ensure_future(node(c1, "d1.slow").read_value())
            await asyncio.sleep(0.2)  # slow read now blocked inside the driver

            fast_start = time.monotonic()
            for _ in range(5):
                assert await node(c2, "d1.fast").read_value() == 1.0
            fast_elapsed = time.monotonic() - fast_start

            assert await slow_read == pytest.approx(42.0)

    assert fast_elapsed < 0.8, f"fast reads took {fast_elapsed:.2f}s behind a blocked driver"
    assert seen["thread"].startswith("kilonova-offload")
    # a loaded CI runner may stall the loop on its own; only OUR handlers must be clean
    stalls = [r for r in caplog.records if "stalled" in r.message]
    assert not [r for r in stalls if "d1." in r.message], "offloaded handler blamed for a stall"


async def test_blocking_async_read_stalls_the_loop_and_watchdog_names_it(tmp_path, caplog):
    """The contrast: the same blocking call inside a coroutine freezes every
    client — and the watchdog reports it, naming the handler."""
    server, url = await boot(tmp_path, SLOW_FAST_DESIGN, '<Dev name="d1"/>')

    @server.read("d1.slow")
    async def read_slow(obj):  # deliberately wrong: blocks the event loop
        time.sleep(0.8)
        return 42.0

    @server.read("d1.fast")
    async def read_fast(obj):
        return 1.0

    with caplog.at_level(logging.WARNING, logger="kilonova.server"):
        async with server, Client(url=url) as c1, Client(url=url) as c2:
            # the test task itself plays "every other client": its 100ms timer
            # cannot fire while the handler blocks the loop, so its lateness
            # IS the stall every session would have seen
            t0 = time.monotonic()
            slow_read = asyncio.ensure_future(node(c1, "d1.slow").read_value())
            await asyncio.sleep(0.1)
            lateness = time.monotonic() - t0

            assert await slow_read == pytest.approx(42.0)
            assert await node(c2, "d1.fast").read_value() == 1.0  # recovered
            await asyncio.sleep(0.3)  # let the watchdog heartbeat report

    assert lateness > 0.5, f"expected the blocked loop to freeze the test task, got {lateness:.3f}s"
    stalls = [r for r in caplog.records if "stalled" in r.message]
    assert stalls, "watchdog never reported the stalled loop"
    assert any("read d1.slow" in r.message for r in stalls)


CONCURRENCY_DESIGN_TEMPLATE = (
    '<d:class name="Dev"><d:devicelogic/>'
    '<d:sourcevariable name="a" dataType="OpcUa_Double" addressSpaceRead="synchronous"'
    ' addressSpaceWrite="forbidden" addressSpaceReadUseMutex="{mutex}"'
    ' addressSpaceWriteUseMutex="no"/>'
    '<d:sourcevariable name="b" dataType="OpcUa_Double" addressSpaceRead="synchronous"'
    ' addressSpaceWrite="forbidden" addressSpaceReadUseMutex="{mutex}"'
    ' addressSpaceWriteUseMutex="no"/>'
    '<d:sourcevariable name="c" dataType="OpcUa_Double" addressSpaceRead="synchronous"'
    ' addressSpaceWrite="forbidden" addressSpaceReadUseMutex="{mutex}"'
    ' addressSpaceWriteUseMutex="no"/>'
    "</d:class>"
    '<d:root><d:hasobjects instantiateUsing="configuration" class="Dev"/></d:root>'
)


def make_counting_handlers(server, state):
    """Blocking def handlers that record how many run at once (thread-safe)."""
    guard = threading.Lock()

    def make(name):
        def read(obj):
            with guard:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            time.sleep(0.4)
            with guard:
                state["active"] -= 1
            return 1.0

        return read

    for name in ("a", "b", "c"):
        server.read(f"d1.{name}")(make(name))


async def test_one_read_request_refreshes_independent_sources_in_parallel(tmp_path):
    """Domain 'no': a single multi-node read runs all three blocked drivers at
    once in the pool — wall clock is one driver call, not three."""
    design = CONCURRENCY_DESIGN_TEMPLATE.format(mutex="no")
    server, url = await boot(tmp_path, design, '<Dev name="d1"/>')
    state = {"active": 0, "max": 0}
    make_counting_handlers(server, state)

    async with server, Client(url=url) as client:
        nodes = [node(client, f"d1.{n}") for n in ("a", "b", "c")]
        start = time.monotonic()
        values = await client.read_values(nodes)
        elapsed = time.monotonic() - start

    assert values == [1.0, 1.0, 1.0]
    assert state["max"] == 3, "blocked drivers should overlap in the pool"
    assert elapsed < 1.0, f"three 0.4s reads took {elapsed:.2f}s — not parallel"


async def test_mutex_domain_still_serializes_offloaded_reads(tmp_path):
    """of_containing_object: the Design's declared serialization survives the
    thread pool — offload must never weaken quasar mutex semantics."""
    design = CONCURRENCY_DESIGN_TEMPLATE.format(mutex="of_containing_object")
    server, url = await boot(tmp_path, design, '<Dev name="d1"/>')
    state = {"active": 0, "max": 0}
    make_counting_handlers(server, state)

    async with server, Client(url=url) as client:
        nodes = [node(client, f"d1.{n}") for n in ("a", "b", "c")]
        values = await client.read_values(nodes)

    assert values == [1.0, 1.0, 1.0]
    assert state["max"] == 1, "object domain must serialize device access"


async def test_sync_method_offloads_and_returns(tmp_path):
    """A blocking def method runs in the pool, returns its value, and leaves
    the server responsive for another session meanwhile."""
    design = (
        '<d:class name="Dev"><d:devicelogic/>'
        '<d:cachevariable name="x" dataType="OpcUa_Double" addressSpaceWrite="forbidden"'
        ' initializeWith="valueAndStatus" nullPolicy="nullAllowed"'
        ' initialStatus="OpcUa_BadWaitingForInitialData"/>'
        '<d:method name="work">'
        '<d:argument name="factor" dataType="OpcUa_Double"/>'
        '<d:returnvalue name="result" dataType="OpcUa_Double"/>'
        "</d:method>"
        "</d:class>"
        '<d:root><d:hasobjects instantiateUsing="configuration" class="Dev"/></d:root>'
    )
    server, url = await boot(tmp_path, design, '<Dev name="d1"/>')

    @server.method("d1.work")
    def work(obj, factor):  # plain def: blocking hardware transaction
        time.sleep(0.6)
        return factor * 2.0

    async with server, Client(url=url) as c1, Client(url=url) as c2:
        d1 = c1.get_node(ua.NodeId("d1", 2))
        call = asyncio.ensure_future(
            d1.call_method(ua.NodeId("d1.work", 2), ua.Variant(21.0, ua.VariantType.Double))
        )
        await asyncio.sleep(0.1)  # method now blocked inside the driver

        start = time.monotonic()
        await c2.get_node(ua.NodeId("d1.x", 2)).read_data_value(raise_on_bad_status=False)
        elapsed = time.monotonic() - start

        assert await call == pytest.approx(42.0)
    assert elapsed < 0.4, f"read behind a blocked method took {elapsed:.2f}s"


async def test_sync_write_handler_offloads(sca_server, sca_client):
    """A blocking def write handler runs in the pool and can refuse writes."""
    server, _ = sca_server
    seen = {}

    @server.write("sca1.dac")
    def write_dac(obj, value):  # plain def
        seen["thread"] = threading.current_thread().name
        if value > 10:
            raise ua.UaStatusCodeError(ua.StatusCodes.BadOutOfRange)

    dac = node(sca_client, "sca1.dac")
    await dac.write_value(ua.Variant(5.5, ua.VariantType.Double))
    assert seen["thread"].startswith("kilonova-offload")
    with pytest.raises(ua.UaStatusCodeError) as refused:
        await dac.write_value(ua.Variant(999.0, ua.VariantType.Double))
    assert refused.value.code == ua.StatusCodes.BadOutOfRange


async def test_def_read_handler_status_errors_reach_the_client(sca_server, sca_client):
    """Exceptions cross the pool boundary exactly like the async path."""
    server, _ = sca_server

    @server.read("sca1.adc")
    def read_adc(obj):
        raise ua.UaStatusCodeError(ua.StatusCodes.BadNoCommunication)

    data_value = await node(sca_client, "sca1.adc").read_data_value(raise_on_bad_status=False)
    assert data_value.StatusCode.value == ua.StatusCodes.BadNoCommunication


async def test_offload_helper_and_pool_shutdown(sca_server):
    """server.offload() runs the callable in the pool; stop() tears it down."""
    server, _ = sca_server
    name = await server.offload(lambda: threading.current_thread().name)
    assert name.startswith("kilonova-offload")
    await server.stop()
    assert server._offload is None


async def test_mixed_handler_offloads_only_the_blocking_part(sca_server, sca_client):
    """The documented mixed style: async handler, blocking part via offload."""
    server, _ = sca_server
    seen = {}

    @server.method("sca1.reset")
    async def reset(obj):
        seen["thread"] = await server.offload(lambda: threading.current_thread().name)
        await obj.setOnline(7)  # async API stays legal: we are on the loop

    sca1 = sca_client.get_node(ua.NodeId("sca1", 2))
    await sca1.call_method(ua.NodeId("sca1.reset", 2))
    assert seen["thread"].startswith("kilonova-offload")
    assert await server.objects["sca1"].get_cv("online") == 7


async def test_restart_gets_a_fresh_pool_and_watchdog(tmp_path):
    """start → stop → start: the second life has a working pool and watchdog."""
    server, url = await boot(tmp_path, SLOW_FAST_DESIGN, '<Dev name="d1"/>')

    @server.read("d1.fast")
    def read_fast(obj):
        return threading.current_thread().name and 1.0

    async with server:
        pass
    assert server._offload is None and server._watchdog_task is None

    async with server, Client(url=url) as client:
        assert server._offload is not None and server._watchdog_task is not None
        assert await node(client, "d1.fast").read_value() == 1.0


async def test_watchdog_names_handlers_still_in_flight(tmp_path, caplog):
    """An async handler that blocks, then awaits: the watchdog wakes while it is
    still in flight and says so."""
    server, url = await boot(tmp_path, SLOW_FAST_DESIGN, '<Dev name="d1"/>')

    @server.read("d1.slow")
    async def read_slow(obj):  # deliberately wrong: blocks, then lingers
        time.sleep(0.5)
        await asyncio.sleep(0.6)
        return 1.0

    with caplog.at_level(logging.WARNING, logger="kilonova.server"):
        async with server, Client(url=url) as client:
            await node(client, "d1.slow").read_value()

    assert any(
        "still in flight: read d1.slow" in r.message
        for r in caplog.records
        if "stalled" in r.message
    )


async def test_watchdog_zero_is_rejected(tmp_path):
    from kilonova import Server

    with pytest.raises(ValueError, match="watchdog"):
        Server(tmp_path / "Design.xml", watchdog=0)

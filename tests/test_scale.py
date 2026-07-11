"""v1 scale gate: a 2000-variable server under sustained load, bounded memory."""

import asyncio
import time

try:
    import resource  # POSIX only; on Windows the memory bound is skipped
except ImportError:  # pragma: no cover
    resource = None

import pytest
from asyncua import Client, ua

from kilonova import Server
from tests.conftest import free_port

CLASSES = 1
INSTANCES = 100
VARS_PER_INSTANCE = 20


def _big_design(tmp_path):
    cache_vars = "".join(
        f'<d:cachevariable name="v{i}" dataType="OpcUa_Double" addressSpaceWrite="regular"'
        f' initializeWith="valueAndStatus" nullPolicy="nullAllowed"'
        f' initialStatus="OpcUa_BadWaitingForInitialData"/>'
        for i in range(VARS_PER_INSTANCE)
    )
    design = tmp_path / "Design.xml"
    design.write_text(
        '<d:design xmlns:d="http://cern.ch/quasar/Design" projectShortName="Scale">'
        f'<d:class name="Node"><d:devicelogic/>{cache_vars}</d:class>'
        '<d:root><d:hasobjects instantiateUsing="configuration" class="Node"/></d:root>'
        "</d:design>"
    )
    config = tmp_path / "config.xml"
    config.write_text(
        '<configuration xmlns="http://cern.ch/quasar/Configuration">'
        + "".join(f'<Node name="n{i}"/>' for i in range(INSTANCES))
        + "</configuration>"
    )
    return design, config


@pytest.mark.slow
async def test_two_thousand_variables_under_load(tmp_path):
    design, config = _big_design(tmp_path)
    url = f"opc.tcp://127.0.0.1:{free_port()}/"
    server = Server(design, config_path=config, endpoint=url)

    boot_start = time.monotonic()
    async with server:
        boot_seconds = time.monotonic() - boot_start
        assert len(server.objects) == INSTANCES
        rss_before = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                      if resource else 0)

        async with Client(url=url) as client:
            # every variable resolvable through the client
            nodes = [
                client.get_node(ua.NodeId(f"n{i}.v{j}", 2))
                for i in range(0, INSTANCES, 10)
                for j in range(VARS_PER_INSTANCE)
            ]
            values = await client.read_values(nodes)
            assert len(values) == len(nodes)

            # sustained device-side churn with a client subscription watching
            class Recorder:
                def __init__(self):
                    self.count = 0

                def datachange_notification(self, node, value, data):
                    self.count += 1

            recorder = Recorder()
            subscription = await client.create_subscription(100, recorder)
            await subscription.subscribe_data_change(
                [client.get_node(ua.NodeId(f"n0.v{j}", 2)) for j in range(10)]
            )

            writes = 0
            churn_start = time.monotonic()
            while time.monotonic() - churn_start < 15:
                for i in range(0, INSTANCES, 5):
                    obj = server.objects[f"n{i}"]
                    await obj.set_cv(f"v{writes % VARS_PER_INSTANCE}", float(writes))
                    writes += 1
                await asyncio.sleep(0)
            await asyncio.sleep(0.5)
            await subscription.delete()

        rss_after = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                     if resource else 0)
        growth_mb = (rss_after - rss_before) / (1024 * 1024)

    assert writes > 2000, f"only {writes} writes in the window"
    assert recorder.count > 0, "subscription never fired under load"
    assert growth_mb < 200, f"memory grew {growth_mb:.0f} MB during churn"
    assert boot_seconds < 60, f"boot took {boot_seconds:.1f}s"

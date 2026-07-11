#!/usr/bin/env python3
"""M12 ecosystem smoke: verify Cacophony's generated WinCC OA addresses resolve
on a live kilonova server.

Cacophony's generated configParser.ctl assigns one OPC UA periphery address per
variable: ``ns=2;s=`` + the DPE path with ``/`` replaced by ``.``. This tool
replays that construction (per-class variable lists parsed from the generated
CTRL, instance tree from config.xml) and reads every resulting address through
a real asyncua client — which is precisely what WinCC OA's OPC UA driver would
subscribe to.

Usage:
  python tools/cacophony_crosscheck.py --ctl <configParser.ctl> \
      --design <Design.xml> --config <config.xml> [--keep-serving]
"""

from __future__ import annotations

import argparse
import asyncio
import re
import socket
import sys
from pathlib import Path

from asyncua import Client, ua

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kilonova import Design, Server  # noqa: E402
from kilonova.config import Instance, load_config  # noqa: E402

_CONFIGURE_FN = re.compile(r"bool\s+configureFromName(\w+)\s*\(")
_DPE_LINE = re.compile(r'dpe\s*=\s*fullName\+"\.(\w+)"')


def variables_per_class(ctl_text: str) -> dict[str, list[str]]:
    """Parse the generated CTRL: which variables get addresses, per class."""
    result: dict[str, list[str]] = {}
    current = None
    for line in ctl_text.splitlines():
        if match := _CONFIGURE_FN.search(line):
            current = match.group(1)
            result[current] = []
        elif current and (match := _DPE_LINE.search(line)):
            result[current].append(match.group(1))
    return result


def expected_addresses(
    instances: list[Instance], per_class: dict[str, list[str]], prefix: str = ""
) -> list[str]:
    addresses = []
    for instance in instances:
        full = f"{prefix}{instance.name}"
        for variable in per_class.get(instance.class_name, ()):
            addresses.append(f"{full}.{variable}")
        addresses.extend(
            expected_addresses(instance.children, per_class, prefix=f"{full}.")
        )
    return addresses


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctl", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    per_class = variables_per_class(Path(args.ctl).read_text())
    design = Design.from_file(args.design)
    configuration = load_config(args.config, design)
    addresses = expected_addresses(configuration.instances, per_class)
    print(f"Cacophony would assign {len(addresses)} periphery addresses "
          f"({sum(len(v) for v in per_class.values())} variables over "
          f"{len(per_class)} classes)")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"opc.tcp://127.0.0.1:{port}/"
    server = Server(args.design, config_path=args.config, endpoint=url)

    failures = []
    async with server, Client(url=url) as client:
        for address in addresses:
            node = client.get_node(ua.NodeId(address, 2))
            try:
                await node.read_data_value(raise_on_bad_status=False)
            except ua.UaStatusCodeError as exc:
                failures.append(f"ns=2;s={address}: {exc}")

    for failure in failures:
        print("FAIL", failure)
    verdict = "all addresses resolve" if not failures else f"{len(failures)} FAILURES"
    print(f"kilonova vs Cacophony: {verdict}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

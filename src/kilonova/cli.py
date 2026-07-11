"""kilonova command line: run a server or dump a running server's address space."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

import kilonova
from kilonova.dump import dump_address_space
from kilonova.server import DEFAULT_ENDPOINT, Server


async def _run(args: argparse.Namespace) -> int:
    server = Server(args.design, config_path=args.config, endpoint=args.endpoint)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        # clean OPC UA shutdown under systemd/docker stop, like C++ quasar
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop.set)
    async with server:
        print(f"kilonova: serving {args.design} on {args.endpoint} (Ctrl-C to stop)")
        await stop.wait()
        print("kilonova: shutting down")
    return 0


async def _dump(args: argparse.Namespace) -> int:
    tree = await dump_address_space(args.endpoint)
    tree.write(args.output, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    print(f"kilonova: address space dumped to {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kilonova", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version",
                        version=f"kilonova {kilonova.__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="serve a quasar Design")
    run_parser.add_argument("--design", required=True)
    run_parser.add_argument("--config", "--config_file", dest="config")
    run_parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)

    dump_parser = sub.add_parser("dump", help="dump a running server's address space")
    dump_parser.add_argument("--endpoint", default="opc.tcp://127.0.0.1:4841/")
    dump_parser.add_argument("--output", default="dump.xml")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    handler = _run if args.command == "run" else _dump
    try:
        return asyncio.run(handler(args))
    except KeyboardInterrupt:
        print("\nkilonova: stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())

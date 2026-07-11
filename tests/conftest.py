"""Shared fixtures: real servers on ephemeral ports, read through real clients."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from asyncua import Client

from microquasar import Server

DATA = Path(__file__).parent / "data"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_server(design="Design.xml", config="config.xml") -> tuple[Server, str]:
    url = f"opc.tcp://127.0.0.1:{free_port()}/"
    server = Server(
        DATA / design,
        config_path=DATA / config if config else None,
        endpoint=url,
    )
    return server, url


@pytest.fixture
async def sca_server():
    """A running server serving the SCA demo design + config."""
    server, url = make_server()
    async with server:
        yield server, url


@pytest.fixture
async def sca_client(sca_server):
    """An OPC UA client connected to the running SCA server — the UX view."""
    _, url = sca_server
    async with Client(url=url) as client:
        yield client

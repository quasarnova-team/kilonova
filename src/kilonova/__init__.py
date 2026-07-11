"""kilonova — pure-Python OPC UA servers from quasar Design files.

A quasar in miniature: loads a quasar Design.xml + config.xml and serves the
identical address space the C++ quasar framework would, with no code generation.
"""

from kilonova.design import Design
from kilonova.server import Server

__version__ = "1.0.0"

__all__ = ["Design", "Server", "__version__"]

"""UnlimitedPipe: pipe the public internet.

Public API for connector authors::

    from unlimitedpipe import Event, Source, arg, opt
"""

from unlimitedpipe._version import __version__
from unlimitedpipe.component import Component, Operator, Output, Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import UnlimitedError
from unlimitedpipe.event import Event

__all__ = [
    "Component",
    "Context",
    "Event",
    "Operator",
    "Output",
    "Source",
    "UnlimitedError",
    "__version__",
    "arg",
    "opt",
]

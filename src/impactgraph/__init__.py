"""impactgraph — pre-merge safety net built on datagraph.

One question: *what breaks if I merge this?*  impactgraph builds (or loads) a
datagraph graph, maps the git diff onto it and reports blast radius, risk,
owners to notify and a test plan — as text, JSON, Markdown (PR comment) or
HTML — with an exit code you can gate CI on.

All of datagraph's public API is re-exported here for convenience, so
``from impactgraph import ImpactGraph, analyze_impact`` works.
"""

from datagraph import *  # noqa: F401,F403  (re-export the engine's public API)
from datagraph import __all__ as _dg_all

from .core import CheckResult, check, to_markdown

__version__ = "0.7.6"
__all__ = list(_dg_all) + ["CheckResult", "check", "to_markdown", "__version__"]

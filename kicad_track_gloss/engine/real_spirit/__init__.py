"""Clean-room post-route gloss engine.

The package intentionally depends only on the API-neutral board model and
shared exact geometry primitives.  It never imports the historical planner.
"""

from .topology import (Chain, Junction, Rail, Terminal, build_topology,
                       extract_chains)
from .planner import PlanningDeadlineExceeded, plan_selected_copper
from .recovery import localized_drc_remainder

__all__ = (
    "Chain",
    "Junction",
    "PlanningDeadlineExceeded",
    "Rail",
    "Terminal",
    "build_topology",
    "extract_chains",
    "localized_drc_remainder",
    "plan_selected_copper",
)

"""Fuse sizing: the GUI's bridge to fuse_sizing.py.

The GUI only talks to :func:`default_engine`.
"""

from fusecalc.engine.adapter import FuseSizeEngine
from fusecalc.engine.api import (
    CoordinationResult,
    FeederTapInputs,
    FuseSizeInputs,
    LatFuseInputs,
    LinkSelection,
    NodeFault,
    ProtectionEngine,
    StudyContext,
    StudyResults,
    XfmrFuseInputs,
    build_context,
)


def default_engine() -> ProtectionEngine:
    """The engine the GUI runs."""
    return FuseSizeEngine()


__all__ = [
    "CoordinationResult",
    "FeederTapInputs",
    "FuseSizeEngine",
    "FuseSizeInputs",
    "LatFuseInputs",
    "LinkSelection",
    "NodeFault",
    "ProtectionEngine",
    "StudyContext",
    "StudyResults",
    "XfmrFuseInputs",
    "build_context",
    "default_engine",
]

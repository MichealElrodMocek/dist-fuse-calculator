"""Fuse sizing: the GUI's bridge to ``fuseSize`` (fuse_sizing.py).

The GUI only talks to :func:`default_engine`.
"""

from fusecalc.engine.adapter import FuseSizeEngine, fuse_size_inputs
from fusecalc.engine.api import (
    CoordinationResult,
    FuseSizeInputs,
    LinkSelection,
    NodeFault,
    ProtectionEngine,
    StudyContext,
    StudyResults,
    build_context,
)


def default_engine() -> ProtectionEngine:
    """The engine the GUI runs."""
    return FuseSizeEngine()


__all__ = [
    "CoordinationResult",
    "FuseSizeEngine",
    "FuseSizeInputs",
    "LinkSelection",
    "NodeFault",
    "ProtectionEngine",
    "StudyContext",
    "StudyResults",
    "build_context",
    "default_engine",
    "fuse_size_inputs",
]

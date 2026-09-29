"""Protection engine: fault study, link selection, coordination checks.

The GUI only talks to :func:`default_engine`. Point it at the real
implementation once it exists; everything else keeps working.
"""

from fusecalc.engine.api import (
    CoordinationResult,
    LinkSelection,
    NodeFault,
    ProtectionEngine,
    StudyContext,
    StudyResults,
    build_context,
)
from fusecalc.engine.placeholder import PlaceholderEngine


def default_engine() -> ProtectionEngine:
    """The engine the GUI runs. Swap the placeholder for the real one here."""
    return PlaceholderEngine()


__all__ = [
    "CoordinationResult",
    "LinkSelection",
    "NodeFault",
    "PlaceholderEngine",
    "ProtectionEngine",
    "StudyContext",
    "StudyResults",
    "build_context",
    "default_engine",
]

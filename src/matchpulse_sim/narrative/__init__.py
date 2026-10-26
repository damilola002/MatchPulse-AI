"""Evidence-grounded Phase 4 narrative generation."""

from .contracts import NarrativeRequestV1, NarrativeResponseV1
from .claims import prepare_narrative_request
from .errors import NarrativeError
from .service import NarrativeService

__all__ = [
    "NarrativeError",
    "NarrativeRequestV1",
    "NarrativeResponseV1",
    "NarrativeService",
    "prepare_narrative_request",
]

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ApiProblem(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] | None = None


class MatchNotFound(Exception):
    pass

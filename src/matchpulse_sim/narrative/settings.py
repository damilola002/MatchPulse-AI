"""Fail-closed provider configuration and conservative resource ceilings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .errors import NarrativeError


@dataclass(frozen=True)
class NarrativeLimits:
    max_selected_insights: int = 10
    max_approved_claims: int = 20
    max_request_bytes: int = 256 * 1024
    max_response_bytes: int = 64 * 1024
    max_output_tokens: int = 512
    max_concurrent_generations: int = 4
    retry_delay_seconds: float = 0.25
    attempt_timeout_seconds: float = 15.0
    total_timeout_seconds: float = 31.0

    def __post_init__(self) -> None:
        ceilings = {
            "max_selected_insights": 10,
            "max_approved_claims": 20,
            "max_request_bytes": 256 * 1024,
            "max_response_bytes": 64 * 1024,
            "max_output_tokens": 512,
            "max_concurrent_generations": 4,
            "retry_delay_seconds": 0.25,
            "attempt_timeout_seconds": 15.0,
            "total_timeout_seconds": 31.0,
        }
        for name, maximum in ceilings.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value > maximum:
                raise NarrativeError(
                    "invalid_narrative_configuration",
                    "narrative limit configuration is outside allowed bounds",
                )
        integer_fields = set(ceilings) - {
            "retry_delay_seconds",
            "attempt_timeout_seconds",
            "total_timeout_seconds",
        }
        if any(getattr(self, name) < 1 for name in integer_fields) or any(
            getattr(self, name) < (0 if name == "retry_delay_seconds" else 0.001)
            for name in ("retry_delay_seconds", "attempt_timeout_seconds", "total_timeout_seconds")
        ):
            raise NarrativeError(
                "invalid_narrative_configuration",
                "narrative limit configuration is outside allowed bounds",
            )

    @classmethod
    def from_env(cls) -> "NarrativeLimits":
        integer_fields = {
            "MATCHPULSE_NARRATIVE_MAX_INSIGHTS": ("max_selected_insights", 1, 10),
            "MATCHPULSE_NARRATIVE_MAX_CLAIMS": ("max_approved_claims", 1, 20),
            "MATCHPULSE_NARRATIVE_MAX_REQUEST_BYTES": ("max_request_bytes", 1024, 256 * 1024),
            "MATCHPULSE_NARRATIVE_MAX_RESPONSE_BYTES": ("max_response_bytes", 1024, 64 * 1024),
            "MATCHPULSE_NARRATIVE_MAX_OUTPUT_TOKENS": ("max_output_tokens", 32, 512),
            "MATCHPULSE_NARRATIVE_MAX_CONCURRENCY": ("max_concurrent_generations", 1, 4),
        }
        values: dict[str, int] = {}
        for env_name, (field_name, minimum, maximum) in integer_fields.items():
            raw = os.environ.get(env_name)
            if raw is None or not raw.strip():
                continue
            try:
                value = int(raw)
            except ValueError as exc:
                raise NarrativeError("invalid_narrative_configuration", "narrative limit configuration is invalid") from exc
            if not minimum <= value <= maximum:
                raise NarrativeError("invalid_narrative_configuration", "narrative limit configuration is outside allowed bounds")
            values[field_name] = value
        return cls(**values)


@dataclass(frozen=True)
class AzureOpenAIConfig:
    endpoint: str
    deployment: str
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        endpoint = os.environ.get("MATCHPULSE_AZURE_OPENAI_ENDPOINT", "").strip()
        deployment = os.environ.get("MATCHPULSE_AZURE_OPENAI_DEPLOYMENT", "").strip()
        api_key = os.environ.get("MATCHPULSE_AZURE_OPENAI_API_KEY", "").strip()
        if not endpoint or not deployment or not api_key:
            raise NarrativeError("narrative_provider_not_configured", "Azure narrative provider configuration is incomplete")
        return cls(endpoint=endpoint, deployment=deployment, api_key=api_key)

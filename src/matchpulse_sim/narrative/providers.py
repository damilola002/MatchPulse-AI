"""Provider-neutral protocol and deterministic local provider."""

from __future__ import annotations

from typing import Any, Protocol

from .rendering import approved_phrases


class NarrativeProvider(Protocol):
    provider_name: str
    model_name: str

    async def generate(self, prompt: dict[str, Any]) -> dict[str, Any]: ...


class DeterministicFakeProvider:
    provider_name = "deterministic-fake"
    model_name = "fake-v1"

    async def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        claims = prompt["request"]["claims"]
        return {
            "blocks": [
                {"claim_id": claim["claim_id"], "text": approved_phrases(claim)["direct"]}
                for claim in claims
            ]
        }

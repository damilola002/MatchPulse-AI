"""Azure OpenAI-compatible Chat Completions adapter using the stable v1 route."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from ..serialization import canonical_json
from .contracts import ProviderSelectionV1
from .errors import ProviderFailure
from .settings import AzureOpenAIConfig, NarrativeLimits


class AzureOpenAIProvider:
    provider_name = "azure-openai"

    def __init__(
        self,
        config: AzureOpenAIConfig | None = None,
        limits: NarrativeLimits | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.config = config or AzureOpenAIConfig.from_env()
        self.limits = limits or NarrativeLimits.from_env()
        self.client = client
        self.model_name = self.config.deployment
        try:
            parsed = httpx.URL(self.config.endpoint)
        except Exception as exc:
            raise ValueError("Azure endpoint configuration is invalid") from exc
        if (
            parsed.scheme != "https"
            or not parsed.host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Azure endpoint must be an HTTPS resource root without credentials or query data")

    @classmethod
    def from_env(
        cls,
        limits: NarrativeLimits | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> "AzureOpenAIProvider":
        return cls(AzureOpenAIConfig.from_env(), limits, client=client)

    def _url(self) -> str:
        return self.config.endpoint.rstrip("/") + "/openai/v1/chat/completions"

    async def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.config.deployment,
            "messages": [
                {"role": "system", "content": prompt["instructions"]},
                {
                    "role": "user",
                    "content": canonical_json(
                        {
                            "request": prompt["request"],
                            "approved_wording": prompt["approved_wording"],
                        }
                    ),
                },
            ],
            "temperature": 0,
            "max_completion_tokens": self.limits.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "narrative_selection_v1",
                    "strict": True,
                    "schema": ProviderSelectionV1.model_json_schema(),
                },
            },
        }
        encoded = canonical_json(body).encode("utf-8")
        if len(encoded) > self.limits.max_request_bytes:
            raise ProviderFailure("request_too_large")
        headers = {"api-key": self.config.api_key, "content-type": "application/json"}
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.limits.attempt_timeout_seconds)
        try:
            async with client.stream("POST", self._url(), headers=headers, content=encoded) as response:
                status = response.status_code
                if status in (401, 403):
                    raise ProviderFailure("authentication_failed")
                if status == 429:
                    raise ProviderFailure("rate_limited", retryable=True)
                if status in (502, 503, 504):
                    raise ProviderFailure("provider_unavailable", retryable=True)
                if status >= 500:
                    raise ProviderFailure("provider_unavailable")
                if status >= 400:
                    raise ProviderFailure("provider_rejected_request")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.limits.max_response_bytes:
                        raise ProviderFailure("response_too_large")
                    chunks.append(chunk)
        except ProviderFailure:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderFailure("provider_timeout", retryable=True) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderFailure("provider_unavailable", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure("provider_unavailable") from exc
        finally:
            if own_client:
                await client.aclose()

        try:
            response_data = json.loads(b"".join(chunks))
            choice = response_data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("incomplete completion")
            content = choice["message"]["content"]
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError("completion is not an object")
            return result
        except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderFailure("invalid_provider_response") from exc

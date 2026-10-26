from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from matchpulse_sim.api.models import Base
from matchpulse_sim.api.service import ingest_events, start_match
from matchpulse_sim.generator import generate_events
from matchpulse_sim.intelligence.api import get_intelligence_page
from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures
from matchpulse_sim.narrative.azure import AzureOpenAIProvider
from matchpulse_sim.narrative.claims import prepare_narrative_request
from matchpulse_sim.narrative.contracts import (
    NarrativeRequestV1,
    ProviderSelectionV1,
)
from matchpulse_sim.narrative.errors import NarrativeError, ProviderFailure
from matchpulse_sim.narrative.providers import DeterministicFakeProvider
from matchpulse_sim.narrative.rendering import approved_phrases
from matchpulse_sim.narrative.service import NarrativeService
from matchpulse_sim.narrative.settings import AzureOpenAIConfig, NarrativeLimits


@pytest.fixture(autouse=True)
def local_intelligence_cursor_key(monkeypatch):
    """Keep SQLite narrative tests independent of any developer's local secret configuration."""
    key = base64.urlsafe_b64encode(b"phase4-narrative-test-cursor-key-material").rstrip(b"=").decode("ascii")
    monkeypatch.setenv("MATCHPULSE_INTELLIGENCE_CURSOR_KEY", key)


def _stored_match():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    events = generate_events(
        MatchConfig(seed=17, match_id="phase4-narrative-match", teams=default_fixtures(), scenario=Scenario.BALANCED)
    )
    with Session(engine) as session, session.begin():
        start_match(session, events[0])
        for start in range(1, len(events), 100):
            ingest_events(session, events[0]["match_id"], events[start : start + 100])
    return engine, events


def _request(engine, events, selected=1):
    with Session(engine) as session, session.begin():
        intelligence = get_intelligence_page(session, events[0]["match_id"], limit=100, cursor=None)
        ids = [item["insight_id"] for item in intelligence["insights"][:selected]]
        request = prepare_narrative_request(
            session,
            match_id=events[0]["match_id"],
            expected_as_of=intelligence["as_of"],
            insight_ids=ids,
        )
        return request


def test_claim_preparation_is_stable_and_resolves_only_finalized_evidence():
    engine, events = _stored_match()
    try:
        first = _request(engine, events, selected=1)
        second = _request(engine, events, selected=1)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.synthetic is True
        assert first.as_of.sequence == len(events)
        assert all(claim.synthetic and claim.evidence_event_ids for claim in first.claims)
        event_sequences = {event["event_id"]: event["sequence"] for event in events}
        assert all(
            event_sequences[event_id] <= first.as_of.sequence
            for claim in first.claims
            for event_id in claim.evidence_event_ids
        )
    finally:
        engine.dispose()


def test_claim_preparation_rejects_stale_snapshot_and_unknown_or_duplicate_insights():
    engine, events = _stored_match()
    try:
        with Session(engine) as session, session.begin():
            intelligence = get_intelligence_page(session, events[0]["match_id"], limit=100, cursor=None)
            insight_id = intelligence["insights"][0]["insight_id"]
            stale = dict(intelligence["as_of"])
            stale["sequence"] -= 1
            with pytest.raises(NarrativeError, match="no longer current") as error:
                prepare_narrative_request(
                    session, match_id=events[0]["match_id"], expected_as_of=stale, insight_ids=[insight_id]
                )
            assert error.value.code == "stale_snapshot"
            with pytest.raises(NarrativeError) as error:
                prepare_narrative_request(
                    session,
                    match_id=events[0]["match_id"],
                    expected_as_of=intelligence["as_of"],
                    insight_ids=["insight:v1:" + "0" * 64],
                )
            assert error.value.code == "unknown_insight"
            with pytest.raises(NarrativeError) as error:
                prepare_narrative_request(
                    session,
                    match_id=events[0]["match_id"],
                    expected_as_of=intelligence["as_of"],
                    insight_ids=[insight_id, insight_id],
                )
            assert error.value.code == "invalid_narrative_request"
    finally:
        engine.dispose()


def test_claims_cannot_cross_run_or_snapshot_scope():
    engine, events = _stored_match()
    try:
        request = _request(engine, events)
        serialized = request.model_dump(mode="json")
        serialized["claims"][0]["simulation_run_id"] = "another-run"
        with pytest.raises(ValidationError):
            NarrativeRequestV1.model_validate(serialized)
        serialized = request.model_dump(mode="json")
        serialized["claims"][0]["as_of"]["sequence"] -= 1
        with pytest.raises(ValidationError):
            NarrativeRequestV1.model_validate(serialized)
    finally:
        engine.dispose()


def test_empty_selection_and_selected_insight_bounds_fail_closed():
    with pytest.raises(NarrativeError) as error:
        prepare_narrative_request(None, match_id="x", expected_as_of={}, insight_ids=[])
    assert error.value.code == "empty_insight_selection"
    with pytest.raises(NarrativeError) as error:
        prepare_narrative_request(
            None,
            match_id="x",
            expected_as_of={},
            insight_ids=[f"insight:v1:{index}" for index in range(11)],
        )
    assert error.value.code == "narrative_input_limit"


def test_evidence_preparation_requires_caller_transaction():
    engine, events = _stored_match()
    try:
        with Session(engine) as session:
            with pytest.raises(NarrativeError) as error:
                prepare_narrative_request(
                    session,
                    match_id=events[0]["match_id"],
                    expected_as_of={"sequence": 1, "event_id": "x", "match_elapsed_ms": 0},
                    insight_ids=["insight:v1:" + "0" * 64],
                )
            assert error.value.code == "read_only_transaction_required"
    finally:
        engine.dispose()


def test_fake_provider_returns_versioned_blocks_with_exact_provenance():
    engine, events = _stored_match()
    try:
        request = _request(engine, events, selected=1)
        service = NarrativeService(DeterministicFakeProvider())
        response = asyncio.run(service.generate(request))
        assert response.synthetic is True
        assert response.match_id == request.match_id
        assert response.simulation_run_id == request.simulation_run_id
        assert response.as_of == request.as_of
        assert response.narrative_contract_version == "1.0.0"
        assert response.prompt_version == "narrative-prompt-v1"
        assert len(response.blocks) == len(request.claims)
        for block, claim in zip(response.blocks, request.claims, strict=True):
            assert block.claim_ids == [claim.claim_id]
            assert block.insight_ids == [claim.insight_id]
            assert block.evidence_event_ids == claim.evidence_event_ids
            assert block.text
    finally:
        engine.dispose()


def test_provider_cannot_add_text_or_unknown_claims():
    engine, events = _stored_match()
    try:
        request = _request(engine, events)

        class UnsupportedAssertionProvider:
            provider_name = "fake"
            model_name = "fake-v1"

            async def generate(self, prompt):
                return {"blocks": [{"claim_id": request.claims[0].claim_id, "text": "The away side scored three goals."}]}

        with pytest.raises(NarrativeError) as error:
            asyncio.run(NarrativeService(UnsupportedAssertionProvider()).generate(request))
        assert error.value.code == "unsupported_factual_assertion"

        class UnknownClaimProvider:
            provider_name = "fake"
            model_name = "fake-v1"

            async def generate(self, prompt):
                return {"blocks": [{"claim_id": "unapproved", "text": "unapproved wording"}]}

        with pytest.raises(NarrativeError) as error:
            asyncio.run(NarrativeService(UnknownClaimProvider()).generate(request))
        assert error.value.code == "unsupported_claim_reference"
    finally:
        engine.dispose()


def test_request_and_response_bytes_and_environment_limits_are_bounded(monkeypatch):
    engine, events = _stored_match()
    try:
        request = _request(engine, events)
        tiny = NarrativeLimits(max_request_bytes=64)
        with pytest.raises(NarrativeError) as error:
            asyncio.run(NarrativeService(DeterministicFakeProvider(), tiny).generate(request))
        assert error.value.code == "narrative_input_limit"
    finally:
        engine.dispose()
    monkeypatch.setenv("MATCHPULSE_NARRATIVE_MAX_CONCURRENCY", "5")
    with pytest.raises(NarrativeError) as error:
        NarrativeLimits.from_env()
    assert error.value.code == "invalid_narrative_configuration"
    with pytest.raises(NarrativeError) as error:
        NarrativeLimits(max_concurrent_generations=5)
    assert error.value.code == "invalid_narrative_configuration"


def test_rendered_response_budget_and_request_scope_are_enforced():
    engine, events = _stored_match()
    try:
        request = _request(engine, events)
        with pytest.raises(ValidationError):
            NarrativeRequestV1.model_validate(
                request.model_dump(mode="json") | {"match_id": "another-match"}
            )
        tiny_response = NarrativeLimits(max_response_bytes=1)
        with pytest.raises(NarrativeError) as error:
            asyncio.run(NarrativeService(DeterministicFakeProvider(), tiny_response).generate(request))
        assert error.value.code == "narrative_output_limit"
    finally:
        engine.dispose()


def test_transient_failure_retries_once_but_permanent_failure_does_not():
    engine, events = _stored_match()
    try:
        request = _request(engine, events)

        class RetryProvider:
            provider_name = "retry-test"
            model_name = "retry-v1"

            def __init__(self):
                self.calls = 0

            async def generate(self, prompt):
                self.calls += 1
                if self.calls == 1:
                    raise ProviderFailure("rate_limited", retryable=True)
                return await DeterministicFakeProvider().generate(prompt)

        retry_provider = RetryProvider()
        limits = NarrativeLimits(retry_delay_seconds=0, attempt_timeout_seconds=1, total_timeout_seconds=2)
        response = asyncio.run(NarrativeService(retry_provider, limits).generate(request))
        assert response.blocks
        assert retry_provider.calls == 2

        class PermanentProvider:
            provider_name = "permanent-test"
            model_name = "permanent-v1"
            calls = 0

            async def generate(self, prompt):
                self.calls += 1
                raise ProviderFailure("authentication_failed")

        permanent = PermanentProvider()
        with pytest.raises(NarrativeError) as error:
            asyncio.run(NarrativeService(permanent, limits).generate(request))
        assert error.value.code == "authentication_failed"
        assert permanent.calls == 1
    finally:
        engine.dispose()


def test_total_timeout_and_concurrency_limit_are_bounded():
    engine, events = _stored_match()
    try:
        request = _request(engine, events)

        class SlowProvider:
            provider_name = "slow-test"
            model_name = "slow-v1"
            active = 0
            peak = 0

            async def generate(self, prompt):
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await asyncio.sleep(0.02)
                    return await DeterministicFakeProvider().generate(prompt)
                finally:
                    self.active -= 1

        provider = SlowProvider()
        limits = NarrativeLimits(
            max_concurrent_generations=2,
            attempt_timeout_seconds=1,
            total_timeout_seconds=2,
            retry_delay_seconds=0,
        )

        async def concurrent_run():
            service = NarrativeService(provider, limits)
            return await asyncio.gather(*(service.generate(request) for _ in range(5)))

        responses = asyncio.run(concurrent_run())
        assert len(responses) == 5
        assert provider.peak == 2

        class HangingProvider:
            provider_name = "hang-test"
            model_name = "hang-v1"
            calls = 0

            async def generate(self, prompt):
                self.calls += 1
                await asyncio.sleep(1)
                return {}

        hanging = HangingProvider()
        short = NarrativeLimits(attempt_timeout_seconds=0.01, total_timeout_seconds=0.04, retry_delay_seconds=0)
        with pytest.raises(NarrativeError) as error:
            asyncio.run(NarrativeService(hanging, short).generate(request))
        assert error.value.code == "provider_timeout"
        assert hanging.calls == 2
    finally:
        engine.dispose()


def test_azure_adapter_uses_mocked_openai_v1_transport_and_secret_is_not_in_errors():
    seen = {}
    response_content = json.dumps({"blocks": [{"claim_id": "claim:v1:" + "a" * 64, "text": "Approved phrase."}]})

    def handler(request):
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": response_content}}]},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AzureOpenAIProvider(
                AzureOpenAIConfig("https://resource.example", "deployment-x", "do-not-log-this"),
                NarrativeLimits(),
                client=client,
            )
            result = await provider.generate(
                {
                    "instructions": "safe",
                    "request": {"claims": []},
                    "approved_wording": {},
                }
            )
            return result

    result = asyncio.run(run())
    assert result["blocks"][0]["claim_id"] == "claim:v1:" + "a" * 64
    assert seen["url"] == "https://resource.example/openai/v1/chat/completions"
    assert seen["api_key"] == "do-not-log-this"
    assert seen["body"]["model"] == "deployment-x"
    assert seen["body"]["max_completion_tokens"] == 512
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert json.loads(seen["body"]["messages"][1]["content"]) == {
        "request": {"claims": []},
        "approved_wording": {},
    }
    assert "do-not-log-this" not in repr(AzureOpenAIConfig("https://resource.example", "deployment-x", "do-not-log-this"))


def test_azure_service_sends_exact_approved_wording_and_rejects_provider_invention():
    engine, events = _stored_match()
    request = _request(engine, events, selected=1)
    claim = request.claims[0]
    expected_phrases = approved_phrases(claim.model_dump(mode="json"))
    seen = {}

    def handler(http_request):
        body = json.loads(http_request.content)
        seen["user_payload"] = json.loads(body["messages"][1]["content"])
        invalid_response = {
            "blocks": [{"claim_id": claim.claim_id, "text": "The away side scored three goals."}]
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(invalid_response)}}
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AzureOpenAIProvider(
                AzureOpenAIConfig("https://resource.example", "deployment-x", "mock-only-key"),
                NarrativeLimits(),
                client=client,
            )
            with pytest.raises(NarrativeError) as error:
                await NarrativeService(provider).generate(request)
            assert error.value.code == "unsupported_factual_assertion"

    try:
        asyncio.run(run())
        assert seen["user_payload"]["request"] == request.model_dump(mode="json")
        assert seen["user_payload"]["request"]["claims"][0]["evidence_event_ids"] == claim.evidence_event_ids
        assert seen["user_payload"]["approved_wording"] == {claim.claim_id: expected_phrases}
        assert set(seen["user_payload"]["approved_wording"][claim.claim_id].values()) == set(expected_phrases.values())
    finally:
        engine.dispose()


def test_azure_adapter_classifies_authentication_and_oversized_response():
    async def auth_check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
            provider = AzureOpenAIProvider(
                AzureOpenAIConfig("https://resource.example", "deployment", "private-key"), client=client
            )
            with pytest.raises(ProviderFailure) as error:
                await provider.generate({"instructions": "safe", "request": {"claims": []}, "approved_wording": {}})
            assert error.value.code == "authentication_failed"
            assert "private-key" not in str(error.value)

    asyncio.run(auth_check())

    async def large_check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 2048))
        ) as client:
            provider = AzureOpenAIProvider(
                AzureOpenAIConfig("https://resource.example", "deployment", "private-key"),
                NarrativeLimits(max_response_bytes=1024),
                client=client,
            )
            with pytest.raises(ProviderFailure) as error:
                await provider.generate({"instructions": "safe", "request": {"claims": []}, "approved_wording": {}})
            assert error.value.code == "response_too_large"

    asyncio.run(large_check())

    async def transient_statuses():
        for status in (429, 502, 503, 504):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request, status=status: httpx.Response(status))
            ) as client:
                provider = AzureOpenAIProvider(
                    AzureOpenAIConfig("https://resource.example", "deployment", "private-key"), client=client
                )
                with pytest.raises(ProviderFailure) as error:
                    await provider.generate({"instructions": "safe", "request": {"claims": []}, "approved_wording": {}})
                assert error.value.retryable is True
                assert error.value.code == ("rate_limited" if status == 429 else "provider_unavailable")

    asyncio.run(transient_statuses())


def test_contract_rejects_unknown_fields_and_wrong_language():
    bad = {
        "schema_version": 1,
        "narrative_kind": "match_insight_explanation",
        "language": "fr",
        "match_id": "m",
        "simulation_run_id": "r",
        "synthetic": True,
        "as_of": {"sequence": 1, "event_id": "r:1", "match_elapsed_ms": 1000},
        "claims": [],
        "unsupported_claim": "invented",
    }
    with pytest.raises(ValidationError):
        NarrativeRequestV1.model_validate(bad)

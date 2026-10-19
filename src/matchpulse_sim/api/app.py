from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Callable

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from ..serialization import canonical_json
from .database import ConfigurationError, application_engine, session_factory
from .errors import ApiProblem, MatchNotFound
from .models import MatchEventRecord, MatchRecord
from .schemas import (
    EventBatchRequest,
    EventPageResponse,
    IntelligenceResponse,
    IngestResponse,
    MatchStateResponse,
    StartMatchRequest,
    StartMatchResponse,
)
from .service import (
    get_event_page,
    get_state,
    ingest_events,
    replay_stored_events,
    start_match,
)
from ..intelligence.api import get_intelligence_page

MAX_REQUEST_BODY_BYTES = 1024 * 1024
MAX_SSE_CONNECTIONS = 100
SSE_POLL_SECONDS = 0.5
SSE_HEARTBEAT_SECONDS = 15.0
SSE_PAGE_SIZE = 1
MAX_LAST_EVENT_ID_LENGTH = 52  # 32 hex run ID, colon, signed PostgreSQL BIGINT sequence.
_CURSOR = re.compile(r"^([a-f0-9]{32}):([1-9][0-9]{0,18})$")


class RequestBodyLimitMiddleware:
    """Buffer only bounded API POST bodies; reject oversized chunked bodies."""

    def __init__(self, app: Any, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not scope.get("path", "").startswith("/api/matches")
        ):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        length = headers.get(b"content-length")
        if length is not None:
            try:
                if int(length) > self.max_bytes:
                    await self._too_large(scope, send)
                    return
            except ValueError:
                await JSONResponse(
                    {"error": {"code": "invalid_content_length", "message": "invalid Content-Length"}},
                    status_code=400,
                )(scope, receive, send)
                return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await self._too_large(scope, send)
                return
            body.extend(chunk)
            more_body = message.get("more_body", False)

        delivered = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _too_large(self, scope: dict[str, Any], send: Callable) -> None:
        body = b'{"error":{"code":"request_too_large","message":"request body exceeds 1 MiB"}}'
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="MatchPulse Synthetic Match API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID", "Accept"],
    )
    app.add_middleware(RequestBodyLimitMiddleware)
    app.state.engine = engine
    app.state.sessions = session_factory(engine) if engine is not None else None
    app.state.active_sse = 0

    def get_sessions() -> sessionmaker[Session]:
        if app.state.sessions is not None:
            return app.state.sessions
        if app.state.engine is None:
            app.state.engine = application_engine()
            app.state.sessions = session_factory(app.state.engine)
        return app.state.sessions

    def db() -> Any:
        sessions = get_sessions()
        with sessions() as session:
            yield session

    @app.on_event("startup")
    def verify_recovered_projections() -> None:
        # Read-only recovery check: migrations must already have been explicitly run.
        with get_sessions()() as session:
            match_ids = list(session.scalars(select(MatchRecord.match_id).order_by(MatchRecord.match_id)))
            for match_id in match_ids:
                replay_stored_events(session, match_id)

    @app.exception_handler(ApiProblem)
    async def api_problem_handler(_: Request, exc: ApiProblem) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            status_code=exc.status_code,
        )

    @app.exception_handler(MatchNotFound)
    async def missing_match_handler(_: Request, __: MatchNotFound) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "match_not_found", "message": "match was not found"}},
            status_code=404,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": [str(part) for part in error.get("loc", ())], "code": error.get("type", "invalid")}
            for error in exc.errors()
        ]
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": "request validation failed", "details": details}},
            status_code=422,
        )

    @app.exception_handler(ConfigurationError)
    async def configuration_handler(_: Request, __: ConfigurationError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "configuration_error", "message": "local database configuration is incomplete"}},
            status_code=503,
        )

    @app.exception_handler(OperationalError)
    async def database_unavailable_handler(_: Request, __: OperationalError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "database_unavailable", "message": "database is temporarily unavailable"}},
            status_code=503,
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(_: Request, __: IntegrityError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "identity_conflict", "message": "event identity conflicts with stored data"}},
            status_code=409,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(_: Request, __: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "database_error", "message": "database request could not be completed"}},
            status_code=503,
        )

    @app.post("/api/matches", response_model=StartMatchResponse)
    def create_match_endpoint(body: StartMatchRequest, session: Session = Depends(db)) -> JSONResponse:
        with session.begin():
            match, duplicate = start_match(session, body.start_event)
            result = {"state": get_state(session, match.match_id), "duplicate": duplicate}
        return JSONResponse(result, status_code=200 if duplicate else 201)

    @app.post("/api/matches/{match_id}/events", response_model=IngestResponse)
    def ingest_endpoint(match_id: str, body: EventBatchRequest, session: Session = Depends(db)) -> dict[str, Any]:
        with session.begin():
            match, accepted_count, duplicate_count = ingest_events(session, match_id, body.events)
            result = {
                "match_id": match_id,
                "simulation_run_id": match.simulation_run_id,
                "accepted_count": accepted_count,
                "duplicate_count": duplicate_count,
                "first_new_sequence": match.accepted_sequence - accepted_count + 1 if accepted_count else None,
                "last_accepted_sequence": match.accepted_sequence,
                "last_event_id": match.accepted_event_id,
                "last_finalized_sequence": match.finalized_sequence,
                "state_version": match.state_version,
                "state": get_state(session, match_id),
            }
        return result

    @app.get("/api/matches/{match_id}/state", response_model=MatchStateResponse)
    def state_endpoint(match_id: str, session: Session = Depends(db)) -> dict[str, Any]:
        return get_state(session, match_id)

    @app.get("/api/matches/{match_id}/events", response_model=EventPageResponse)
    def events_endpoint(
        match_id: str,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        return get_event_page(session, match_id, after_sequence, limit)

    @app.get(
        "/api/matches/{match_id}/intelligence",
        response_model=IntelligenceResponse,
    )
    def intelligence_endpoint(
        match_id: str,
        limit: int | None = Query(default=None, ge=1, le=100),
        cursor: str | None = Query(default=None),
        session: Session = Depends(db),
    ) -> dict[str, Any]:
        # This is a read-only transaction. The finalized watermark and its
        # immutable event prefix are captured together without locking writers.
        with session.begin():
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
            return get_intelligence_page(session, match_id, limit=limit, cursor=cursor)

    @app.get("/api/matches/{match_id}/stream")
    async def stream_endpoint(match_id: str, request: Request) -> StreamingResponse:
        def read_match_state() -> dict[str, Any]:
            with get_sessions()() as session:
                return get_state(session, match_id)

        match = await run_in_threadpool(read_match_state)
        cursor = 0
        supplied = request.headers.get("Last-Event-ID")
        if supplied:
            if len(supplied) > MAX_LAST_EVENT_ID_LENGTH:
                raise ApiProblem(400, "invalid_event_cursor", "Last-Event-ID exceeds the supported length")
            parsed = _CURSOR.fullmatch(supplied)
            if parsed is None:
                raise ApiProblem(400, "invalid_event_cursor", "Last-Event-ID must contain a run ID and positive sequence")
            run_id, sequence_text = parsed.groups()
            cursor = int(sequence_text)
            if cursor > 9_223_372_036_854_775_807:
                raise ApiProblem(400, "invalid_event_cursor", "Last-Event-ID sequence is outside the supported range")
            if run_id != match["simulation_run_id"] or cursor > match["last_finalized_sequence"]:
                raise ApiProblem(409, "invalid_event_cursor", "Last-Event-ID is not a finalized event for this match")
            def read_cursor_event() -> MatchEventRecord | None:
                with get_sessions()() as session:
                    return session.scalar(select(MatchEventRecord).where(MatchEventRecord.match_id == match_id, MatchEventRecord.sequence == cursor))

            row = await run_in_threadpool(read_cursor_event)
            if row is None or row.event_id != supplied:
                raise ApiProblem(409, "invalid_event_cursor", "Last-Event-ID does not match the stored event log")
        if app.state.active_sse >= MAX_SSE_CONNECTIONS:
            raise ApiProblem(503, "stream_capacity", "stream capacity is temporarily full")
        app.state.active_sse += 1

        async def generate() -> Any:
            nonlocal cursor
            heartbeat_at = time.monotonic() + SSE_HEARTBEAT_SECONDS
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    def poll_page() -> tuple[int, bool, list[tuple[int, str, str]]]:
                        with get_sessions()() as read_session:
                            current = read_session.get(MatchRecord, match_id)
                            if current is None:
                                return 0, True, []
                            finalized = current.finalized_sequence
                            ended = current.status == "ended"
                            rows = list(read_session.scalars(
                                select(MatchEventRecord)
                                .where(
                                    MatchEventRecord.match_id == match_id,
                                    MatchEventRecord.sequence > cursor,
                                    MatchEventRecord.sequence <= finalized,
                                )
                                .order_by(MatchEventRecord.sequence)
                                .limit(SSE_PAGE_SIZE)
                            ))
                            return finalized, ended, [
                                (row.sequence, row.event_id, canonical_json(row.payload)) for row in rows
                            ]
                    finalized, ended, rows = await run_in_threadpool(poll_page)
                    if rows:
                        for sequence, event_id, payload in rows:
                            cursor = sequence
                            yield (
                                f"id: {event_id}\nevent: match.event\ndata: {payload}\n\n"
                            )
                            if json.loads(payload).get("type") == "full_time":
                                return
                        continue
                    if ended and cursor >= finalized:
                        return
                    now = time.monotonic()
                    if now >= heartbeat_at:
                        yield ": heartbeat\n\n"
                        heartbeat_at = now + SSE_HEARTBEAT_SECONDS
                    await asyncio.sleep(SSE_POLL_SECONDS)
            finally:
                app.state.active_sse = max(0, app.state.active_sse - 1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()

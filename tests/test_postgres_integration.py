"""PostgreSQL-only locking/recovery checks; never target the development database."""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from matchpulse_sim.api.database import database_url
from matchpulse_sim.api.models import Base
from matchpulse_sim.api.service import get_state, ingest_events, replay_stored_events, start_match
from matchpulse_sim.generator import generate_events
from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures


def _test_engine():
    value = os.environ.get("MATCHPULSE_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("MATCHPULSE_TEST_DATABASE_URL is not configured; PostgreSQL integration checks blocked")
    try:
        url = make_url(value)
        configured = database_url(test=True)
        if url != configured:
            pytest.fail("refusing PostgreSQL integration tests because the configured test URL is ambiguous")
    except ValueError as exc:
        pytest.fail(str(exc))
    admin_engine = create_engine(configured, pool_pre_ping=True)
    schema = f"mp_test_{uuid4().hex}"
    engine = None
    schema_created = False
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        schema_created = True
        engine = create_engine(configured, pool_pre_ping=True, connect_args={"options": f"-c search_path={schema}"})
        Base.metadata.create_all(engine)
        return engine, admin_engine, schema
    except BaseException:
        if engine is not None:
            engine.dispose()
        try:
            if schema_created:
                with admin_engine.begin() as connection:
                    connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin_engine.dispose()
        raise


def test_concurrent_duplicate_ingestion_and_restart_replay():
    engine, admin_engine, schema = _test_engine()
    match_id = f"integration-{uuid4().hex}"
    events = generate_events(MatchConfig(seed=19, match_id=match_id, teams=default_fixtures(), scenario=Scenario.BALANCED))
    try:
        with Session(engine) as session, session.begin():
            start_match(session, events[0])
        barrier = Barrier(2)
        def submit():
            barrier.wait()
            with Session(engine) as session, session.begin():
                match, accepted, duplicates = ingest_events(session, match_id, events[1:2])
                return accepted, duplicates, match.state_version
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        assert sorted((accepted, duplicates) for accepted, duplicates, _ in results) == [(0, 1), (1, 0)]
        with Session(engine) as session:
            state = get_state(session, match_id)
            replayed = replay_stored_events(session, match_id)
            assert state["last_accepted_sequence"] == 2
            assert replayed.last_sequence == 2
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin_engine.dispose()


def test_partial_test_schema_setup_failure_cleans_only_its_schema(monkeypatch):
    from contextlib import contextmanager

    monkeypatch.setenv("POSTGRES_PASSWORD", "local-only-test-value")
    monkeypatch.setenv("POSTGRES_DB", "matchpulse")
    monkeypatch.setenv("POSTGRES_HOST_PORT", "5434")
    monkeypatch.setenv("MATCHPULSE_TEST_DATABASE_NAME", "matchpulse_test")
    monkeypatch.setenv(
        "MATCHPULSE_TEST_DATABASE_URL",
        "postgresql+psycopg://matchpulse@127.0.0.1:5434/matchpulse_test",
    )
    statements = []

    class FakeConnection:
        def exec_driver_sql(self, statement):
            statements.append(statement)

    class FakeEngine:
        @contextmanager
        def begin(self):
            yield FakeConnection()

        def dispose(self):
            pass

    engines = [FakeEngine(), FakeEngine()]
    monkeypatch.setattr(sys.modules[__name__], "create_engine", lambda *args, **kwargs: engines.pop(0))
    monkeypatch.setattr(Base.metadata, "create_all", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("setup failure")))
    with pytest.raises(RuntimeError, match="setup failure"):
        _test_engine()
    create_schema = next(statement for statement in statements if statement.startswith("CREATE SCHEMA"))
    assert statements[-1] == f'DROP SCHEMA "{create_schema.split(chr(34))[1]}" CASCADE'
    assert len([statement for statement in statements if statement.startswith("DROP SCHEMA")]) == 1

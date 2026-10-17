from __future__ import annotations

import pytest

from matchpulse_sim.api.database import ConfigurationError, database_url, migration_database_url


def _configure(monkeypatch, *, dev_name="matchpulse", test_name="matchpulse_test", test_host="127.0.0.1", test_port=5434):
    monkeypatch.setenv("POSTGRES_PASSWORD", "local-only-test-value")
    monkeypatch.setenv("POSTGRES_DB", dev_name)
    monkeypatch.setenv("POSTGRES_USER", "matchpulse")
    monkeypatch.setenv("POSTGRES_HOST_PORT", "5434")
    monkeypatch.setenv("MATCHPULSE_TEST_DATABASE_NAME", test_name)
    monkeypatch.setenv(
        "MATCHPULSE_TEST_DATABASE_URL",
        f"postgresql+psycopg://matchpulse@{test_host}:{test_port}/{test_name}",
    )


def test_database_url_requires_explicit_test_database_designation(monkeypatch):
    monkeypatch.setenv("MATCHPULSE_TEST_DATABASE_URL", "postgresql+psycopg://u@127.0.0.1:5434/anything_test")
    monkeypatch.delenv("MATCHPULSE_TEST_DATABASE_NAME", raising=False)
    with pytest.raises(ConfigurationError, match="MATCHPULSE_TEST_DATABASE_NAME"):
        database_url(test=True)


def test_database_url_rejects_same_normalized_development_target(monkeypatch):
    _configure(monkeypatch, dev_name="matchpulse_test", test_name="matchpulse_test", test_host="localhost")
    with pytest.raises(ConfigurationError, match="differ from.*development"):
        database_url(test=True)


def test_database_url_accepts_explicit_distinct_loopback_test_target(monkeypatch):
    _configure(monkeypatch)
    assert database_url(test=True).database == "matchpulse_test"


def test_database_url_fails_closed_for_blank_development_identity(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("POSTGRES_DB", " ")
    with pytest.raises(ConfigurationError, match="POSTGRES_DB must identify"):
        database_url(test=True)


def test_migration_target_must_be_explicit_and_test_migration_confirmed(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.delenv("MATCHPULSE_MIGRATION_TARGET", raising=False)
    with pytest.raises(ConfigurationError, match="explicitly be development or test"):
        migration_database_url()
    monkeypatch.setenv("MATCHPULSE_MIGRATION_TARGET", "test")
    monkeypatch.delenv("MATCHPULSE_TEST_MIGRATION_CONFIRM", raising=False)
    with pytest.raises(ConfigurationError, match="require MATCHPULSE_TEST_MIGRATION_CONFIRM"):
        migration_database_url()
    monkeypatch.setenv("MATCHPULSE_TEST_MIGRATION_CONFIRM", "matchpulse_test")
    assert migration_database_url().database == "matchpulse_test"


def test_development_migration_requires_explicit_selection(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("MATCHPULSE_MIGRATION_TARGET", "development")
    assert migration_database_url().database == "matchpulse"

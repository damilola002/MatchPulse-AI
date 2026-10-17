from __future__ import annotations

from functools import lru_cache
import ipaddress
import os

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class ConfigurationError(ValueError):
    pass


def _normalized_host(host: str | None) -> str:
    if not host:
        raise ConfigurationError("database host must be configured")
    lowered = host.lower().rstrip(".")
    if lowered == "localhost":
        return "loopback"
    try:
        address = ipaddress.ip_address(lowered)
        return "loopback" if address.is_loopback else address.compressed
    except ValueError:
        return lowered


def database_identity(url: URL) -> tuple[str, int, str]:
    if not url.database:
        raise ConfigurationError("database name must be configured")
    return (_normalized_host(url.host), url.port or 5432, url.database)


def _development_identity() -> tuple[str, int, str]:
    try:
        port = int(os.environ.get("POSTGRES_HOST_PORT", "5434"))
    except ValueError as exc:
        raise ConfigurationError("POSTGRES_HOST_PORT must be numeric") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError("POSTGRES_HOST_PORT must be between 1 and 65535")
    database = os.environ.get("POSTGRES_DB", "matchpulse").strip()
    if not database:
        raise ConfigurationError("POSTGRES_DB must identify the development database")
    return ("loopback", port, database)


def _test_database_url() -> URL:
    value = os.environ.get("MATCHPULSE_TEST_DATABASE_URL", "").strip()
    designated_name = os.environ.get("MATCHPULSE_TEST_DATABASE_NAME", "").strip()
    if not value or not designated_name:
        raise ConfigurationError(
            "MATCHPULSE_TEST_DATABASE_URL and MATCHPULSE_TEST_DATABASE_NAME must identify a dedicated test database"
        )
    from sqlalchemy.engine import make_url

    try:
        url = make_url(value)
    except Exception as exc:
        raise ConfigurationError("MATCHPULSE_TEST_DATABASE_URL is invalid") from exc
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ConfigurationError("test database URL must use PostgreSQL with psycopg")
    if _normalized_host(url.host) != "loopback":
        raise ConfigurationError("test database must use a loopback host")
    if url.database != designated_name or not designated_name.lower().endswith("_test"):
        raise ConfigurationError("test database name must match MATCHPULSE_TEST_DATABASE_NAME and end in _test")
    if database_identity(url) == _development_identity():
        raise ConfigurationError("test database target must differ from the configured development database")
    return url


def database_url(*, test: bool = False) -> URL:
    if test:
        return _test_database_url()

    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password.strip():
        raise ConfigurationError("POSTGRES_PASSWORD must be set in the untracked local .env")
    database = os.environ.get("POSTGRES_DB", "matchpulse").strip()
    username = os.environ.get("POSTGRES_USER", "matchpulse").strip()
    if not database or not username:
        raise ConfigurationError("POSTGRES_DB and POSTGRES_USER must be non-empty")
    port_text = os.environ.get("POSTGRES_HOST_PORT", "5434")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ConfigurationError("POSTGRES_HOST_PORT must be numeric") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError("POSTGRES_HOST_PORT must be between 1 and 65535")
    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host="127.0.0.1",
        port=port,
        database=database,
    )


def migration_database_url() -> URL:
    """Select an explicit Alembic target; test migrations require deliberate confirmation."""
    target = os.environ.get("MATCHPULSE_MIGRATION_TARGET", "").strip().lower()
    if target == "development":
        return database_url()
    if target != "test":
        raise ConfigurationError("MATCHPULSE_MIGRATION_TARGET must explicitly be development or test")
    if not os.environ.get("POSTGRES_PASSWORD", "").strip():
        raise ConfigurationError("POSTGRES_PASSWORD must be set before selecting a test migration target")
    url = _test_database_url()
    confirmation = os.environ.get("MATCHPULSE_TEST_MIGRATION_CONFIRM", "").strip()
    if confirmation != url.database:
        raise ConfigurationError(
            "test migrations require MATCHPULSE_TEST_MIGRATION_CONFIRM to equal the designated test database name"
        )
    return url


@lru_cache(maxsize=1)
def application_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True, pool_size=5, max_overflow=5)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

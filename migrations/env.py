from __future__ import annotations

from alembic import context
from sqlalchemy import URL, create_engine, pool, text

from matchpulse_sim.api.database import ConfigurationError, database_identity, migration_database_url
from matchpulse_sim.api.models import Base

target_url = migration_database_url()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=target_url.render_as_string(hide_password=True), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(target_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        actual_database = connection.execute(text("SELECT current_database()")).scalar_one()
        driver_info = connection.connection.driver_connection.info
        actual_identity = database_identity(
            URL.create(
                target_url.drivername,
                host=driver_info.host,
                port=int(driver_info.port),
                database=actual_database,
            )
        )
        if actual_identity != database_identity(target_url):
            raise ConfigurationError("connected PostgreSQL target does not match the explicitly selected migration target")
        # The identity SELECT above autobegins a SQLAlchemy 2.x transaction.
        # End that read-only transaction so Alembic can own and commit its DDL transaction.
        connection.rollback()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

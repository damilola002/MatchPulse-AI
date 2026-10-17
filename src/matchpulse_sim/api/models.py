from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Index,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class MatchRecord(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("match_id", "simulation_run_id", name="uq_matches_match_run"),
        UniqueConstraint("simulation_run_id", name="uq_matches_simulation_run_id"),
        CheckConstraint("accepted_sequence >= 1", name="ck_matches_accepted_sequence"),
        CheckConstraint("finalized_sequence >= 0 AND finalized_sequence <= accepted_sequence", name="ck_matches_watermarks"),
    )

    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    simulation_run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(32), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    home_team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    away_team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    period: Mapped[str | None] = mapped_column(String(16))
    match_elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    period_elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_possession: Mapped[str | None] = mapped_column(String(64))
    home_shots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    away_shots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accepted_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_match_elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finalized_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    finalized_event_id: Mapped[str | None] = mapped_column(String(64))
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    pending_checkpoint: Mapped[dict | None] = mapped_column(JSON_VALUE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=func.now())


class MatchEventRecord(Base):
    __tablename__ = "match_events"
    __table_args__ = (
        Index("ix_match_events_match_sequence", "match_id", "sequence"),
        UniqueConstraint("event_id", name="uq_match_events_event_id"),
        UniqueConstraint("match_id", "simulation_run_id", "sequence", name="uq_match_events_match_run_sequence"),
        ForeignKeyConstraint(
            ["match_id", "simulation_run_id"],
            ["matches.match_id", "matches.simulation_run_id"],
            name="fk_match_events_match_run",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    match_id: Mapped[str] = mapped_column(String(64), nullable=False)
    simulation_run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    match_elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

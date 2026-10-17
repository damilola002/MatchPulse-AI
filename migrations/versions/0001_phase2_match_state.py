"""Create the Phase 2 match projection and append-only event log."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_phase2"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "matches",
        sa.Column("match_id", sa.String(length=64), primary_key=True),
        sa.Column("simulation_run_id", sa.String(length=32), nullable=False),
        sa.Column("scenario_id", sa.String(length=32), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("generator_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("home_team_id", sa.String(length=64), nullable=False),
        sa.Column("away_team_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("match_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("period_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("current_possession", sa.String(length=64), nullable=True),
        sa.Column("home_shots", sa.Integer(), nullable=False),
        sa.Column("away_shots", sa.Integer(), nullable=False),
        sa.Column("accepted_sequence", sa.BigInteger(), nullable=False),
        sa.Column("accepted_event_id", sa.String(length=64), nullable=False),
        sa.Column("accepted_match_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("finalized_sequence", sa.BigInteger(), nullable=False),
        sa.Column("finalized_event_id", sa.String(length=64), nullable=True),
        sa.Column("state_version", sa.BigInteger(), nullable=False),
        sa.Column("pending_checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("accepted_sequence >= 1", name="ck_matches_accepted_sequence"),
        sa.CheckConstraint(
            "finalized_sequence >= 0 AND finalized_sequence <= accepted_sequence",
            name="ck_matches_watermarks",
        ),
        sa.UniqueConstraint("match_id", "simulation_run_id", name="uq_matches_match_run"),
        sa.UniqueConstraint("simulation_run_id", name="uq_matches_simulation_run_id"),
    )
    op.create_table(
        "match_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("simulation_run_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("match_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("period_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("canonical_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["match_id", "simulation_run_id"],
            ["matches.match_id", "matches.simulation_run_id"],
            name="fk_match_events_match_run",
        ),
        sa.UniqueConstraint("event_id", name="uq_match_events_event_id"),
        sa.UniqueConstraint(
            "match_id", "simulation_run_id", "sequence",
            name="uq_match_events_match_run_sequence",
        ),
    )
    op.create_index(
        "ix_match_events_match_sequence", "match_events", ["match_id", "sequence"], unique=False
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION match_events_immutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'match_events is append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_match_events_immutable BEFORE UPDATE OR DELETE ON match_events FOR EACH ROW EXECUTE FUNCTION match_events_immutable()")
        op.execute("CREATE TRIGGER trg_match_events_no_truncate BEFORE TRUNCATE ON match_events FOR EACH STATEMENT EXECUTE FUNCTION match_events_immutable()")
def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_match_events_immutable ON match_events")
        op.execute("DROP TRIGGER IF EXISTS trg_match_events_no_truncate ON match_events")
        op.execute("DROP FUNCTION IF EXISTS match_events_immutable()")
    op.drop_index("ix_match_events_match_sequence", table_name="match_events")
    op.drop_table("match_events")
    op.drop_table("matches")

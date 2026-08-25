"""add candidate stage history tracking

Revision ID: 4a9d885ac5f5
Revises: a05baafa6355
Create Date: 2026-08-25 16:32:52.904868

"""
"""Adds candidate_stage_history: precise entered_at/exited_at per
candidate pipeline stage, so "time spent in stage" can be computed
exactly going forward (per-candidate detail tab + dashboard averages).

candidates.stage previously changed in 4 places in
routers/recruitment.py (move_stage, schedule_interview's auto-move,
create_offer's Offer/Decline branch, update_offer_status's Accepted
branch), each independently calling _log_candidate with its own
human-readable action/detail text — only move_stage's "Stage Changed"
entries are cleanly parseable as an old→new transition, so
candidate_audit_log can't reliably answer "how long in each stage" on
its own. candidates.updated_at is equally unusable: it's bumped by the
trg_cand_upd trigger (see 20260717_0001) on *any* row update, not just a
stage change. This table is purpose-built instead, kept in sync via one
new shared helper (_transition_candidate_stage) all 5 stage-touching call
sites (the 4 above, plus candidate creation, which seeds the initial
'New' row) now go through.

Backfill: one open row per existing candidate, stage=candidates.stage,
entered_at=candidates.updated_at (the closest available proxy — exact
historical stage-entry times don't exist), exited_at=NULL. Same
"document the approximation, don't silently assume it" approach as the
Rejected→Rejected by Company backfill in a05baafa6355.
"""
from alembic import op


revision = '4a9d885ac5f5'
down_revision = 'a05baafa6355'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS candidate_stage_history (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            candidate_id    INTEGER NOT NULL REFERENCES candidates(id),
            stage           TEXT    NOT NULL,
            entered_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            exited_at       TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_stage_history_institution_candidate "
               "ON candidate_stage_history(institution_id, candidate_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_stage_history_institution_stage "
               "ON candidate_stage_history(institution_id, stage)")

    op.execute("ALTER TABLE candidate_stage_history ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON candidate_stage_history
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE candidate_stage_history FORCE ROW LEVEL SECURITY")

    op.execute("""
        INSERT INTO candidate_stage_history (institution_id, candidate_id, stage, entered_at, exited_at)
        SELECT institution_id, id, stage, updated_at, NULL FROM candidates
    """)


def downgrade():
    op.execute("ALTER TABLE candidate_stage_history NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON candidate_stage_history")
    op.execute("DROP TABLE IF EXISTS candidate_stage_history")

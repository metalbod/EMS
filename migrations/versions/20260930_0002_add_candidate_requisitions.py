"""Add candidate_requisitions (one person, many requisitions)

Revision ID: 20260930_0002
Revises: 20260928_0001
Create Date: 2026-09-30

Phase 1 of "one candidate, many requisitions" (see the session plan this
was approved from — no separate design doc). candidates.requisition_id is
today a single nullable FK: one candidate *row* per application, so the
same real person applying to a second requisition means a second,
unrelated candidates row with no link to the first — duplicated profile
data, and a stage change on one application has no way to reflect (or not
reflect) on the other.

This migration only ADDS structure — no application code reads or writes
candidate_requisitions yet (that's Phase 2), and every existing column on
candidates/candidate_stage_history stays exactly as-is. Safe to apply and
run for a while with the old code path still in charge; nothing breaks
mid-rollout.

candidate_requisitions is the new "application": one row per
(candidate, requisition), holding everything that's really about *this*
application rather than the person — stage, source, notes, salary
expectation, notice period, referral. candidates itself becomes purely the
deduplicated person record (name, IC, email, resume, skills, documents,
general audit log) once Phase 2 stops writing the old requisition_id/
stage/source/notes/expected_salary/notice_period/referral_by columns on it
(they're left in place here, untouched, for exactly that transition).

interviews/offers need NO schema change — they already carry their own
requisition_id alongside candidate_id (see 20260717_0001_full_schema_ddl),
so that pair already uniquely identifies "this application" without a new
FK. candidate_stage_history does need a requisition_id, though: it
currently assumes at most one open (exited_at IS NULL) stage row per
candidate, which stops holding once a person can be mid-pipeline on two
applications at once.

Backfill (both tables): one row per existing candidates row, using its own
current requisition_id/stage/etc — per the approved plan, deliberately NO
attempt to detect or merge candidates rows that already represent the same
real person under different requisitions. Every pre-existing row becomes
its own independent person with exactly one application; that's exactly
today's behavior, just made explicit. A person can be linked across
requisitions only from this point forward, via Phase 2's new "apply an
existing candidate to another requisition" endpoint.
"""
from alembic import op

revision = '20260930_0002'
down_revision = '20260928_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS candidate_requisitions (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            candidate_id    INTEGER NOT NULL REFERENCES candidates(id),
            requisition_id  INTEGER REFERENCES job_requisitions(id),
            stage           TEXT    NOT NULL DEFAULT 'New',
            source          TEXT    NOT NULL DEFAULT 'Direct',
            notes           TEXT,
            expected_salary NUMERIC(12,2),
            notice_period   TEXT,
            referral_by     TEXT,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            -- A candidate can't apply to the exact same requisition twice.
            UNIQUE(candidate_id, requisition_id)
        )
    """)
    # UNIQUE above doesn't stop multiple NULL-requisition ("general
    # interest, not tied to a specific opening") rows for one candidate,
    # since SQL treats every NULL as distinct — this partial index closes
    # that gap on its own: at most one general-interest row per candidate.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_requisitions_general
        ON candidate_requisitions(candidate_id) WHERE requisition_id IS NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_requisitions_institution_requisition "
               "ON candidate_requisitions(institution_id, requisition_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_requisitions_institution_stage "
               "ON candidate_requisitions(institution_id, stage)")

    op.execute("DROP TRIGGER IF EXISTS trg_candreq_upd ON candidate_requisitions")
    op.execute("""
        CREATE TRIGGER trg_candreq_upd BEFORE UPDATE ON candidate_requisitions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    op.execute("ALTER TABLE candidate_requisitions ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON candidate_requisitions
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE candidate_requisitions FORCE ROW LEVEL SECURITY")

    op.execute("""
        INSERT INTO candidate_requisitions
            (institution_id, candidate_id, requisition_id, stage, source, notes,
             expected_salary, notice_period, referral_by, created_by, created_at, updated_at)
        SELECT institution_id, id, requisition_id, stage, source, notes,
               expected_salary, notice_period, referral_by, created_by, created_at, updated_at
        FROM candidates
    """)

    # candidate_stage_history's own institution_id/candidate_id columns
    # already narrow this correctly for every row backfilled here (each
    # existing candidate has exactly one requisition_id today), so a plain
    # correlated UPDATE is enough — no ambiguity to resolve.
    op.execute("ALTER TABLE candidate_stage_history ADD COLUMN IF NOT EXISTS requisition_id INTEGER REFERENCES job_requisitions(id)")
    op.execute("""
        UPDATE candidate_stage_history h
        SET requisition_id = c.requisition_id
        FROM candidates c
        WHERE c.id = h.candidate_id
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_stage_history_institution_requisition "
               "ON candidate_stage_history(institution_id, requisition_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_candidate_stage_history_institution_requisition")
    op.execute("ALTER TABLE candidate_stage_history DROP COLUMN IF EXISTS requisition_id")

    op.execute("ALTER TABLE candidate_requisitions NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON candidate_requisitions")
    op.execute("DROP TRIGGER IF EXISTS trg_candreq_upd ON candidate_requisitions")
    op.execute("DROP TABLE IF EXISTS candidate_requisitions")

"""Add missing requisition_id indexes (candidates, interviews, offers)

Revision ID: 20260806_0003
Revises: 20260806_0002
Create Date: 2026-08-06

routers/recruitment.py's list_requisitions runs 4 correlated subqueries
per requisition row (candidate_count, shortlisted_count,
interviewed_count, offer_count), each filtered by requisition_id against
candidates/interviews/offers — none of which had an index on that
column, only institution_id. Confirmed via EXPLAIN ANALYZE (Supabase
slow-query report): a Seq Scan per subquery per row, ~1.1s total for
~2200 requisitions against ~3200 candidates in the shared test
institution.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260806_0003'
down_revision = '20260806_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('idx_candidates_requisition_id', 'candidates', ['requisition_id'])
    op.create_index('idx_interviews_requisition_id', 'interviews', ['requisition_id'])
    op.create_index('idx_offers_requisition_id', 'offers', ['requisition_id'])


def downgrade():
    op.drop_index('idx_offers_requisition_id', table_name='offers')
    op.drop_index('idx_interviews_requisition_id', table_name='interviews')
    op.drop_index('idx_candidates_requisition_id', table_name='candidates')

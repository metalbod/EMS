"""Add missing index on ob_checklist_items.checklist_id

Revision ID: 20260806_0002
Revises: 20260806_0001
Create Date: 2026-08-06

ob_checklist_items had only an institution_id index — every item-list
lookup, MAX(order_index) computation, and the Dashboard To-Do aggregation
(routers/dashboard.py) filters/joins on checklist_id instead, forcing a
full table scan. Found while investigating a Supabase query-performance
report flagging these as slow; the underlying table also had heavy dead
tuple bloat from an unrelated bulk cleanup, addressed separately via
VACUUM FULL (not something a migration can do safely/portably).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260806_0002'
down_revision = '20260806_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('idx_ob_checklist_items_checklist_id', 'ob_checklist_items', ['checklist_id'])


def downgrade():
    op.drop_index('idx_ob_checklist_items_checklist_id', table_name='ob_checklist_items')

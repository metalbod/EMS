"""Fix two more nullable user-reference FKs to ON DELETE SET NULL

Revision ID: 20260727_0001
Revises: 20260726_0001
Create Date: 2026-07-27

Same category of bug as 20260726_0001 (location_transfers), just on two
more tables added in the same 20260719_0002 migration:
  - employee_location_assignments.ended_by_user_id
  - location_capacity_alerts.acknowledged_by_user_id

Both are nullable and had no ON DELETE clause (defaulting to NO ACTION),
confirmed live via pg_constraint.confdeltype = 'a' on the actual database
(not 'fk_assignment_ended_by_user', the name the original migration
specified — this DB's schema was evidently not built by literally
replaying every historical migration, same situation noted in
20260725_0017's docstring). Confirmed by CI: deleting a disposable test
user who had ended an employee_location_assignments row failed with
psycopg2.errors.ForeignKeyViolation on
employee_location_assignments_ended_by_user_id_fkey.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260727_0001'
down_revision = '20260726_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('employee_location_assignments_ended_by_user_id_fkey', 'employee_location_assignments', type_='foreignkey')
    op.create_foreign_key(
        'employee_location_assignments_ended_by_user_id_fkey', 'employee_location_assignments',
        'users', ['ended_by_user_id'], ['id'], ondelete='SET NULL',
    )
    op.drop_constraint('location_capacity_alerts_acknowledged_by_user_id_fkey', 'location_capacity_alerts', type_='foreignkey')
    op.create_foreign_key(
        'location_capacity_alerts_acknowledged_by_user_id_fkey', 'location_capacity_alerts',
        'users', ['acknowledged_by_user_id'], ['id'], ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('location_capacity_alerts_acknowledged_by_user_id_fkey', 'location_capacity_alerts', type_='foreignkey')
    op.create_foreign_key(
        'location_capacity_alerts_acknowledged_by_user_id_fkey', 'location_capacity_alerts',
        'users', ['acknowledged_by_user_id'], ['id'],
    )
    op.drop_constraint('employee_location_assignments_ended_by_user_id_fkey', 'employee_location_assignments', type_='foreignkey')
    op.create_foreign_key(
        'employee_location_assignments_ended_by_user_id_fkey', 'employee_location_assignments',
        'users', ['ended_by_user_id'], ['id'],
    )

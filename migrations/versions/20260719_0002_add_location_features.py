"""Add location features: transfers, alerts, budgets, reports.

Revision ID: 20260719_0002
Revises: 20260718_0001
Create Date: 2026-07-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260719_0002'
down_revision = '20260718_0001'
branch_labels = None
depends_on = None


def upgrade():
    # Add columns to employee_location_assignments
    op.add_column('employee_location_assignments', sa.Column('ended_by_user_id', sa.Integer(), nullable=True))
    op.add_column('employee_location_assignments', sa.Column('end_reason', sa.Text(), nullable=True))
    op.create_foreign_key('fk_assignment_ended_by_user', 'employee_location_assignments', 'users', ['ended_by_user_id'], ['id'])

    # Add capacity settings to locations
    op.add_column('locations', sa.Column('capacity_warning_threshold', sa.Integer(), nullable=True, server_default='80'))
    op.add_column('locations', sa.Column('capacity_critical_threshold', sa.Integer(), nullable=True, server_default='95'))

    # Create location_transfers table
    op.create_table(
        'location_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Text(), nullable=False),
        sa.Column('from_location_id', sa.Integer(), nullable=True),
        sa.Column('to_location_id', sa.Integer(), nullable=False),
        sa.Column('transfer_date', sa.Date(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='Pending'),
        sa.Column('requested_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
        sa.ForeignKeyConstraint(['from_location_id'], ['locations.id'], ),
        sa.ForeignKeyConstraint(['to_location_id'], ['locations.id'], ),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'to_location_id', 'transfer_date', name='uq_transfer_unique')
    )
    op.create_index('idx_transfers_employee', 'location_transfers', ['employee_id', 'status'])
    op.create_index('idx_transfers_location', 'location_transfers', ['to_location_id', 'status'])

    # Create location_capacity_alerts table
    op.create_table(
        'location_capacity_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('alert_level', sa.Text(), nullable=False),
        sa.Column('triggered_at', sa.Text(), nullable=False),
        sa.Column('acknowledged_at', sa.Text(), nullable=True),
        sa.Column('acknowledged_by_user_id', sa.Integer(), nullable=True),
        sa.Column('is_resolved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('resolved_at', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ),
        sa.ForeignKeyConstraint(['acknowledged_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_alerts_location', 'location_capacity_alerts', ['location_id', 'is_resolved'])
    op.create_index('idx_alerts_active', 'location_capacity_alerts', ['is_resolved', 'triggered_at'])

    # Create location_budgets table
    op.create_table(
        'location_budgets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('budget_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('actual_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('location_id', 'period_start', 'period_end', name='uq_budget_period')
    )
    op.create_index('idx_budget_location_period', 'location_budgets', ['location_id', 'period_start', 'period_end'])

    # Create report_schedules table
    op.create_table(
        'report_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('report_type', sa.Text(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('frequency', sa.Text(), nullable=False),
        sa.Column('scheduled_day_of_week', sa.Integer(), nullable=True),
        sa.Column('scheduled_day_of_month', sa.Integer(), nullable=True),
        sa.Column('email_recipients', sa.Text(), nullable=True),
        sa.Column('format', sa.Text(), nullable=False, server_default='CSV'),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_schedule_active', 'report_schedules', ['is_active', 'frequency'])
    op.create_index('idx_schedule_location', 'report_schedules', ['location_id', 'is_active'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_schedule_location', 'report_schedules')
    op.drop_index('idx_schedule_active', 'report_schedules')
    op.drop_index('idx_budget_location_period', 'location_budgets')
    op.drop_index('idx_alerts_active', 'location_capacity_alerts')
    op.drop_index('idx_alerts_location', 'location_capacity_alerts')
    op.drop_index('idx_transfers_location', 'location_transfers')
    op.drop_index('idx_transfers_employee', 'location_transfers')

    # Drop tables
    op.drop_table('report_schedules')
    op.drop_table('location_budgets')
    op.drop_table('location_capacity_alerts')
    op.drop_table('location_transfers')

    # Drop columns from locations
    op.drop_column('locations', 'capacity_critical_threshold')
    op.drop_column('locations', 'capacity_warning_threshold')

    # Drop columns from employee_location_assignments
    op.drop_constraint('fk_assignment_ended_by_user', 'employee_location_assignments', type_='foreignkey')
    op.drop_column('employee_location_assignments', 'end_reason')
    op.drop_column('employee_location_assignments', 'ended_by_user_id')

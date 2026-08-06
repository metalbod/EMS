"""Add custom_roles (per-institution configurable roles)

Revision ID: 20260807_0001
Revises: 20260806_0005
Create Date: 2026-08-07

Roles were previously a hardcoded Python list (core.constants.
INSTITUTION_ROLES) — this adds a per-institution table so HR can define
additional roles (e.g. "IT Infra") beyond the 6 fixed built-ins
(hr_manager, hr_admin, manager, payroll_manager, compensation_manager,
employee — see core/roles.py's BUILTIN_ROLES), usable both as a user's
role and as an onboarding/offboarding checklist item's assigned_role.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260807_0001'
down_revision = '20260806_0005'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'custom_roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('role_key', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_custom_roles_institution_id', 'custom_roles', ['institution_id'])
    op.create_unique_constraint('uq_custom_roles_institution_key', 'custom_roles', ['institution_id', 'role_key'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON custom_roles
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE custom_roles FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE custom_roles NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON custom_roles")
    op.drop_constraint('uq_custom_roles_institution_key', 'custom_roles', type_='unique')
    op.drop_index('ix_custom_roles_institution_id', table_name='custom_roles')
    op.drop_table('custom_roles')

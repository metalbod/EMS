"""Add Compensation Framework: Pay Grades, Job Levels, Salary Structures

Revision ID: 20260719_0003
Revises: 20260719_0002
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    """Create compensation framework tables."""

    # Pay Grades table - defines salary bands
    op.create_table(
        'pay_grades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('grade_code', sa.String(20), nullable=False),
        sa.Column('grade_name', sa.String(100), nullable=False),
        sa.Column('grade_level', sa.Integer(), nullable=False),  # For sorting (1=lowest)
        sa.Column('min_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('midpoint_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('max_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('institution_id', 'grade_code', name='uq_pay_grade_code'),
        sa.Index('ix_pay_grades_institution', 'institution_id'),
        sa.Index('ix_pay_grades_level', 'grade_level'),
    )

    # Job Levels table - defines organizational hierarchy
    op.create_table(
        'job_levels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('level_code', sa.String(20), nullable=False),
        sa.Column('level_name', sa.String(100), nullable=False),
        sa.Column('level_order', sa.Integer(), nullable=False),  # 1=entry level, ascending
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('institution_id', 'level_code', name='uq_job_level_code'),
        sa.Index('ix_job_levels_institution', 'institution_id'),
    )

    # Job Roles table - specific job titles/roles
    op.create_table(
        'job_roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('job_level_id', sa.Integer(), nullable=False),
        sa.Column('role_name', sa.String(100), nullable=False),
        sa.Column('role_code', sa.String(20), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('department', sa.String(100), nullable=True),
        sa.Column('required_experience_years', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_level_id'], ['job_levels.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('institution_id', 'role_code', name='uq_job_role_code'),
        sa.Index('ix_job_roles_institution', 'institution_id'),
        sa.Index('ix_job_roles_level', 'job_level_id'),
    )

    # Job Role to Pay Grade mapping
    op.create_table(
        'job_role_pay_grades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_role_id', sa.Integer(), nullable=False),
        sa.Column('pay_grade_id', sa.Integer(), nullable=False),
        sa.Column('is_primary', sa.Integer(), nullable=False, server_default='0'),  # Primary grade for this role
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['job_role_id'], ['job_roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pay_grade_id'], ['pay_grades.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('job_role_id', 'pay_grade_id', name='uq_role_grade'),
        sa.Index('ix_role_pay_grades_role', 'job_role_id'),
    )

    # Salary Structure Templates
    op.create_table(
        'salary_structures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('structure_name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('structure_type', sa.String(50), nullable=False),  # 'template', 'role', 'location', 'business_unit'
        sa.Column('applicable_to_id', sa.Integer(), nullable=True),  # role_id, location_id, or business_unit_id depending on type
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_salary_structures_institution', 'institution_id'),
        sa.Index('ix_salary_structures_type', 'structure_type'),
    )

    # Salary Components (base salary, allowances, benefits breakdown)
    op.create_table(
        'salary_components',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('salary_structure_id', sa.Integer(), nullable=False),
        sa.Column('component_name', sa.String(100), nullable=False),  # 'base_salary', 'housing_allowance', etc.
        sa.Column('component_type', sa.String(50), nullable=False),  # 'base', 'allowance', 'benefit', 'deduction'
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),  # Fixed amount
        sa.Column('percentage_of_base', sa.Numeric(5, 2), nullable=True),  # % of base salary
        sa.Column('is_taxable', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['salary_structure_id'], ['salary_structures.id'], ondelete='CASCADE'),
        sa.Index('ix_salary_components_structure', 'salary_structure_id'),
    )

    # Employee Compensation - link employee to job role, pay grade, salary structure
    op.create_table(
        'employee_compensation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('job_role_id', sa.Integer(), nullable=True),
        sa.Column('job_level_id', sa.Integer(), nullable=True),
        sa.Column('pay_grade_id', sa.Integer(), nullable=True),
        sa.Column('salary_structure_id', sa.Integer(), nullable=True),
        sa.Column('base_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('effective_date', sa.String(10), nullable=False),  # YYYY-MM-DD
        sa.Column('end_date', sa.String(10), nullable=True),  # For historical records
        sa.Column('is_current', sa.Integer(), nullable=False, server_default='1'),  # Current active record
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.employee_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_role_id'], ['job_roles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['job_level_id'], ['job_levels.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['pay_grade_id'], ['pay_grades.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['salary_structure_id'], ['salary_structures.id'], ondelete='SET NULL'),
        sa.Index('ix_emp_comp_employee', 'employee_id'),
        sa.Index('ix_emp_comp_current', 'is_current'),
        sa.Index('ix_emp_comp_grade', 'pay_grade_id'),
    )

    # Salary Changes History - audit trail
    op.create_table(
        'salary_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('change_type', sa.String(50), nullable=False),  # 'merit_increase', 'promotion', 'adjustment', 'role_change'
        sa.Column('from_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('to_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('from_pay_grade_id', sa.Integer(), nullable=True),
        sa.Column('to_pay_grade_id', sa.Integer(), nullable=True),
        sa.Column('from_job_level_id', sa.Integer(), nullable=True),
        sa.Column('to_job_level_id', sa.Integer(), nullable=True),
        sa.Column('effective_date', sa.String(10), nullable=False),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approval_date', sa.String(50), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending'),  # Pending, Approved, Rejected
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.employee_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_pay_grade_id'], ['pay_grades.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_pay_grade_id'], ['pay_grades.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['from_job_level_id'], ['job_levels.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_job_level_id'], ['job_levels.id'], ondelete='SET NULL'),
        sa.Index('ix_salary_changes_employee', 'employee_id'),
        sa.Index('ix_salary_changes_status', 'status'),
        sa.Index('ix_salary_changes_type', 'change_type'),
    )

    # Merit Review Cycles
    op.create_table(
        'merit_review_cycles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('cycle_name', sa.String(100), nullable=False),
        sa.Column('review_year', sa.Integer(), nullable=False),
        sa.Column('cycle_start_date', sa.String(10), nullable=False),
        sa.Column('cycle_end_date', sa.String(10), nullable=False),
        sa.Column('submission_deadline', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),  # Draft, Active, Completed
        sa.Column('budget_pool_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_merit_cycles_institution', 'institution_id'),
        sa.Index('ix_merit_cycles_status', 'status'),
    )

    # Merit Increase Recommendations
    op.create_table(
        'merit_recommendations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('merit_review_cycle_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('current_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('recommended_increase_percent', sa.Numeric(5, 2), nullable=False),
        sa.Column('recommended_new_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('recommended_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approval_status', sa.String(20), nullable=False, server_default='Pending'),  # Pending, Approved, Rejected
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approval_date', sa.String(50), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['merit_review_cycle_id'], ['merit_review_cycles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_merit_rec_cycle', 'merit_review_cycle_id'),
        sa.Index('ix_merit_rec_employee', 'employee_id'),
        sa.Index('ix_merit_rec_status', 'approval_status'),
    )

    # Pay Equity Analysis Results (cached/computed)
    op.create_table(
        'pay_equity_analysis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('analysis_date', sa.String(50), nullable=False),
        sa.Column('analysis_type', sa.String(50), nullable=False),  # 'gender', 'department', 'role', 'location', 'tenure'
        sa.Column('category_1', sa.String(100), nullable=False),  # e.g., 'Female', 'Engineering', 'Engineer', 'KL', '<2 years'
        sa.Column('category_2', sa.String(100), nullable=True),  # e.g., 'Male' for comparison
        sa.Column('count_1', sa.Integer(), nullable=False),
        sa.Column('count_2', sa.Integer(), nullable=True),
        sa.Column('avg_salary_1', sa.Numeric(12, 2), nullable=False),
        sa.Column('avg_salary_2', sa.Numeric(12, 2), nullable=True),
        sa.Column('pay_gap_percent', sa.Numeric(5, 2), nullable=True),
        sa.Column('flagged', sa.Integer(), nullable=False, server_default='0'),  # Flag if gap > threshold
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_pay_equity_institution', 'institution_id'),
        sa.Index('ix_pay_equity_type', 'analysis_type'),
        sa.Index('ix_pay_equity_flagged', 'flagged'),
    )

    # Create triggers for automatic timestamps
    op.execute("""
    CREATE TRIGGER pay_grades_update_timestamp
    BEFORE UPDATE ON pay_grades
    FOR EACH ROW
    BEGIN
      NEW.updated_at = datetime('now');
    END;
    """)

    op.execute("""
    CREATE TRIGGER job_levels_update_timestamp
    BEFORE UPDATE ON job_levels
    FOR EACH ROW
    BEGIN
      NEW.updated_at = datetime('now');
    END;
    """)

    op.execute("""
    CREATE TRIGGER job_roles_update_timestamp
    BEFORE UPDATE ON job_roles
    FOR EACH ROW
    BEGIN
      NEW.updated_at = datetime('now');
    END;
    """)

    op.execute("""
    CREATE TRIGGER salary_structures_update_timestamp
    BEFORE UPDATE ON salary_structures
    FOR EACH ROW
    BEGIN
      NEW.updated_at = datetime('now');
    END;
    """)

    op.execute("""
    CREATE TRIGGER employee_compensation_update_timestamp
    BEFORE UPDATE ON employee_compensation
    FOR EACH ROW
    BEGIN
      NEW.updated_at = datetime('now');
    END;
    """)

    op.execute("""
    CREATE TRIGGER merit_review_cycles_update_timestamp
    BEFORE UPDATE ON merit_review_cycles
    FOR EACH ROW
    BEGIN
      NEW.updated_at = datetime('now');
    END;
    """)

    op.execute("""
    CREATE TRIGGER merit_recommendations_update_timestamp
    BEFORE UPDATE ON merit_recommendations
    FOR EACH ROW
    BEGIN
      NEW.updated_at = datetime('now');
    END;
    """)


def downgrade():
    """Drop compensation framework tables."""
    op.drop_table('pay_equity_analysis')
    op.drop_table('merit_recommendations')
    op.drop_table('merit_review_cycles')
    op.drop_table('salary_changes')
    op.drop_table('employee_compensation')
    op.drop_table('salary_components')
    op.drop_table('salary_structures')
    op.drop_table('job_role_pay_grades')
    op.drop_table('job_roles')
    op.drop_table('job_levels')
    op.drop_table('pay_grades')

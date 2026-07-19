"""
Sample compensation setup for software companies.
Typical structure for Mandrill demo institution with realistic pay grades,
job levels, roles, and merit cycles.
"""
import sqlite3
from datetime import datetime, timedelta

# Note: This is for SQLite. For production PostgreSQL, adjust syntax accordingly.

SAMPLE_DATA = {
    "pay_grades": [
        {
            "grade_code": "IC1",
            "grade_name": "Junior IC - Entry Level",
            "grade_level": 1,
            "min_salary": 3500.00,
            "midpoint_salary": 4200.00,
            "max_salary": 5000.00,
            "description": "Entry level individual contributor roles for new graduates or career starters"
        },
        {
            "grade_code": "IC2",
            "grade_name": "Mid-Level IC",
            "grade_level": 2,
            "min_salary": 5100.00,
            "midpoint_salary": 6300.00,
            "max_salary": 7500.00,
            "description": "Mid-level engineer with 2-4 years experience"
        },
        {
            "grade_code": "IC3",
            "grade_name": "Senior IC",
            "grade_level": 3,
            "min_salary": 7600.00,
            "midpoint_salary": 9000.00,
            "max_salary": 11000.00,
            "description": "Senior engineer with deep expertise, mentoring capabilities"
        },
        {
            "grade_code": "IC4",
            "grade_name": "Staff / Principal IC",
            "grade_level": 4,
            "min_salary": 11000.00,
            "midpoint_salary": 13000.00,
            "max_salary": 16000.00,
            "description": "Staff-level engineers driving technical strategy"
        },
        {
            "grade_code": "L1",
            "grade_name": "Tech Lead / Lead Engineer",
            "grade_level": 5,
            "min_salary": 8500.00,
            "midpoint_salary": 10000.00,
            "max_salary": 12000.00,
            "description": "Technical lead managing small teams or major projects"
        },
        {
            "grade_code": "M1",
            "grade_name": "Engineering Manager",
            "grade_level": 6,
            "min_salary": 10000.00,
            "midpoint_salary": 12000.00,
            "max_salary": 15000.00,
            "description": "Manager overseeing engineering team of 5-10 people"
        },
        {
            "grade_code": "M2",
            "grade_name": "Senior Engineering Manager",
            "grade_level": 7,
            "min_salary": 13000.00,
            "midpoint_salary": 15500.00,
            "max_salary": 19000.00,
            "description": "Senior manager overseeing multiple teams or large team"
        },
        {
            "grade_code": "D1",
            "grade_name": "Engineering Director",
            "grade_level": 8,
            "min_salary": 16000.00,
            "midpoint_salary": 19000.00,
            "max_salary": 25000.00,
            "description": "Director-level leader for engineering departments"
        },
    ],

    "job_levels": [
        {
            "level_code": "ENTRY",
            "level_name": "Entry Level",
            "level_order": 1,
            "description": "Fresh graduates or career starters (0-1 years)"
        },
        {
            "level_code": "JUNIOR",
            "level_name": "Junior",
            "level_order": 2,
            "description": "Junior engineers (1-2 years experience)"
        },
        {
            "level_code": "MID",
            "level_name": "Mid-Level",
            "level_order": 3,
            "description": "Mid-level engineers (2-5 years experience)"
        },
        {
            "level_code": "SENIOR",
            "level_name": "Senior",
            "level_order": 4,
            "description": "Senior engineers (5+ years experience)"
        },
        {
            "level_code": "STAFF",
            "level_name": "Staff/Principal",
            "level_order": 5,
            "description": "Staff-level engineers driving technical direction"
        },
        {
            "level_code": "LEAD",
            "level_name": "Tech Lead",
            "level_order": 6,
            "description": "Technical leads managing projects or small teams"
        },
        {
            "level_code": "MANAGER",
            "level_name": "Manager",
            "level_order": 7,
            "description": "Engineering managers overseeing teams"
        },
        {
            "level_code": "SENIOR_MANAGER",
            "level_name": "Senior Manager",
            "level_order": 8,
            "description": "Senior managers with multiple teams"
        },
        {
            "level_code": "DIRECTOR",
            "level_name": "Director",
            "level_order": 9,
            "description": "Director-level leadership"
        },
    ],

    "job_roles": [
        {
            "level_code": "ENTRY",
            "role_name": "Junior Software Engineer",
            "role_code": "ENG_JR",
            "department": "Engineering",
            "required_experience_years": 0,
        },
        {
            "level_code": "JUNIOR",
            "role_name": "Software Engineer I",
            "role_code": "ENG_1",
            "department": "Engineering",
            "required_experience_years": 1,
        },
        {
            "level_code": "MID",
            "role_name": "Software Engineer II",
            "role_code": "ENG_2",
            "department": "Engineering",
            "required_experience_years": 3,
        },
        {
            "level_code": "MID",
            "role_name": "Frontend Engineer II",
            "role_code": "FE_2",
            "department": "Engineering",
            "required_experience_years": 3,
        },
        {
            "level_code": "MID",
            "role_name": "Backend Engineer II",
            "role_code": "BE_2",
            "department": "Engineering",
            "required_experience_years": 3,
        },
        {
            "level_code": "SENIOR",
            "role_name": "Senior Software Engineer",
            "role_code": "ENG_SR",
            "department": "Engineering",
            "required_experience_years": 5,
        },
        {
            "level_code": "SENIOR",
            "role_name": "Senior Frontend Engineer",
            "role_code": "FE_SR",
            "department": "Engineering",
            "required_experience_years": 5,
        },
        {
            "level_code": "SENIOR",
            "role_name": "Senior Backend Engineer",
            "role_code": "BE_SR",
            "department": "Engineering",
            "required_experience_years": 5,
        },
        {
            "level_code": "STAFF",
            "role_name": "Staff Engineer",
            "role_code": "ENG_STAFF",
            "department": "Engineering",
            "required_experience_years": 8,
        },
        {
            "level_code": "LEAD",
            "role_name": "Engineering Tech Lead",
            "role_code": "TECH_LEAD",
            "department": "Engineering",
            "required_experience_years": 5,
        },
        {
            "level_code": "MANAGER",
            "role_name": "Engineering Manager",
            "role_code": "ENG_MGR",
            "department": "Engineering",
            "required_experience_years": 5,
        },
        {
            "level_code": "SENIOR_MANAGER",
            "role_name": "Senior Engineering Manager",
            "role_code": "ENG_SR_MGR",
            "department": "Engineering",
            "required_experience_years": 8,
        },
        {
            "level_code": "DIRECTOR",
            "role_name": "Engineering Director",
            "role_code": "ENG_DIR",
            "department": "Engineering",
            "required_experience_years": 10,
        },
    ],

    "merit_cycles": [
        {
            "cycle_name": "2026 Annual Merit Review",
            "review_year": 2026,
            "cycle_start_date": "2026-01-01",
            "cycle_end_date": "2026-02-28",
            "submission_deadline": "2026-02-15",
            "budget_pool_amount": 1500000.00,
            "description": "Annual merit increase cycle for all employees. Budget: RM 1.5M"
        },
        {
            "cycle_name": "2026 Mid-Year Bonus Review",
            "review_year": 2026,
            "cycle_start_date": "2026-06-01",
            "cycle_end_date": "2026-07-31",
            "submission_deadline": "2026-07-15",
            "budget_pool_amount": 800000.00,
            "description": "Mid-year performance bonus distribution. Budget: RM 800K"
        },
    ]
}


def seed_compensation_data(institution_code: str = "MANDRILL"):
    """
    Seed sample compensation data for a software company.

    Usage:
        python -c "from seeds.compensation_setup_software import seed_compensation_data; seed_compensation_data()"
    """
    import requests
    import json

    # This would connect to the live API to create the data
    # For now, print the structure to be imported

    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║   Software Company Compensation Setup - Sample Data          ║
    ║   Ready to import into Mandrill demo institution             ║
    ╚══════════════════════════════════════════════════════════════╝

    This setup includes:
    ✅ 8 Pay Grades (IC1-IC4, L1, M1-M2, D1)
    ✅ 9 Job Levels (Entry → Director)
    ✅ 13 Job Roles (Junior → Director level roles)
    ✅ 2 Merit Cycles (Annual + Mid-Year)

    Typical salary ranges for Malaysia-based tech company:

    Pay Grade Breakdown:
    """)

    for grade in SAMPLE_DATA["pay_grades"]:
        print(f"    {grade['grade_code']:5} {grade['grade_name']:30} "
              f"RM {grade['min_salary']:7,.0f} - {grade['max_salary']:7,.0f} "
              f"(mid: RM {grade['midpoint_salary']:7,.0f})")

    print(f"""
    Job Levels: {len(SAMPLE_DATA['job_levels'])} levels from Entry to Director
    Job Roles: {len(SAMPLE_DATA['job_roles'])} roles across Engineering department

    Role Examples:
    """)

    for role in SAMPLE_DATA["job_roles"][:8]:
        print(f"    • {role['role_name']:35} ({role['role_code']:10}) - "
              f"Requires {role['required_experience_years']} yrs")

    print(f"""
    Merit Cycles:
    """)

    for cycle in SAMPLE_DATA["merit_cycles"]:
        print(f"    • {cycle['cycle_name']:40} - Budget: RM {cycle['budget_pool_amount']:,.0f}")

    return SAMPLE_DATA


if __name__ == "__main__":
    seed_compensation_data()

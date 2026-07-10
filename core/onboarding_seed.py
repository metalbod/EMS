"""Default onboarding/offboarding checklist templates, seeded for every new institution."""
DEFAULT_OB_TEMPLATES = {
    "onboarding": [
        ("Medical / Health Check",          "Arrange pre-employment medical examination",              "hr_admin",   0),
        ("Background Check",                "Conduct background and reference verification",           "hr_admin",   1),
        ("Contract Signing",                "Issue and sign employment contract",                      "hr_manager", 2),
        ("System Account Setup",            "Create email, system logins and access cards",            "hr_admin",   3),
        ("Laptop / Equipment Allocation",   "Provision laptop and peripherals",                       "hr_admin",   4),
        ("Stationery & Supplies",           "Provide stationery kit and desk setup",                  "hr_admin",   5),
        ("Payroll & Bank Details",          "Collect bank info and register in payroll",               "hr_admin",   6),
        ("EPF / SOCSO / PCB Registration",  "Register statutory contributions",                       "hr_admin",   7),
        ("Orientation & Induction",         "Conduct company orientation session",                    "hr_manager", 8),
        ("Department Introduction",         "Introduce new hire to team and assign buddy",            "manager",    9),
        ("Welcome Acknowledgement",         "New employee signs onboarding completion form",          "employee",  10),
        # Day 1 activities
        ("Day 1: IT & Security Briefing",   "IT security policies, password rules and acceptable use","hr_admin",  11),
        ("Day 1: Workplace Safety Briefing","Evacuation routes, first aid and OSH awareness",         "hr_admin",  12),
        ("Day 1: Awareness Training",       "Complete mandatory e-learning modules (data privacy, anti-bribery, harassment)", "employee", 13),
        ("Day 1: Code of Conduct",          "Read and acknowledge the company Code of Conduct",       "employee",  14),
        ("Day 1: Employee Handbook",        "Read and acknowledge the Employee Handbook",             "employee",  15),
        ("Day 1: Company Policies",         "Briefing on leave, claims, travel and other HR policies","hr_manager",16),
        ("Day 1: Buddy / Mentor Intro",     "Meet assigned buddy or mentor for the probation period","manager",   17),
    ],
    "offboarding": [
        ("Resignation Letter Received",     "Acknowledge and accept resignation letter",               "hr_manager", 0),
        ("Exit Interview",                  "Conduct structured exit interview",                      "hr_manager", 1),
        ("Knowledge Transfer",              "Ensure handover of duties and documentation",            "manager",    2),
        ("System Access Revocation",        "Revoke all system, email and door access",               "hr_admin",   3),
        ("Return of Laptop / Equipment",    "Collect laptop, accessories and company assets",         "hr_admin",   4),
        ("Return of Stationery & Items",    "Collect stationery, pass and any company items",        "hr_admin",   5),
        ("Final Payroll Settlement",        "Process last salary, claims and encashment",             "hr_admin",   6),
        ("EPF / SOCSO Cessation",           "Notify statutory bodies of employment cessation",        "hr_admin",   7),
        ("Insurance & Benefits Termination","Remove from group insurance and benefits",               "hr_admin",   8),
        ("Reference / Certificate",         "Issue experience letter or reference if applicable",    "hr_manager", 9),
        ("Employee Acknowledgement",        "Employee signs offboarding completion checklist",       "employee",  10),
    ],
}


def seed_ob_templates(conn, inst_id: int):
    """Seed default onboarding/offboarding templates for a new institution."""
    for ob_type, items in DEFAULT_OB_TEMPLATES.items():
        existing = conn.execute(
            "SELECT COUNT(*) FROM ob_templates WHERE institution_id=? AND type=?", (inst_id, ob_type)
        ).fetchone()[0]
        if existing == 0:
            for title, desc, role, idx in items:
                conn.execute(
                    "INSERT INTO ob_templates (institution_id,type,title,description,assigned_role,order_index) VALUES (?,?,?,?,?,?)",
                    (inst_id, ob_type, title, desc, role, idx)
                )

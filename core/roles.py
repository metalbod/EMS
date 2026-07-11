"""Role-group constants shared across multiple routers/modules that main.py hasn't split out yet."""
ROLES = ["superadmin", "hr_manager", "hr_admin", "manager", "payroll_manager", "employee"]
LEAVE_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")
PAYROLL_VIEW_ROLES = ("payroll_manager", "hr_manager")

"""Static reference-data lists shared by /api/meta, EmployeeIn validators, and routers/employees.py."""
RACES            = ["Malay","Chinese","Indian","Bumiputera Sabah","Bumiputera Sarawak","Orang Asli","Others"]
RELIGIONS        = ["Islam","Buddhism","Christianity","Hinduism","Sikhism","No Religion","Others"]
GENDERS          = ["Male","Female"]
MARITAL_STATUSES = ["Single","Married","Divorced","Widowed"]
EMPLOYMENT_TYPES = ["Permanent","Contract","Part-Time","Internship"]
STATUSES         = ["Active","Inactive"]
BANKS = [
    "Maybank","CIMB Bank","Public Bank","RHB Bank","Hong Leong Bank",
    "AmBank","Bank Islam","Bank Rakyat","Affin Bank","Alliance Bank",
    "HSBC Bank Malaysia","Standard Chartered","OCBC Bank","UOB Malaysia","Others",
]

INSTITUTION_ROLES = ["hr_manager", "hr_admin", "manager", "payroll_manager", "employee"]
ROLE_LABELS = {
    "superadmin": "Platform Admin", "hr_manager": "HR Manager",
    "hr_admin": "HR Admin", "manager": "Manager", "payroll_manager": "Payroll Manager",
    "employee": "Employee",
}
PLANS = ["starter", "professional", "enterprise"]
PLAN_LABELS = {"starter": "Starter", "professional": "Professional", "enterprise": "Enterprise"}

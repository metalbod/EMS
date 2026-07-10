"""
Malaysia statutory payroll deduction calculators (EPF, SOCSO, EIS, PCB).

IMPORTANT: These are simplified approximations of the official KWSP/PERKESO/LHDN
rate tables, intended to get a payroll module running end-to-end. Real EPF/SOCSO/EIS
use exact wage-bracket rounding tables (not flat percentages), and PCB (MTD) follows
LHDN's formula method with many more reliefs/rebates than modelled here. Before this
is used for real payroll, an HR/payroll professional must verify the figures against
the current official tables — rates and brackets change periodically.
"""
import math

# ---------------------------------------------------------------------------
# EPF (KWSP) — simplified flat-rate approximation of the Third Schedule.
# ---------------------------------------------------------------------------
def calc_epf(wage: float) -> dict:
    if wage <= 0:
        return {"employee": 0.0, "employer": 0.0}
    employee_rate = 0.11
    employer_rate = 0.13 if wage <= 5000 else 0.12
    return {
        "employee": round(wage * employee_rate, 2),
        "employer": round(wage * employer_rate, 2),
    }

# ---------------------------------------------------------------------------
# SOCSO (PERKESO) — Category 1 (Employment Injury + Invalidity) for age < 60,
# Category 2 (Employment Injury only, employer-paid) for age >= 60.
# Wage ceiling RM6,000. Approximated as flat percentages of the tiered table.
# ---------------------------------------------------------------------------
SOCSO_WAGE_CEILING = 6000.0

def calc_socso(wage: float, age: int) -> dict:
    if wage <= 0:
        return {"employee": 0.0, "employer": 0.0}
    capped_wage = min(wage, SOCSO_WAGE_CEILING)
    if age >= 60:
        return {"employee": 0.0, "employer": round(capped_wage * 0.0125, 2)}
    return {
        "employee": round(capped_wage * 0.005, 2),
        "employer": round(capped_wage * 0.0175, 2),
    }

# ---------------------------------------------------------------------------
# EIS (SIP) — 0.2% employee + 0.2% employer, wage ceiling RM6,000.
# Exempt if age < 18 or age >= 60.
# ---------------------------------------------------------------------------
EIS_WAGE_CEILING = 6000.0

def calc_eis(wage: float, age: int) -> dict:
    if wage <= 0 or age < 18 or age >= 60:
        return {"employee": 0.0, "employer": 0.0}
    capped_wage = min(wage, EIS_WAGE_CEILING)
    return {
        "employee": round(capped_wage * 0.002, 2),
        "employer": round(capped_wage * 0.002, 2),
    }

# ---------------------------------------------------------------------------
# PCB (Potongan Cukai Bulanan) — simplified monthly tax deduction, derived by
# annualizing the monthly wage, applying personal/spouse/child relief and the
# progressive resident tax brackets, then dividing back by 12. This is NOT the
# exact LHDN formula method (which includes rebates, zakat, EPF relief caps,
# etc.) — treat as an estimate only.
# ---------------------------------------------------------------------------
_TAX_BRACKETS = [  # (upper bound of band, rate) — cumulative, YA2024-style resident rates
    (5000, 0.00),
    (20000, 0.01),
    (35000, 0.03),
    (50000, 0.06),
    (70000, 0.11),
    (100000, 0.19),
    (400000, 0.25),
    (600000, 0.26),
    (2000000, 0.28),
    (math.inf, 0.30),
]

def _annual_tax(chargeable: float) -> float:
    if chargeable <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in _TAX_BRACKETS:
        if chargeable <= lower:
            break
        band = min(chargeable, upper) - lower
        tax += band * rate
        lower = upper
    return tax

def calc_pcb(wage: float, tax_category: str, num_children: int, epf_employee_contribution: float) -> float:
    if wage <= 0:
        return 0.0
    annual_wage = wage * 12
    epf_relief = min(epf_employee_contribution * 12, 4000.0)
    personal_relief = 9000.0
    spouse_relief = 4000.0 if tax_category == "Married" else 0.0
    child_relief = max(num_children, 0) * 2000.0
    chargeable = max(0.0, annual_wage - epf_relief - personal_relief - spouse_relief - child_relief)
    annual_tax = _annual_tax(chargeable)
    return round(annual_tax / 12, 2)

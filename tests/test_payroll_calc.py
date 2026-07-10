"""
Unit tests for payroll_calc.py — pure functions, no DB/network involved.

This is the highest legal/compliance-risk code in the app (statutory
deductions) and previously had zero test coverage. These tests lock in the
*documented* simplified behavior so a future refactor can't silently change
the math without a test failing — they do not, and cannot, validate the
figures against real KWSP/PERKESO/LHDN tables (see the module docstring).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import payroll_calc as pc


class TestEpf:
    def test_zero_or_negative_wage_is_zero(self):
        assert pc.calc_epf(0) == {"employee": 0.0, "employer": 0.0}
        assert pc.calc_epf(-100) == {"employee": 0.0, "employer": 0.0}

    def test_employer_rate_at_or_below_5000(self):
        result = pc.calc_epf(5000)
        assert result["employee"] == 550.0   # 11%
        assert result["employer"] == 650.0   # 13%

    def test_employer_rate_above_5000(self):
        result = pc.calc_epf(5001)
        assert result["employee"] == round(5001 * 0.11, 2)
        assert result["employer"] == round(5001 * 0.12, 2)  # drops to 12%

    def test_rounds_to_2dp(self):
        result = pc.calc_epf(3333.33)
        assert result["employee"] == round(3333.33 * 0.11, 2)


class TestSocso:
    def test_zero_wage_is_zero(self):
        assert pc.calc_socso(0, 30) == {"employee": 0.0, "employer": 0.0}

    def test_under_60_category_1(self):
        result = pc.calc_socso(3000, 30)
        assert result["employee"] == round(3000 * 0.005, 2)
        assert result["employer"] == round(3000 * 0.0175, 2)

    def test_60_or_over_employer_only(self):
        result = pc.calc_socso(3000, 60)
        assert result["employee"] == 0.0
        assert result["employer"] == round(3000 * 0.0125, 2)

    def test_wage_ceiling_applied(self):
        below = pc.calc_socso(6000, 30)
        above = pc.calc_socso(10000, 30)
        assert above == below  # both capped at the RM6,000 ceiling


class TestEis:
    def test_zero_wage_is_zero(self):
        assert pc.calc_eis(0, 30) == {"employee": 0.0, "employer": 0.0}

    def test_under_18_exempt(self):
        assert pc.calc_eis(3000, 17) == {"employee": 0.0, "employer": 0.0}

    def test_60_or_over_exempt(self):
        assert pc.calc_eis(3000, 60) == {"employee": 0.0, "employer": 0.0}

    def test_normal_case(self):
        result = pc.calc_eis(3000, 30)
        assert result["employee"] == round(3000 * 0.002, 2)
        assert result["employer"] == round(3000 * 0.002, 2)

    def test_wage_ceiling_applied(self):
        below = pc.calc_eis(6000, 30)
        above = pc.calc_eis(10000, 30)
        assert above == below


class TestPcb:
    def test_zero_or_negative_wage_is_zero(self):
        assert pc.calc_pcb(0, "Single", 0, 0) == 0.0
        assert pc.calc_pcb(-500, "Single", 0, 0) == 0.0

    def test_low_wage_below_relief_threshold_is_zero_tax(self):
        # RM700/mo = RM8,400/yr, under the RM9,000 personal relief alone, so
        # chargeable income should floor at 0 even with no EPF contribution.
        assert pc.calc_pcb(700, "Single", 0, 0) == 0.0

    def test_married_reduces_tax_vs_single(self):
        single = pc.calc_pcb(8000, "Single", 0, 880)
        married = pc.calc_pcb(8000, "Married", 0, 880)
        assert married < single

    def test_children_reduce_tax(self):
        no_kids = pc.calc_pcb(8000, "Married", 0, 880)
        two_kids = pc.calc_pcb(8000, "Married", 2, 880)
        assert two_kids < no_kids

    def test_epf_relief_capped_at_4000_annually(self):
        # A contribution large enough that 12x it would exceed the RM4,000/yr
        # EPF relief cap — result should be identical to one right at the cap.
        at_cap = pc.calc_pcb(20000, "Single", 0, 4000 / 12)
        over_cap = pc.calc_pcb(20000, "Single", 0, 10000 / 12)
        assert at_cap == over_cap

    def test_higher_wage_never_produces_lower_tax(self):
        lower = pc.calc_pcb(5000, "Single", 0, 550)
        higher = pc.calc_pcb(15000, "Single", 0, 1650)
        assert higher >= lower

    def test_result_is_rounded_to_2dp(self):
        result = pc.calc_pcb(7777, "Single", 1, 855.47)
        assert result == round(result, 2)

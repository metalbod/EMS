"""Who may use a leave type.

A leave type can carry up to three conditions — a gender (e.g. Maternity = Female, Paternity = Male), "married staff only", and a
minimum length of service — and HR can make an exception for one named person either way. This module is the ONE place that answers
"may this person use this type, and if not why", so every screen and every endpoint (the types list, My Leave's cards, Home, Me,
the employee profile, the AI assistant, the Claude connector, applying, attendance reclassify) agrees by construction.

The default is no conditions: every type is open to everyone, exactly as before this existed.

Pure functions take plain dict-like rows (leave_types / employees / override) so they are testable without a database; the two
small loaders at the bottom fetch what they need in one query for a whole list.
"""
import calendar
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

GENDER_CHOICES = ("Any", "Male", "Female")

_GENDER_PHRASE = {"Male": "for male staff only", "Female": "for female staff only"}


def _to_date(v) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def add_months(d: date, months: int) -> date:
    """`d` plus whole months, clamped to the end of a short month (31 Jan + 1 month = 28/29 Feb)."""
    total = d.year * 12 + (d.month - 1) + months
    y, m = divmod(total, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def eligible_from(lt, emp) -> Optional[date]:
    """The first day the minimum-service condition is met (None when there is no minimum or no start date on file)."""
    months = int(lt["min_service_months"] or 0)
    start = _to_date(emp["start_date"])
    return add_months(start, months) if months and start else None


def ineligible_reason(lt, emp, on: date, override=None) -> Optional[str]:
    """Why `emp` may not use `lt` for leave starting `on` — a short phrase that completes "'<type>' isn't available: ..." — or None
    when they may. An HR exception wins over the three rules, whichever way it points."""
    if override is not None:
        return None if int(override["allowed"]) else "HR has withheld it"
    gender = (lt["eligible_gender"] or "Any")
    if gender != "Any" and (emp["gender"] or "") != gender:
        return _GENDER_PHRASE.get(gender, f"for {gender.lower()} staff only")
    if int(lt["require_married"] or 0) and (emp["marital_status"] or "") != "Married":
        return "for married staff only"
    months = int(lt["min_service_months"] or 0)
    if months:
        start = _to_date(emp["start_date"])
        if start is None:
            return f"only after {months} month{'s' if months != 1 else ''} of service (no start date on file)"
        ok_from = add_months(start, months)
        if on < ok_from:
            return f"only after {months} month{'s' if months != 1 else ''} of service (from {ok_from.strftime('%d-%b-%Y')})"
    return None


def is_eligible(lt, emp, on: date, override=None) -> bool:
    return ineligible_reason(lt, emp, on, override) is None


def has_rules(lt) -> bool:
    return (lt["eligible_gender"] or "Any") != "Any" or bool(int(lt["require_married"] or 0)) or int(lt["min_service_months"] or 0) > 0


def rule_badges(lt) -> List[str]:
    """Short labels for the leave type list: ['Female only', 'Married', '12+ months']."""
    out = []
    g = lt["eligible_gender"] or "Any"
    if g != "Any":
        out.append(f"{g} only")
    if int(lt["require_married"] or 0):
        out.append("Married")
    months = int(lt["min_service_months"] or 0)
    if months:
        out.append(f"{months}+ months")
    return out


# ---- loaders ---------------------------------------------------------------------------------------------------------------
def load_overrides(conn, inst_id: int, employee_ids: Optional[Iterable[str]] = None, type_ids: Optional[Iterable[int]] = None) -> Dict[Tuple[int, str], Any]:
    """{(leave_type_id, employee_id): row} for the given people and/or types (everyone's when both are None)."""
    q = "SELECT * FROM leave_type_eligibility_overrides WHERE institution_id=?"
    p: List[Any] = [inst_id]
    if employee_ids is not None:
        ids = list(employee_ids)
        if not ids:
            return {}
        q += f" AND employee_id IN ({','.join('?' * len(ids))})"
        p.extend(ids)
    if type_ids is not None:
        tids = list(type_ids)
        if not tids:
            return {}
        q += f" AND leave_type_id IN ({','.join('?' * len(tids))})"
        p.extend(tids)
    return {(r["leave_type_id"], r["employee_id"]): r for r in conn.execute(q, p).fetchall()}


def load_employees(conn, inst_id: int, employee_ids: Iterable[str]) -> Dict[str, Any]:
    ids = list(dict.fromkeys(employee_ids))
    if not ids:
        return {}
    rows = conn.execute(
        f"SELECT employee_id, gender, marital_status, start_date, status FROM employees WHERE institution_id=? AND employee_id IN ({','.join('?' * len(ids))})",
        [inst_id, *ids]).fetchall()
    return {r["employee_id"]: r for r in rows}


def eligible_type_rows(conn, inst_id: int, types: List[Any], emp_id: str, on: date) -> List[Any]:
    """`types` (leave_types rows) narrowed to those `emp_id` may use. An unknown employee gets nothing restricted."""
    emp = load_employees(conn, inst_id, [emp_id]).get(emp_id)
    ov = load_overrides(conn, inst_id, [emp_id], [t["id"] for t in types])
    if emp is None:
        return [t for t in types if not has_rules(t)]
    return [t for t in types if is_eligible(t, emp, on, ov.get((t["id"], emp_id)))]

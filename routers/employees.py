"""Employee routes (institution-scoped), plus Bulk Employee Upload (HR Manager only)."""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError, field_validator

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from core.org_queries import is_self_or_subordinate
except ImportError:
    from ems.core.org_queries import is_self_or_subordinate

try:
    from core.audit import write_audit
except ImportError:
    from ems.core.audit import write_audit

try:
    from core.validators import validate_logo_url
except ImportError:
    from ems.core.validators import validate_logo_url

try:
    from core.constants import RACES, RELIGIONS, GENDERS, MARITAL_STATUSES, EMPLOYMENT_TYPES, STATUSES
except ImportError:
    from ems.core.constants import RACES, RELIGIONS, GENDERS, MARITAL_STATUSES, EMPLOYMENT_TYPES, STATUSES

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

router = APIRouter()

CAN_WRITE  = ("superadmin", "hr_manager", "hr_admin")
CAN_TOGGLE = ("superadmin", "hr_manager")

SENSITIVE = {"bank_account", "income_tax_number", "socso_number", "epf_number"}
FIELD_LABELS = {
    "employee_id":"Employee ID",
    "full_name":"Full Name","preferred_name":"Preferred Name","ic_number":"IC Number",
    "passport_number":"Passport Number","nationality":"Nationality","race":"Race",
    "religion":"Religion","gender":"Gender","date_of_birth":"Date of Birth",
    "marital_status":"Marital Status","personal_email":"Personal Email","phone":"Phone",
    "address":"Address","department":"Department","designation":"Designation",
    "employment_type":"Employment Type","start_date":"Start Date",
    "probation_end_date":"Probation End Date","contract_end_date":"Contract End Date",
    "work_email":"Work Email","epf_number":"EPF Number","socso_number":"SOCSO Number",
    "income_tax_number":"Income Tax No.","bank_name":"Bank Name","bank_account":"Bank Account",
    "basic_salary":"Basic Salary","num_children":"No. of Children","salary_type":"Salary Type","hourly_rate":"Hourly Rate",
    "reports_to":"Reports To","status":"Status",
}


def diff_employee(old, new):
    out = []
    for f, label in FIELD_LABELS.items():
        ov, nv = str(old.get(f) or ""), str(new.get(f) or "")
        if ov != nv:
            out.append({"field":f,"label":label,
                        "old":"***" if f in SENSITIVE else ov,
                        "new":"***" if f in SENSITIVE else nv})
    return out


def write_employee_change_note(conn, inst_id, emp_id, actor, changes):
    """Mirror any employee record change into a General HR Note, so the change
    history is visible on the employee's profile, not just the Audit Log."""
    if not changes:
        return
    lines = [f'{c["label"]} changed from "{c["old"] or "—"}" to "{c["new"] or "—"}"' for c in changes]
    body = "Employee record updated — " + "; ".join(lines) + "."
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?,?,?,?,?)",
        (inst_id, emp_id, "general", body, actor["username"])
    )


class EmployeeIn(BaseModel):
    full_name: str
    preferred_name: Optional[str] = None
    ic_number: str
    passport_number: Optional[str] = None
    nationality: str = "Malaysian"
    race: Optional[str] = None
    religion: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    marital_status: Optional[str] = None
    personal_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    department: str
    designation: str
    employment_type: str
    start_date: str
    probation_end_date: Optional[str] = None
    contract_end_date: Optional[str] = None
    work_email: Optional[str] = None
    epf_number: Optional[str] = None
    socso_number: Optional[str] = None
    income_tax_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    basic_salary: float = 0.0
    num_children: int = 0  # for PCB (income tax) child relief
    salary_type: str = "Monthly"  # Monthly | Hourly
    hourly_rate: float = 0.0  # used when salary_type == "Hourly"
    reports_to: Optional[str] = None
    employee_id: Optional[str] = None  # HR Manager only — custom/renamed Employee ID

    @field_validator("salary_type")
    @classmethod
    def validate_salary_type(cls, v):
        if v not in ("Monthly", "Hourly"):
            raise ValueError("salary_type must be Monthly or Hourly")
        return v

    @field_validator("employee_id")
    @classmethod
    def validate_employee_id(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Employee ID cannot be blank")
        return v

    @field_validator("ic_number")
    @classmethod
    def validate_ic(cls, v):
        d = v.replace("-","").replace(" ","")
        if len(d)==12 and d.isdigit():
            return f"{d[:6]}-{d[6:8]}-{d[8:]}"
        raise ValueError("IC number must be 12 digits (e.g. 900101-14-1234)")

    @field_validator("race")
    @classmethod
    def validate_race(cls, v):
        if v not in RACES: raise ValueError(f"Race must be one of: {', '.join(RACES)}")
        return v

    @field_validator("religion")
    @classmethod
    def validate_religion(cls, v):
        if v not in RELIGIONS: raise ValueError(f"Religion must be one of: {', '.join(RELIGIONS)}")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v):
        if v not in GENDERS: raise ValueError("Gender must be Male or Female")
        return v

    @field_validator("marital_status")
    @classmethod
    def validate_marital(cls, v):
        if v not in MARITAL_STATUSES: raise ValueError(f"Marital status must be one of: {', '.join(MARITAL_STATUSES)}")
        return v

    @field_validator("employment_type")
    @classmethod
    def validate_emp_type(cls, v):
        if v not in EMPLOYMENT_TYPES: raise ValueError(f"Employment type must be one of: {', '.join(EMPLOYMENT_TYPES)}")
        return v

    @field_validator("basic_salary")
    @classmethod
    def validate_salary(cls, v):
        if v < 0: raise ValueError("Salary cannot be negative")
        return v


class BulkUploadIn(BaseModel):
    csv_content: str


class StatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def val(cls, v):
        if v not in STATUSES: raise ValueError("Status must be Active or Inactive")
        return v


def gen_employee_id(conn, inst_id: int) -> str:
    cnt = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE institution_id=?", (inst_id,)
    ).fetchone()[0]
    n = cnt + 1
    while True:
        eid = f"EMP{n:04d}"
        if not conn.execute(
            "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, eid)
        ).fetchone():
            return eid
        n += 1


@router.get("/api/employees")
def list_employees(
    status: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    inst_id = need_inst(user)
    conn = get_db()
    if user["role"] == "manager" and user.get("employee_id"):
        # Self + full downstream reporting chain (not just same-department peers)
        q = """
            WITH RECURSIVE subordinates AS (
                SELECT employee_id FROM employees WHERE institution_id=? AND employee_id=?
                UNION ALL
                SELECT e.employee_id FROM employees e
                JOIN subordinates s ON e.reports_to = s.employee_id
                WHERE e.institution_id=?
            )
            SELECT * FROM employees
            WHERE institution_id=? AND employee_id IN (SELECT employee_id FROM subordinates)
        """
        p = [inst_id, user["employee_id"], inst_id, inst_id]
    else:
        q = "SELECT * FROM employees WHERE institution_id=?"
        p = [inst_id]
        if user["role"] == "employee":
            q += " AND employee_id=?"; p.append(user["employee_id"])
    if status: q += " AND status=?"; p.append(status)
    if search and user["role"] != "employee":
        like = f"%{search}%"
        q += " AND (full_name LIKE ? OR employee_id LIKE ? OR ic_number LIKE ? OR designation LIKE ? OR department LIKE ?)"
        p.extend([like,like,like,like,like])
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/employees", status_code=201)
def _insert_new_employee(conn, inst_id, emp: EmployeeIn, user: dict, ip: Optional[str]):
    """Core employee-creation logic, shared by the single Add Employee form and bulk upload.
    Raises HTTPException on business-rule violations; lets IntegrityError propagate to the caller."""
    if emp.employee_id and user["role"] == "hr_manager":
        emp_id = emp.employee_id
        if conn.execute(
            "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, emp_id)
        ).fetchone():
            raise HTTPException(400, f"Employee ID '{emp_id}' is already in use in this institution")
    else:
        emp_id = gen_employee_id(conn, inst_id)
    reports_to = emp_id if emp.reports_to == "SELF" else emp.reports_to
    if reports_to and reports_to != emp_id:
        if not conn.execute(
            "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, reports_to)
        ).fetchone():
            raise HTTPException(400, f"Reporting manager '{reports_to}' not found")
    conn.execute("""
        INSERT INTO employees (
            institution_id, employee_id, full_name, preferred_name, ic_number, passport_number,
            nationality, race, religion, gender, date_of_birth, marital_status,
            personal_email, phone, address, department, designation, employment_type, start_date,
            probation_end_date, contract_end_date, work_email,
            epf_number, socso_number, income_tax_number, bank_name, bank_account, basic_salary, num_children,
            salary_type, hourly_rate, reports_to
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, emp_id, emp.full_name, emp.preferred_name, emp.ic_number, emp.passport_number,
          emp.nationality, emp.race or '', emp.religion or '', emp.gender or '', emp.date_of_birth or '', emp.marital_status or '',
          emp.personal_email, emp.phone, emp.address, emp.department, emp.designation,
          emp.employment_type, emp.start_date, emp.probation_end_date, emp.contract_end_date,
          emp.work_email, emp.epf_number, emp.socso_number, emp.income_tax_number,
          emp.bank_name, emp.bank_account, emp.basic_salary, emp.num_children,
          emp.salary_type, emp.hourly_rate, reports_to))
    write_audit(conn, user, inst_id, emp_id, emp.full_name, "CREATE", None, ip)
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?,?,?,?,?)",
        (inst_id, emp_id, "general", "Employee record created.", user["username"])
    )
    return emp_id


def create_employee(emp: EmployeeIn, request: Request, user: dict = Depends(require_roles(*CAN_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    # Enforce max_employees
    inst = conn.execute("SELECT max_employees FROM institutions WHERE id=?", (inst_id,)).fetchone()
    if inst:
        cnt = conn.execute("SELECT COUNT(*) FROM employees WHERE institution_id=?", (inst_id,)).fetchone()[0]
        if cnt >= inst["max_employees"]:
            conn.close()
            raise HTTPException(400, f"Employee limit ({inst['max_employees']}) reached for this institution")
    try:
        emp_id = _insert_new_employee(conn, inst_id, emp, user, request.client.host if request.client else None)
        conn.commit()
        row = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?",
                           (inst_id, emp_id)).fetchone()
        return dict(row)
    except IntegrityError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bulk Employee Upload (HR Manager only)
# ---------------------------------------------------------------------------
BULK_UPLOAD_ROLES = ("hr_manager",)

# Column order mirrors the single Add Employee form. Employee ID is optional —
# leave blank to auto-generate, or supply a custom one (HR Manager privilege).
BULK_UPLOAD_COLUMNS = [
    "employee_id", "full_name", "ic_number", "passport_number", "nationality",
    "race", "religion", "gender", "date_of_birth", "marital_status",
    "personal_email", "phone", "address", "department", "designation",
    "employment_type", "start_date", "probation_end_date", "contract_end_date", "work_email",
    "epf_number", "socso_number", "income_tax_number", "bank_name", "bank_account",
    "basic_salary", "num_children", "salary_type", "hourly_rate", "reports_to",
]
BULK_UPLOAD_REQUIRED = [
    "full_name", "ic_number", "race", "religion", "gender", "date_of_birth",
    "marital_status", "phone", "department", "designation", "employment_type", "start_date",
]


@router.get("/api/employees/bulk-template")
def download_bulk_template(user: dict = Depends(require_roles(*BULK_UPLOAD_ROLES))):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(BULK_UPLOAD_COLUMNS)
    example = {
        "employee_id": "", "full_name": "Jane Tan", "ic_number": "900101-14-1234", "passport_number": "",
        "nationality": "Malaysian", "race": RACES[0], "religion": RELIGIONS[0], "gender": "Female",
        "date_of_birth": "1990-01-01", "marital_status": "Single", "personal_email": "jane@example.com",
        "phone": "+60123456789", "address": "", "department": "Sales", "designation": "Sales Executive",
        "employment_type": "Permanent", "start_date": "2026-01-01", "probation_end_date": "", "contract_end_date": "",
        "work_email": "", "epf_number": "", "socso_number": "", "income_tax_number": "", "bank_name": "",
        "bank_account": "", "basic_salary": "3500", "num_children": "0", "salary_type": "Monthly",
        "hourly_rate": "0", "reports_to": "",
    }
    writer.writerow([example[c] for c in BULK_UPLOAD_COLUMNS])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=employee-bulk-upload-template.csv"})


@router.post("/api/employees/bulk-upload")
def bulk_upload_employees(body: BulkUploadIn, request: Request, user: dict = Depends(require_roles(*BULK_UPLOAD_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    inst = conn.execute("SELECT max_employees FROM institutions WHERE id=?", (inst_id,)).fetchone()
    existing_count = conn.execute("SELECT COUNT(*) FROM employees WHERE institution_id=?", (inst_id,)).fetchone()[0]

    reader = csv.DictReader(io.StringIO(body.csv_content))
    missing_cols = [c for c in BULK_UPLOAD_REQUIRED if c not in (reader.fieldnames or [])]
    if missing_cols:
        conn.close()
        raise HTTPException(400, f"CSV is missing required column(s): {', '.join(missing_cols)}")

    created, errors = [], []
    ip = request.client.host if request.client else None
    for i, raw_row in enumerate(reader, start=2):  # row 1 is the header
        row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items()}
        if not any(row.values()):
            continue  # skip fully blank rows
        try:
            payload = {c: (row.get(c) or None) for c in BULK_UPLOAD_COLUMNS}
            if payload.get("basic_salary") in (None, ""): payload["basic_salary"] = 0
            if payload.get("num_children") in (None, ""): payload["num_children"] = 0
            if payload.get("hourly_rate") in (None, ""): payload["hourly_rate"] = 0
            if payload.get("salary_type") in (None, ""): payload["salary_type"] = "Monthly"
            if payload.get("nationality") in (None, ""): payload["nationality"] = "Malaysian"
            payload["basic_salary"] = float(payload["basic_salary"])
            payload["num_children"] = int(float(payload["num_children"]))
            payload["hourly_rate"] = float(payload["hourly_rate"])
            emp = EmployeeIn(**payload)
            if existing_count >= (inst["max_employees"] if inst else 10**9):
                errors.append({"row": i, "reason": f"Employee limit ({inst['max_employees']}) reached for this institution"})
                continue
            emp_id = _insert_new_employee(conn, inst_id, emp, user, ip)
            conn.commit()
            existing_count += 1
            created.append({"row": i, "employee_id": emp_id, "full_name": emp.full_name})
        except ValidationError as e:
            conn.rollback()
            reasons = "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
            errors.append({"row": i, "reason": reasons})
        except (ValueError, TypeError) as e:
            conn.rollback()
            errors.append({"row": i, "reason": str(e)})
        except HTTPException as e:
            conn.rollback()
            errors.append({"row": i, "reason": e.detail})
        except IntegrityError as e:
            conn.rollback()
            errors.append({"row": i, "reason": str(e)})
    conn.close()
    return {"created": created, "errors": errors}


@router.get("/api/employees/{employee_id}")
def get_employee(employee_id: str, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "employee" and user["employee_id"] != employee_id:
        raise HTTPException(403, "Access denied")
    conn = get_db()
    if user["role"] == "manager" and not is_self_or_subordinate(conn, inst_id, user.get("employee_id"), employee_id):
        conn.close(); raise HTTPException(403, "Access denied")
    row = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Employee not found")
    return dict(row)


@router.put("/api/employees/{employee_id}")
def update_employee(employee_id: str, emp: EmployeeIn, request: Request,
                    user: dict = Depends(require_roles(*CAN_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    old_row = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    if not old_row: conn.close(); raise HTTPException(404, "Employee not found")
    old = dict(old_row)
    try:
        new_id = employee_id
        if emp.employee_id and emp.employee_id != employee_id:
            if user["role"] != "hr_manager":
                raise HTTPException(403, "Only the HR Manager role can change Employee ID")
            new_id = emp.employee_id
            if conn.execute(
                "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, new_id)
            ).fetchone():
                raise HTTPException(400, f"Employee ID '{new_id}' is already in use in this institution")
            # employee_id is a soft key referenced (as plain TEXT, no DB-level FK) across many
            # tables — rename it everywhere in one transaction so nothing gets silently orphaned.
            conn.execute("UPDATE employees SET employee_id=? WHERE institution_id=? AND employee_id=?", (new_id, inst_id, employee_id))
            conn.execute("UPDATE employees SET reports_to=? WHERE institution_id=? AND reports_to=?", (new_id, inst_id, employee_id))
            conn.execute("UPDATE users SET employee_id=? WHERE institution_id=? AND employee_id=?", (new_id, inst_id, employee_id))
            conn.execute("UPDATE audit_logs SET target_employee_id=? WHERE institution_id=? AND target_employee_id=?", (new_id, inst_id, employee_id))
            for tbl in ("ob_audit_log", "hr_notes", "ob_checklists", "ld_enrollments", "ld_audit_log",
                        "ld_quiz_attempts", "ld_lesson_progress", "leave_balances", "leave_applications",
                        "leave_audit_log", "timesheets", "timesheet_audit_log", "task_assignments"):
                conn.execute(f"UPDATE {tbl} SET employee_id=? WHERE institution_id=? AND employee_id=?", (new_id, inst_id, employee_id))

        reports_to = new_id if emp.reports_to == "SELF" else emp.reports_to
        if reports_to and reports_to != new_id:
            if not conn.execute(
                "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, reports_to)
            ).fetchone():
                raise HTTPException(400, f"Reporting manager '{reports_to}' not found")
        conn.execute("""
            UPDATE employees SET
                full_name=?,preferred_name=?,ic_number=?,passport_number=?,
                nationality=?,race=?,religion=?,gender=?,date_of_birth=?,marital_status=?,
                personal_email=?,phone=?,address=?,department=?,designation=?,employment_type=?,
                start_date=?,probation_end_date=?,contract_end_date=?,work_email=?,
                epf_number=?,socso_number=?,income_tax_number=?,bank_name=?,bank_account=?,
                basic_salary=?,num_children=?,salary_type=?,hourly_rate=?,reports_to=?
            WHERE institution_id=? AND employee_id=?
        """, (emp.full_name, emp.preferred_name, emp.ic_number, emp.passport_number,
              emp.nationality, emp.race, emp.religion, emp.gender, emp.date_of_birth,
              emp.marital_status, emp.personal_email, emp.phone, emp.address,
              emp.department, emp.designation, emp.employment_type, emp.start_date,
              emp.probation_end_date, emp.contract_end_date, emp.work_email,
              emp.epf_number, emp.socso_number, emp.income_tax_number,
              emp.bank_name, emp.bank_account, emp.basic_salary, emp.num_children,
              emp.salary_type, emp.hourly_rate, reports_to,
              inst_id, new_id))
        new_row = conn.execute(
            "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, new_id)
        ).fetchone()
        changes = diff_employee(old, dict(new_row))
        write_audit(conn, user, inst_id, new_id, emp.full_name, "UPDATE", changes,
                    request.client.host if request.client else None)
        write_employee_change_note(conn, inst_id, new_id, user, changes)
        conn.commit()
        return dict(new_row)
    except IntegrityError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.patch("/api/employees/{employee_id}/status")
def update_status(employee_id: str, body: StatusUpdate, request: Request,
                  user: dict = Depends(require_roles(*CAN_TOGGLE))):
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    if not row: conn.close(); raise HTTPException(404, "Employee not found")
    old = dict(row)
    conn.execute("UPDATE employees SET status=? WHERE institution_id=? AND employee_id=?",
                 (body.status, inst_id, employee_id))
    action = "ACTIVATE" if body.status == "Active" else "DEACTIVATE"
    status_change = [{"field":"status","label":"Status","old":old["status"],"new":body.status}]
    write_audit(conn, user, inst_id, employee_id, row["full_name"], action,
                status_change, request.client.host if request.client else None)
    write_employee_change_note(conn, inst_id, employee_id, user, status_change)
    conn.commit()
    result = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    conn.close()
    return dict(result)


# ---------------------------------------------------------------------------
# Employee-record-linked routes (rehire, related contracts) also live here —
# these are Employee-module concerns even though they were interleaved with
# the Onboarding section in the original monolith.
# ---------------------------------------------------------------------------
@router.get("/api/employees/{employee_id}/related-contracts")
def get_related_contracts(employee_id: str, user: dict = Depends(get_current_user)):
    """Return all employment contracts for the same person (matched by IC number)."""
    inst_id = need_inst(user)
    conn = get_db()
    target = conn.execute(
        "SELECT ic_number FROM employees WHERE employee_id=? AND institution_id=?",
        (employee_id, inst_id)
    ).fetchone()
    if not target:
        conn.close(); raise HTTPException(404, "Employee not found")
    rows = conn.execute(
        """SELECT employee_id, full_name, employment_type, designation, department,
                  start_date, contract_end_date, status, created_at
           FROM employees
           WHERE ic_number=? AND institution_id=? AND employee_id!=?
           ORDER BY start_date DESC""",
        (target["ic_number"], inst_id, employee_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/employees/{employee_id}/rehire-prefill")
def rehire_prefill(employee_id: str, user: dict = Depends(require_roles(*CAN_WRITE))):
    """Pre-fill personal details for a rehire from an existing employee record."""
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
        (employee_id, inst_id)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Employee not found")
    r = dict(row)
    return {
        "full_name": r["full_name"], "preferred_name": r["preferred_name"],
        "ic_number": r["ic_number"], "passport_number": r["passport_number"],
        "nationality": r["nationality"], "race": r["race"], "religion": r["religion"],
        "gender": r["gender"], "date_of_birth": r["date_of_birth"],
        "marital_status": r["marital_status"], "personal_email": r["personal_email"],
        "phone": r["phone"], "address": r["address"],
        "previous_employee_id": employee_id,
    }

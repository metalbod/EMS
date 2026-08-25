"""Async task definitions and Celery configuration."""
import os
import re
import logging
import json
from datetime import date
from celery import Celery
from celery.result import AsyncResult

logger = logging.getLogger("ems")

BULK_UPLOAD_DATE_COLUMNS = ("date_of_birth", "start_date", "probation_end_date", "contract_end_date")


def _detect_bulk_upload_date_format(samples):
    """Infer whether ambiguous numeric dates in a bulk-upload CSV are D/M/Y, M/D/Y, or Y/M/D.

    Looks at every date value in the file together, not row by row, since a single
    upload is assumed to come from one export with one consistent format throughout.
    A value with a 4-digit or >31 first part is treated as Y/M/D; otherwise, the
    first ambiguous value where one of the first two parts is a plausible day
    (13-31) pins down D/M/Y vs M/D/Y. A value that doesn't fit any real date
    (e.g. "45/13/1983") is skipped rather than treated as a signal, so one bad
    row in an otherwise-consistent file can't corrupt detection for every other
    row. Defaults to D/M/Y if every value is fully ambiguous (day and month
    both <=12), matching this system's local convention.
    """
    day_position = None
    for s in samples:
        if not s:
            continue
        parts = re.split(r"[/\-]", s.strip())
        if len(parts) != 3:
            continue
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            continue
        if len(parts[0]) == 4:
            return "YMD"
        # Only a signal if exactly one of the two positions can be a day
        # (13-31) while the other still fits as a month (1-12) — e.g. "45/13"
        # fits neither reading and must be skipped rather than misread.
        if 13 <= nums[0] <= 31 and 1 <= nums[1] <= 12:
            day_position = 0
            break
        if 13 <= nums[1] <= 31 and 1 <= nums[0] <= 12:
            day_position = 1
            break
    return "MDY" if day_position == 1 else "DMY"


def _normalize_bulk_upload_date(value, fmt):
    """Convert a raw CSV date string to the ISO YYYY-MM-DD format the rest of the
    app stores dates in, using the file-wide format detected by
    _detect_bulk_upload_date_format."""
    if not value:
        return value
    value = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value  # already ISO
    parts = re.split(r"[/\-]", value)
    if len(parts) != 3:
        raise ValueError(f"Unrecognized date '{value}' (expected D/M/Y, M/D/Y, or Y/M/D)")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValueError(f"Unrecognized date '{value}' (expected D/M/Y, M/D/Y, or Y/M/D)")
    if fmt == "YMD":
        y, m, d = nums
    elif fmt == "MDY":
        m, d, y = nums
    else:
        d, m, y = nums
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        raise ValueError(f"Invalid date '{value}' (detected file format: {fmt})")

# Redis connection string: redis://[:password]@host:port/db
# Default for local dev: redis://localhost:6379/0
# CELERY_TASK_ALWAYS_EAGER is set to true in *production* (ems-app's Fly
# secrets), not just for tests — there's no Redis instance or separate
# worker machine deployed at all (see README.md's "Async Operations >
# Production Deployment"). Eager mode skips the broker/backend since
# results are available immediately, in-process.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"

# In eager mode, tasks execute immediately and return directly (no need for a broker/backend).
# Use a dummy broker/backend to avoid connection attempts. A real Redis broker is only
# actually used when ALWAYS_EAGER is false, e.g. local dev with `redis-server` running —
# production today runs eager, not Redis-backed (see comment above).
BROKER_URL = "memory://" if ALWAYS_EAGER else REDIS_URL
BACKEND_URL = "cache+memory://" if ALWAYS_EAGER else REDIS_URL

app = Celery(
    "ems",
    broker=BROKER_URL,
    backend=BACKEND_URL,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minute hard limit
    task_soft_time_limit=25 * 60,  # 25 minute soft limit (send SIGTERM)
    worker_prefetch_multiplier=1,  # Process one task at a time
    task_always_eager=ALWAYS_EAGER,
    task_eager_propagates=ALWAYS_EAGER,
    task_store_eager_result=ALWAYS_EAGER,  # Store results for eager tasks so AsyncResult works
)


@app.task(bind=True)
def generate_payroll_run(self, inst_id: int, run_id: int, period_start: str, period_end: str):
    """Generate payslips for all active employees in a payroll run (async)."""
    try:
        from db import get_db, IntegrityError

        import payroll_calc

        from routers.payroll import _generate_payslip

        logger.info(f"Task {self.request.id}: generating payslips for run {run_id}, period {period_start} to {period_end}")

        conn = get_db()
        try:
            employees = conn.execute(
                "SELECT * FROM employees WHERE institution_id=? AND status='Active'",
                (inst_id,)
            ).fetchall()

            for emp in employees:
                _generate_payslip(conn, inst_id, run_id, emp, period_start, period_end)

            conn.commit()

            # Get final run for result
            run = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (run_id,)).fetchone()
            result = {
                "run_id": run["id"],
                "status": run["status"],
                "employee_count": len(employees),
                "period_start": run["period_start"],
                "period_end": run["period_end"],
            }
            logger.info(f"Task {self.request.id}: completed with {len(employees)} payslips")
            return result
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Task {self.request.id}: failed with error: {e}")
        raise


@app.task(bind=True)
def bulk_upload_employees_task(self, inst_id: int, csv_content: str, user_id: int, username: str, role: str):
    """Bulk upload employees from CSV content (async). Returns dict with created/errors."""
    try:
        import csv
        import io
        from pydantic import ValidationError
        from fastapi import HTTPException

        from db import get_db, IntegrityError

        from routers.employees import (
            _insert_new_employee, _update_bulk_employee, BULK_UPLOAD_REQUIRED, BULK_UPLOAD_COLUMNS, EmployeeIn
        )

        logger.info(f"Task {self.request.id}: bulk uploading employees for institution {inst_id}")

        conn = get_db()
        try:
            inst = conn.execute("SELECT max_employees FROM institutions WHERE id=?", (inst_id,)).fetchone()
            existing_count = conn.execute("SELECT COUNT(*) FROM employees WHERE institution_id=?", (inst_id,)).fetchone()[0]

            reader = csv.DictReader(io.StringIO(csv_content))
            missing_cols = [c for c in BULK_UPLOAD_REQUIRED if c not in (reader.fieldnames or [])]
            if missing_cols:
                return {"created": [], "errors": [{"row": 0, "reason": f"CSV is missing required column(s): {', '.join(missing_cols)}"}]}

            all_rows = list(reader)
            date_samples = [
                row.get(col) for row in all_rows for col in BULK_UPLOAD_DATE_COLUMNS if row.get(col)
            ]
            date_format = _detect_bulk_upload_date_format(date_samples)

            created, updated, errors = [], [], []
            actor = {"id": user_id, "username": username, "role": role}
            for i, raw_row in enumerate(all_rows, start=2):  # row 1 is the header
                row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items()}
                if not any(row.values()):
                    continue  # skip fully blank rows
                # Captured before validation so a failed row is still identifiable
                # in the error list even if EmployeeIn itself rejects the row.
                row_identity = {"employee_id": row.get("employee_id") or None, "full_name": row.get("full_name") or None}
                try:
                    payload = {c: (row.get(c) or None) for c in BULK_UPLOAD_COLUMNS}
                    for col in BULK_UPLOAD_DATE_COLUMNS:
                        if payload.get(col):
                            payload[col] = _normalize_bulk_upload_date(payload[col], date_format)
                    if payload.get("basic_salary") in (None, ""): payload["basic_salary"] = 0
                    if payload.get("num_children") in (None, ""): payload["num_children"] = 0
                    if payload.get("hourly_rate") in (None, ""): payload["hourly_rate"] = 0
                    if payload.get("salary_type") in (None, ""): payload["salary_type"] = "Monthly"
                    if payload.get("nationality") in (None, ""): payload["nationality"] = "Malaysian"
                    payload["basic_salary"] = float(payload["basic_salary"])
                    payload["num_children"] = int(float(payload["num_children"]))
                    payload["hourly_rate"] = float(payload["hourly_rate"])
                    emp = EmployeeIn(**payload)

                    # A row whose employee_id already exists in this institution
                    # updates that record instead of erroring — lets HR re-upload
                    # the same roster (e.g. an HRIS export) to apply changes in
                    # bulk, same as re-submitting the single Edit Employee form.
                    existing = conn.execute(
                        "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, emp.employee_id)
                    ).fetchone() if emp.employee_id else None
                    if existing:
                        emp_id = _update_bulk_employee(conn, inst_id, emp.employee_id, emp, actor, None)
                        conn.commit()
                        updated.append({"row": i, "employee_id": emp_id, "full_name": emp.full_name})
                        continue

                    if existing_count >= (inst["max_employees"] if inst else 10**9):
                        errors.append({**row_identity, "row": i, "reason": f"Employee limit ({inst['max_employees']}) reached for this institution"})
                        continue
                    max_attempts = 5 if not emp.employee_id else 1
                    for attempt in range(max_attempts):
                        try:
                            emp_id = _insert_new_employee(conn, inst_id, emp, actor, None)
                            conn.commit()
                            break
                        except IntegrityError as e:
                            conn.rollback()
                            if "employees_institution_id_employee_id_key" in str(e) and attempt < max_attempts - 1:
                                continue
                            raise
                    existing_count += 1
                    created.append({"row": i, "employee_id": emp_id, "full_name": emp.full_name})
                except ValidationError as e:
                    conn.rollback()
                    reasons = "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
                    errors.append({**row_identity, "row": i, "reason": reasons})
                except HTTPException as e:
                    conn.rollback()
                    errors.append({**row_identity, "row": i, "reason": e.detail})
                except (ValueError, TypeError) as e:
                    conn.rollback()
                    errors.append({**row_identity, "row": i, "reason": str(e)})
                except IntegrityError as e:
                    conn.rollback()
                    errors.append({**row_identity, "row": i, "reason": str(e)})

            result = {
                "created": created, "updated": updated, "errors": errors,
                "summary": f"{len(created)} created, {len(updated)} updated, {len(errors)} errors",
            }
            logger.info(f"Task {self.request.id}: completed with {len(created)} created, {len(updated)} updated, {len(errors)} errors")
            return result
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Task {self.request.id}: failed with error: {e}")
        raise


# Base async task for long-running operations
@app.task(bind=True)
def long_running_task(self, task_type: str, payload: dict):
    """Base template for async tasks. Override in specific task functions."""
    logger.info(f"Task {self.request.id} ({task_type}) started with payload: {payload}")
    # Subclasses will override this
    return {"status": "completed", "result": None}


def get_task_status(task_id: str) -> dict:
    """Get the status of a task by ID."""
    result = AsyncResult(task_id, app=app)
    return {
        "id": task_id,
        "status": result.status,
        "result": result.result if result.status == "SUCCESS" else None,
        "error": str(result.info) if result.status == "FAILURE" else None,
    }

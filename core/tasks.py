"""Async task definitions and Celery configuration."""
import os
import logging
import json
from celery import Celery
from celery.result import AsyncResult

logger = logging.getLogger("ems")

# Redis connection string: redis://[:password]@host:port/db
# Default for local dev: redis://localhost:6379/0
# In test mode with CELERY_TASK_ALWAYS_EAGER, skip broker/backend since results are immediate
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"

# In eager mode, tasks execute immediately and return directly (no need for a broker/backend).
# Use a dummy broker/backend to avoid connection attempts. In production, Redis is used.
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
        try:
            from db import get_db, IntegrityError
        except ImportError:
            from ems.db import get_db, IntegrityError

        try:
            import payroll_calc
        except ImportError:
            from ems import payroll_calc

        try:
            from routers.payroll import _generate_payslip
        except ImportError:
            from ems.routers.payroll import _generate_payslip

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
def bulk_upload_employees_task(self, inst_id: int, csv_content: str, username: str):
    """Bulk upload employees from CSV content (async). Returns dict with created/errors."""
    try:
        import csv
        import io
        from pydantic import ValidationError

        try:
            from db import get_db, IntegrityError
        except ImportError:
            from ems.db import get_db, IntegrityError

        try:
            from routers.employees import (
                _insert_new_employee, BULK_UPLOAD_REQUIRED, BULK_UPLOAD_COLUMNS, EmployeeIn
            )
        except ImportError:
            from ems.routers.employees import (
                _insert_new_employee, BULK_UPLOAD_REQUIRED, BULK_UPLOAD_COLUMNS, EmployeeIn
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

            created, errors = [], []
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
                    max_attempts = 5 if not emp.employee_id else 1
                    for attempt in range(max_attempts):
                        try:
                            emp_id = _insert_new_employee(conn, inst_id, emp, {"username": username}, None)
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
                    errors.append({"row": i, "reason": reasons})
                except (ValueError, TypeError) as e:
                    conn.rollback()
                    errors.append({"row": i, "reason": str(e)})
                except IntegrityError as e:
                    conn.rollback()
                    errors.append({"row": i, "reason": str(e)})

            result = {"created": created, "errors": errors, "summary": f"{len(created)} created, {len(errors)} errors"}
            logger.info(f"Task {self.request.id}: completed with {len(created)} employees created, {len(errors)} errors")
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

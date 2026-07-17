"""Async task definitions and Celery configuration."""
import os
import logging
import json
from celery import Celery
from celery.result import AsyncResult

logger = logging.getLogger("ems")

# Redis connection string: redis://[:password]@host:port/db
# Default for local dev: redis://localhost:6379/0
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "ems",
    broker=REDIS_URL,
    backend=REDIS_URL,
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

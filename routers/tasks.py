"""Task tracking and status endpoints for async operations."""
from fastapi import APIRouter, HTTPException, Depends

try:
    from core.deps import require_roles
    from core.schemas import ErrorResponse
    from core.tasks import get_task_status
    from db import get_db
except ImportError:
    from ems.core.deps import require_roles
    from ems.core.schemas import ErrorResponse
    from ems.core.tasks import get_task_status
    from ems.db import get_db

router = APIRouter()


class TaskStatusResponse:
    """Task status response model."""
    pass


@router.get("/api/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: str, user: dict = Depends(require_roles("employee", "hr_manager", "hr_admin", "payroll_manager", "superadmin"))):
    """Get the status of an async task.

    Returns:
    - status: pending, started, success, failure
    - result: task output (when status is success)
    - error: error message (when status is failure)
    """
    # Get from Celery backend
    status = get_task_status(task_id)

    # Optionally: verify task belongs to this user (future: read from task_tracking table)
    # For now, any authenticated user can check any task ID

    return status

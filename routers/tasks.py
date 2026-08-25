"""Task tracking and status endpoints for async operations."""
from fastapi import APIRouter, HTTPException, Depends

from core.deps import get_current_user
from core.db_session import db_session
from core.schemas import ErrorResponse
from core.tasks import get_task_status

router = APIRouter()

_TASK_HR_TIER_ROLES = ("hr_manager", "hr_admin", "payroll_manager", "superadmin")


class TaskStatusResponse:
    """Task status response model."""
    pass


@router.get("/api/tasks/{task_id}", tags=["tasks"])
@db_session
def get_task(conn, task_id: str, user: dict = Depends(get_current_user)):
    """Get the status of an async task.

    Returns:
    - status: pending, started, success, failure
    - result: task output (when status is success)
    - error: error message (when status is failure)
    """
    track = conn.execute("SELECT user_id FROM task_tracking WHERE id=?", (task_id,)).fetchone()

    # No tracking row (e.g. a task predating this table, or an untracked
    # task type) means ownership can't be verified — only HR-tier roles may
    # blind-guess a task ID in that case. A tracked task additionally allows
    # its own creator.
    is_owner = track is not None and track["user_id"] == user["id"]
    if not is_owner and user["role"] not in _TASK_HR_TIER_ROLES:
        raise HTTPException(403, detail="Not authorized to view this task")

    return get_task_status(task_id)

"""Static reference-data endpoint for frontend dropdowns/labels."""
from fastapi import APIRouter, Depends

try:
    from core.deps import get_current_user
except ImportError:
    from ems.core.deps import get_current_user

try:
    from core.roles import ROLES
except ImportError:
    from ems.core.roles import ROLES

try:
    from core.constants import (
        RACES, RELIGIONS, GENDERS, MARITAL_STATUSES, EMPLOYMENT_TYPES, STATUSES, BANKS,
        INSTITUTION_ROLES, ROLE_LABELS, PLANS, PLAN_LABELS,
    )
except ImportError:
    from ems.core.constants import (
        RACES, RELIGIONS, GENDERS, MARITAL_STATUSES, EMPLOYMENT_TYPES, STATUSES, BANKS,
        INSTITUTION_ROLES, ROLE_LABELS, PLANS, PLAN_LABELS,
    )

router = APIRouter()


@router.get("/api/meta")
def get_meta(user: dict = Depends(get_current_user)):
    return {
        "races": RACES, "religions": RELIGIONS, "genders": GENDERS,
        "marital_statuses": MARITAL_STATUSES, "employment_types": EMPLOYMENT_TYPES,
        "statuses": STATUSES, "banks": BANKS, "roles": ROLES,
        "institution_roles": INSTITUTION_ROLES,
        "role_labels": ROLE_LABELS, "plans": PLANS, "plan_labels": PLAN_LABELS,
    }

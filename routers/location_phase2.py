"""API endpoints for Phase 2 location features: transfers, payroll dashboards, trends."""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.location_features_schemas import (
    LocationTransferResponse,
    LocationPayrollSummary,
    LocationPayrollDetail,
    EmployeesByDepartmentReport,
)

logger = logging.getLogger("ems.location_phase2")
router = APIRouter(prefix="/api", tags=["location-phase2"])


# ============================================================================
# LOCATION TRANSFER WORKFLOW ENDPOINTS
# ============================================================================

@router.post("/employees/{employee_id}/transfer-request", status_code=201)
async def request_location_transfer(
    employee_id: str,
    to_location_id: int,
    transfer_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> LocationTransferResponse:
    """Request a location transfer for an employee."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")
        user_id = current_user.get("id")

        # Verify employee exists
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()

        if not employee:
            raise HTTPException(404, detail="Employee not found")

        # Verify target location exists
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (to_location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Target location not found")

        # Get current location
        current_assignment = conn.execute(
            """
            SELECT location_id FROM employee_location_assignments
            WHERE employee_id = ? AND institution_id = ? AND is_active = 1 AND assignment_type = 'primary'
            """,
            (employee_id, inst_id),
        ).fetchone()

        from_location_id = current_assignment["location_id"] if current_assignment else None

        # Create transfer request
        transfer_date = transfer_date or datetime.utcnow().date().isoformat()
        conn.execute(
            """
            INSERT INTO location_transfers (institution_id, employee_id, from_location_id, to_location_id,
                                           transfer_date, status, requested_by_user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?)
            """,
            (inst_id, employee_id, from_location_id, to_location_id, transfer_date, user_id,
             datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
        )
        conn.commit()

        transfer_id = conn._last_id

        return LocationTransferResponse(
            id=transfer_id,
            employee_id=employee_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            transfer_date=transfer_date,
            status="Pending",
            requested_by_user_id=user_id,
            approved_by_user_id=None,
            rejection_reason=None,
            created_at=datetime.utcnow().isoformat(),
        )

    finally:
        conn.close()


@router.get("/employees/{employee_id}/transfer-requests")
async def get_employee_transfer_requests(
    employee_id: str,
    current_user: dict = Depends(get_current_user),
) -> List[LocationTransferResponse]:
    """Get all transfer requests for an employee."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify employee exists
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()

        if not employee:
            raise HTTPException(404, detail="Employee not found")

        # Get transfer requests
        transfers = conn.execute(
            """
            SELECT * FROM location_transfers
            WHERE employee_id = ? AND institution_id = ?
            ORDER BY created_at DESC
            """,
            (employee_id, inst_id),
        ).fetchall()

        return [
            LocationTransferResponse(
                id=t["id"],
                employee_id=t["employee_id"],
                from_location_id=t["from_location_id"],
                to_location_id=t["to_location_id"],
                transfer_date=t["transfer_date"],
                status=t["status"],
                requested_by_user_id=t["requested_by_user_id"],
                approved_by_user_id=t["approved_by_user_id"],
                rejection_reason=t["rejection_reason"],
                created_at=t["created_at"],
            )
            for t in transfers
        ]

    finally:
        conn.close()


@router.put("/transfer-requests/{transfer_id}/approve", status_code=200)
async def approve_transfer_request(
    transfer_id: int,
    current_user: dict = Depends(get_current_user),
) -> LocationTransferResponse:
    """Approve a location transfer request."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")
        user_id = current_user.get("id")

        # Get transfer request
        transfer = conn.execute(
            "SELECT * FROM location_transfers WHERE id = ? AND institution_id = ?",
            (transfer_id, inst_id),
        ).fetchone()

        if not transfer:
            raise HTTPException(404, detail="Transfer request not found")

        if transfer["status"] != "Pending":
            raise HTTPException(400, detail=f"Cannot approve transfer with status: {transfer['status']}")

        # Update transfer status
        conn.execute(
            """
            UPDATE location_transfers
            SET status = 'Approved', approved_by_user_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (user_id, datetime.utcnow().isoformat(), transfer_id),
        )

        # If transfer_date is today or earlier, mark as Completed and update assignments
        transfer_date_str = transfer["transfer_date"] if isinstance(transfer["transfer_date"], str) else transfer["transfer_date"].isoformat()
        if transfer_date_str <= datetime.utcnow().date().isoformat():
            # End old assignment
            if transfer["from_location_id"]:
                conn.execute(
                    """
                    UPDATE employee_location_assignments
                    SET is_active = 0, ended_by_user_id = ?, end_reason = 'Location Transfer'
                    WHERE employee_id = ? AND location_id = ? AND is_active = 1
                    """,
                    (user_id, transfer["employee_id"], transfer["from_location_id"]),
                )

            # Create new assignment
            conn.execute(
                """
                INSERT INTO employee_location_assignments
                (institution_id, employee_id, location_id, assignment_type, start_date, is_active)
                VALUES (?, ?, ?, 'primary', ?, 1)
                """,
                (inst_id, transfer["employee_id"], transfer["to_location_id"],
                 datetime.utcnow().date().isoformat()),
            )

            conn.execute(
                "UPDATE location_transfers SET status = 'Completed' WHERE id = ?",
                (transfer_id,),
            )

        conn.commit()

        # Fetch updated transfer
        updated_transfer = conn.execute(
            "SELECT * FROM location_transfers WHERE id = ?",
            (transfer_id,),
        ).fetchone()

        return LocationTransferResponse(
            id=updated_transfer["id"],
            employee_id=updated_transfer["employee_id"],
            from_location_id=updated_transfer["from_location_id"],
            to_location_id=updated_transfer["to_location_id"],
            transfer_date=updated_transfer["transfer_date"],
            status=updated_transfer["status"],
            requested_by_user_id=updated_transfer["requested_by_user_id"],
            approved_by_user_id=updated_transfer["approved_by_user_id"],
            rejection_reason=updated_transfer["rejection_reason"],
            created_at=updated_transfer["created_at"],
        )

    finally:
        conn.close()


@router.put("/transfer-requests/{transfer_id}/reject", status_code=200)
async def reject_transfer_request(
    transfer_id: int,
    reason: str,
    current_user: dict = Depends(get_current_user),
) -> LocationTransferResponse:
    """Reject a location transfer request."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")
        user_id = current_user.get("id")

        # Get transfer request
        transfer = conn.execute(
            "SELECT * FROM location_transfers WHERE id = ? AND institution_id = ?",
            (transfer_id, inst_id),
        ).fetchone()

        if not transfer:
            raise HTTPException(404, detail="Transfer request not found")

        if transfer["status"] != "Pending":
            raise HTTPException(400, detail=f"Cannot reject transfer with status: {transfer['status']}")

        # Update transfer status
        conn.execute(
            """
            UPDATE location_transfers
            SET status = 'Rejected', approved_by_user_id = ?, rejection_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (user_id, reason, datetime.utcnow().isoformat(), transfer_id),
        )
        conn.commit()

        # Fetch updated transfer
        updated_transfer = conn.execute(
            "SELECT * FROM location_transfers WHERE id = ?",
            (transfer_id,),
        ).fetchone()

        return LocationTransferResponse(
            id=updated_transfer["id"],
            employee_id=updated_transfer["employee_id"],
            from_location_id=updated_transfer["from_location_id"],
            to_location_id=updated_transfer["to_location_id"],
            transfer_date=updated_transfer["transfer_date"],
            status=updated_transfer["status"],
            requested_by_user_id=updated_transfer["requested_by_user_id"],
            approved_by_user_id=updated_transfer["approved_by_user_id"],
            rejection_reason=updated_transfer["rejection_reason"],
            created_at=updated_transfer["created_at"],
        )

    finally:
        conn.close()


# ============================================================================
# LOCATION PAYROLL DASHBOARD ENDPOINTS
# ============================================================================

@router.get("/payroll/location/{location_id}/dashboard")
async def get_location_payroll_dashboard(
    location_id: int,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get comprehensive payroll dashboard for a location."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify location exists
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # Get latest payroll run summary
        summary = conn.execute(
            """
            SELECT
                COUNT(DISTINCT ps.employee_id) as total_employees,
                SUM(ps.gross_pay) as total_gross_pay,
                SUM(ps.net_pay) as total_net_pay,
                AVG(ps.gross_pay) as avg_salary,
                pr.period_start, pr.period_end
            FROM payslips ps
            JOIN payroll_runs pr ON ps.payroll_run_id = pr.id
            JOIN employees e ON ps.employee_id = e.employee_id
            JOIN employee_location_assignments ela ON e.employee_id = ela.employee_id
            WHERE ela.location_id = ? AND pr.institution_id = ? AND ela.is_active = 1
            GROUP BY pr.period_start, pr.period_end
            ORDER BY pr.period_end DESC
            LIMIT 1
            """,
            (location_id, inst_id),
        ).fetchone()

        # Get department breakdown
        departments = conn.execute(
            """
            SELECT e.department, COUNT(*) as headcount, AVG(ps.gross_pay) as avg_salary
            FROM employee_location_assignments ela
            JOIN employees e ON ela.employee_id = e.employee_id
            LEFT JOIN payslips ps ON e.employee_id = ps.employee_id
            WHERE ela.location_id = ? AND ela.institution_id = ? AND ela.is_active = 1
            GROUP BY e.department
            ORDER BY headcount DESC
            """,
            (location_id, inst_id),
        ).fetchall()

        # Get budget status
        budget = conn.execute(
            """
            SELECT budget_amount, actual_amount FROM location_budgets
            WHERE location_id = ? AND period_end >= date('now')
            ORDER BY period_end DESC LIMIT 1
            """,
            (location_id,),
        ).fetchone()

        return {
            "location_id": location_id,
            "location_name": location["name"],
            "summary": {
                "total_employees": summary["total_employees"] if summary else 0,
                "total_gross_pay": float(summary["total_gross_pay"] or 0) if summary else 0,
                "total_net_pay": float(summary["total_net_pay"] or 0) if summary else 0,
                "average_salary": float(summary["avg_salary"] or 0) if summary else 0,
                "period_start": summary["period_start"] if summary else None,
                "period_end": summary["period_end"] if summary else None,
            },
            "departments": [
                {
                    "department": d["department"],
                    "headcount": d["headcount"],
                    "average_salary": float(d["avg_salary"] or 0),
                }
                for d in departments
            ],
            "budget": {
                "allocated": float(budget["budget_amount"]) if budget else None,
                "actual": float(budget["actual_amount"]) if budget else None,
                "variance": float(budget["budget_amount"] - budget["actual_amount"]) if budget and budget["actual_amount"] else None,
            } if budget else None,
        }

    finally:
        conn.close()


@router.get("/payroll/institution/{institution_id}/summary")
async def get_institution_payroll_summary(
    institution_id: int,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get institution-wide payroll summary across all locations."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify institution matches
        if institution_id != inst_id:
            raise HTTPException(403, detail="Access denied")

        # Get all locations summary
        locations = conn.execute(
            """
            SELECT
                l.id, l.name,
                COUNT(DISTINCT ps.employee_id) as employee_count,
                SUM(ps.gross_pay) as total_gross_pay,
                AVG(ps.gross_pay) as avg_salary
            FROM locations l
            LEFT JOIN employee_location_assignments ela ON l.id = ela.location_id AND ela.is_active = 1
            LEFT JOIN payslips ps ON ela.employee_id = ps.employee_id
            WHERE l.institution_id = ?
            GROUP BY l.id, l.name
            ORDER BY total_gross_pay DESC NULLS LAST
            """,
            (inst_id,),
        ).fetchall()

        return {
            "institution_id": inst_id,
            "locations": [
                {
                    "location_id": l["id"],
                    "location_name": l["name"],
                    "employee_count": l["employee_count"] or 0,
                    "total_gross_pay": float(l["total_gross_pay"] or 0),
                    "average_salary": float(l["avg_salary"] or 0),
                }
                for l in locations
            ],
            "total_employees": sum(l["employee_count"] or 0 for l in locations),
            "total_gross_pay": float(sum(l["total_gross_pay"] or 0 for l in locations)),
        }

    finally:
        conn.close()


# ============================================================================
# CAPACITY UTILIZATION TRENDS ENDPOINTS
# ============================================================================

@router.get("/locations/{location_id}/utilization-history")
async def get_utilization_history(
    location_id: int,
    days: int = 30,
    current_user: dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Get historical capacity utilization data for a location."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify location exists
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # For now, return current snapshot
        # In a production system, you'd query a time-series table or audit logs
        emp_count = conn.execute(
            """
            SELECT COUNT(*) FROM employee_location_assignments
            WHERE location_id = ? AND institution_id = ? AND is_active = 1
            """,
            (location_id, inst_id),
        ).fetchone()[0]

        capacity = location["capacity"] or 100
        utilization = (emp_count / capacity * 100) if capacity > 0 else 0

        # Return current data point
        return [
            {
                "date": datetime.utcnow().date().isoformat(),
                "employee_count": emp_count,
                "capacity": capacity,
                "utilization_percent": round(utilization, 1),
            }
        ]

    finally:
        conn.close()


@router.get("/locations/{location_id}/utilization-trends")
async def get_utilization_trends(
    location_id: int,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get capacity utilization trends and analysis."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify location exists
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # Get current utilization
        emp_count = conn.execute(
            """
            SELECT COUNT(*) FROM employee_location_assignments
            WHERE location_id = ? AND institution_id = ? AND is_active = 1
            """,
            (location_id, inst_id),
        ).fetchone()[0]

        capacity = location["capacity"] or 100
        current_utilization = (emp_count / capacity * 100) if capacity > 0 else 0

        # Get historical average (simplified - would use audit data)
        historical_avg = current_utilization  # Placeholder

        # Trend calculation
        trend = "stable"  # Placeholder

        return {
            "location_id": location_id,
            "location_name": location["name"],
            "current_utilization": round(current_utilization, 1),
            "historical_average": round(historical_avg, 1),
            "trend": trend,
            "current_employees": emp_count,
            "capacity": capacity,
            "available_capacity": capacity - emp_count,
            "recommendation": _get_capacity_recommendation(current_utilization),
        }

    finally:
        conn.close()


def _get_capacity_recommendation(utilization: float) -> str:
    """Get recommendation based on utilization."""
    if utilization >= 95:
        return "URGENT: Recruit immediately or reduce assignments"
    elif utilization >= 80:
        return "Plan recruitment to maintain buffer"
    elif utilization >= 60:
        return "Monitor and plan for growth"
    else:
        return "Capacity available for additional assignments"


logger.info("Location Phase 2 router registered with 7 endpoints")

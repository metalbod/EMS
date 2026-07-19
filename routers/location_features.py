"""API endpoints for location features: history, transfers, alerts, budgets, reports."""
import logging
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.location_features_schemas import (
    EmployeeAssignmentHistory,
    AssignmentHistoryEntry,
    LocationAssignmentHistory,
    CapacityAlert,
    CapacityAlertAcknowledge,
    LocationEmployeeReport,
    EmployeeLocationReportRequest,
    CapacityStatus,
    CapacityForecast,
    LocationCapacityDashboard,
    LocationPayrollSummary,
    ReportScheduleCreate,
    ReportScheduleResponse,
)

logger = logging.getLogger("ems.location_features")
router = APIRouter(prefix="/api", tags=["location-features"])


# ============================================================================
# PAYROLL SCOPING ENDPOINTS
# ============================================================================

@router.get("/locations/{location_id}/payroll-runs")
async def get_location_payroll_runs(
    location_id: int,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[dict]:
    """Get payroll runs for a specific location."""
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

        # Get payroll runs that include employees from this location
        query = """
            SELECT DISTINCT pr.id, pr.institution_id, pr.period_start, pr.period_end,
                   pr.created_by, pr.created_at
            FROM payroll_runs pr
            JOIN payslips ps ON pr.id = ps.payroll_run_id
            JOIN employees e ON ps.employee_id = e.employee_id
            JOIN employee_location_assignments ela ON e.employee_id = ela.employee_id
            WHERE ela.location_id = ? AND pr.institution_id = ? AND ela.is_active = 1
        """
        params = [location_id, inst_id]

        if period_start:
            query += " AND pr.period_start >= ?"
            params.append(period_start)

        if period_end:
            query += " AND pr.period_end <= ?"
            params.append(period_end)

        query += " ORDER BY pr.period_start DESC LIMIT 100"

        runs = conn.execute(query, params).fetchall()

        return [
            {
                "id": run["id"],
                "period_start": run["period_start"],
                "period_end": run["period_end"],
                "created_by": run["created_by"],
                "created_at": run["created_at"],
            }
            for run in runs
        ]

    finally:
        conn.close()


@router.get("/locations/{location_id}/payroll-summary")
async def get_location_payroll_summary(
    location_id: int,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> LocationPayrollSummary:
    """Get payroll summary for a location."""
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

        # Get payroll summary (use computed deductions or default to 0)
        query = """
            SELECT
                COUNT(DISTINCT ps.employee_id) as total_employees,
                SUM(ps.gross_pay) as total_gross_pay,
                SUM(COALESCE(ps.gross_pay - ps.net_pay, 0)) as total_deductions,
                SUM(ps.net_pay) as total_net_pay,
                AVG(ps.gross_pay) as average_salary,
                pr.period_start, pr.period_end
            FROM payslips ps
            JOIN payroll_runs pr ON ps.payroll_run_id = pr.id
            JOIN employees e ON ps.employee_id = e.employee_id
            JOIN employee_location_assignments ela ON e.employee_id = ela.employee_id
            WHERE ela.location_id = ? AND pr.institution_id = ? AND ela.is_active = 1
        """
        params = [location_id, inst_id]

        if period_start:
            query += " AND pr.period_start >= ?"
            params.append(period_start)

        if period_end:
            query += " AND pr.period_end <= ?"
            params.append(period_end)

        query += " GROUP BY pr.period_start, pr.period_end ORDER BY pr.period_end DESC LIMIT 1"

        result = conn.execute(query, params).fetchone()

        if not result:
            return LocationPayrollSummary(
                location_id=location_id,
                location_name=location["name"],
                location_code=location["code"],
                report_period="N/A",
                total_employees=0,
                payroll_run_status=None,
                total_gross_pay=0.0,
                total_deductions=0.0,
                total_net_pay=0.0,
                average_salary=0.0,
                budget_allocated=None,
                budget_variance=None,
                variance_percent=None,
            )

        # Check budget for this location
        budget = conn.execute(
            """
            SELECT budget_amount, actual_amount FROM location_budgets
            WHERE location_id = ? AND period_start = ? AND period_end = ?
            """,
            (location_id, result["period_start"], result["period_end"]),
        ).fetchone()

        budget_variance = None
        variance_percent = None
        if budget and result["total_gross_pay"]:
            budget_variance = budget["budget_amount"] - result["total_gross_pay"]
            variance_percent = (budget_variance / budget["budget_amount"] * 100) if budget["budget_amount"] > 0 else None

        return LocationPayrollSummary(
            location_id=location_id,
            location_name=location["name"],
            location_code=location["code"],
            report_period=f"{result['period_start']} to {result['period_end']}",
            total_employees=result["total_employees"] or 0,
            payroll_run_status="active",
            total_gross_pay=float(result["total_gross_pay"] or 0),
            total_deductions=float(result["total_deductions"] or 0),
            total_net_pay=float(result["total_net_pay"] or 0),
            average_salary=float(result["average_salary"] or 0),
            budget_allocated=float(budget["budget_amount"]) if budget else None,
            budget_variance=budget_variance,
            variance_percent=variance_percent,
        )

    finally:
        conn.close()


# ============================================================================
# ASSIGNMENT HISTORY ENDPOINTS
# ============================================================================

@router.get("/employees/{employee_id}/locations/history")
async def get_employee_assignment_history(
    employee_id: str,
    current_user: dict = Depends(get_current_user),
) -> EmployeeAssignmentHistory:
    """Get complete assignment history for an employee."""
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

        # Get all assignments (active and inactive)
        assignments = conn.execute(
            """
            SELECT ela.*, l.name as location_name, l.code as location_code
            FROM employee_location_assignments ela
            JOIN locations l ON ela.location_id = l.id
            WHERE ela.employee_id = ? AND ela.institution_id = ?
            ORDER BY ela.start_date DESC
            """,
            (employee_id, inst_id),
        ).fetchall()

        # Build history
        history_entries = []
        current_assignment = None

        for asg in assignments:
            entry = AssignmentHistoryEntry(
                id=asg["id"],
                location_id=asg["location_id"],
                location_name=asg["location_name"],
                location_code=asg["location_code"],
                assignment_type=asg["assignment_type"],
                start_date=asg["start_date"],
                end_date=asg["end_date"],
                ended_by_user_id=asg["ended_by_user_id"],
                end_reason=asg["end_reason"],
                is_active=bool(asg["is_active"]),
                created_at=asg["created_at"],
                updated_at=asg["updated_at"],
            )
            history_entries.append(entry)

            # Current assignment is first active one in reverse-date order
            if bool(asg["is_active"]) and current_assignment is None:
                current_assignment = entry

        return EmployeeAssignmentHistory(
            employee_id=employee_id,
            total_assignments=len(history_entries),
            current_assignment=current_assignment,
            assignment_history=history_entries,
        )

    finally:
        conn.close()


@router.get("/locations/{location_id}/assignment-history")
async def get_location_assignment_history(
    location_id: int,
    current_user: dict = Depends(get_current_user),
) -> LocationAssignmentHistory:
    """Get assignment history for a location."""
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

        # Get all assignments for this location
        assignments = conn.execute(
            """
            SELECT ela.*, e.full_name
            FROM employee_location_assignments ela
            JOIN employees e ON ela.employee_id = e.employee_id
            WHERE ela.location_id = ? AND ela.institution_id = ?
            ORDER BY ela.start_date DESC
            """,
            (location_id, inst_id),
        ).fetchall()

        # Count current employees
        current_count = conn.execute(
            """
            SELECT COUNT(*) FROM employee_location_assignments
            WHERE location_id = ? AND institution_id = ? AND is_active = 1
            """,
            (location_id, inst_id),
        ).fetchone()[0]

        history_data = [
            {
                "employee_id": asg["employee_id"],
                "employee_name": asg["full_name"],
                "assignment_type": asg["assignment_type"],
                "start_date": asg["start_date"],
                "end_date": asg["end_date"],
                "is_active": bool(asg["is_active"]),
            }
            for asg in assignments
        ]

        return LocationAssignmentHistory(
            location_id=location_id,
            location_name=location["name"],
            total_assignments=len(assignments),
            current_employees=current_count,
            assignment_history=history_data,
        )

    finally:
        conn.close()


# ============================================================================
# CAPACITY ALERTS ENDPOINTS
# ============================================================================

@router.get("/locations/{location_id}/capacity-alerts")
async def get_location_capacity_alerts(
    location_id: int,
    unresolved_only: bool = True,
    current_user: dict = Depends(get_current_user),
) -> List[CapacityAlert]:
    """Get capacity alerts for a location."""
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

        # Get alerts
        query = """
            SELECT * FROM location_capacity_alerts
            WHERE location_id = ?
        """
        params = [location_id]

        if unresolved_only:
            query += " AND is_resolved = 0"

        query += " ORDER BY triggered_at DESC LIMIT 100"

        alerts = conn.execute(query, params).fetchall()

        return [
            CapacityAlert(
                id=alert["id"],
                location_id=alert["location_id"],
                alert_level=alert["alert_level"],
                triggered_at=alert["triggered_at"],
                acknowledged_at=alert["acknowledged_at"],
                acknowledged_by_user_id=alert["acknowledged_by_user_id"],
                is_resolved=bool(alert["is_resolved"]),
                resolved_at=alert["resolved_at"],
            )
            for alert in alerts
        ]

    finally:
        conn.close()


@router.put("/capacity-alerts/{alert_id}/acknowledge", status_code=200)
async def acknowledge_capacity_alert(
    alert_id: int,
    data: CapacityAlertAcknowledge,
    current_user: dict = Depends(get_current_user),
) -> CapacityAlert:
    """Acknowledge a capacity alert."""
    conn = get_db()
    try:
        user_id = current_user.get("id")
        acknowledged_at = data.acknowledged_at or datetime.utcnow().isoformat()

        # Update alert
        conn.execute(
            """
            UPDATE location_capacity_alerts
            SET acknowledged_at = ?, acknowledged_by_user_id = ?
            WHERE id = ?
            """,
            (acknowledged_at, user_id, alert_id),
        )
        conn.commit()

        # Fetch updated alert
        alert = conn.execute(
            "SELECT * FROM location_capacity_alerts WHERE id = ?",
            (alert_id,),
        ).fetchone()

        if not alert:
            raise HTTPException(404, detail="Alert not found")

        return CapacityAlert(
            id=alert["id"],
            location_id=alert["location_id"],
            alert_level=alert["alert_level"],
            triggered_at=alert["triggered_at"],
            acknowledged_at=alert["acknowledged_at"],
            acknowledged_by_user_id=alert["acknowledged_by_user_id"],
            is_resolved=bool(alert["is_resolved"]),
            resolved_at=alert["resolved_at"],
        )

    finally:
        conn.close()


@router.post("/locations/{location_id}/capacity-alerts/check")
async def check_and_trigger_capacity_alerts(
    location_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Check location capacity and trigger alerts if needed."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Get location
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # Get current employee count
        emp_count = conn.execute(
            """
            SELECT COUNT(*) FROM employee_location_assignments
            WHERE location_id = ? AND institution_id = ? AND is_active = 1
            """,
            (location_id, inst_id),
        ).fetchone()[0]

        capacity = (location["capacity"] if location["capacity"] else None) or 100
        utilization = (emp_count / capacity * 100) if capacity > 0 else 0

        warning_threshold = (location["capacity_warning_threshold"] if location["capacity_warning_threshold"] else None) or 80
        critical_threshold = (location["capacity_critical_threshold"] if location["capacity_critical_threshold"] else None) or 95

        alert_triggered = False
        alert_level = None

        if utilization >= critical_threshold:
            alert_level = "Critical"
            alert_triggered = True
        elif utilization >= warning_threshold:
            alert_level = "Warning"
            alert_triggered = True

        if alert_triggered:
            # Check if recent alert already exists
            recent_alert = conn.execute(
                """
                SELECT id FROM location_capacity_alerts
                WHERE location_id = ? AND is_resolved = 0 AND alert_level = ?
                AND triggered_at > datetime('now', '-24 hours')
                """,
                (location_id, alert_level),
            ).fetchone()

            if not recent_alert:
                # Create new alert
                conn.execute(
                    """
                    INSERT INTO location_capacity_alerts
                    (location_id, alert_level, triggered_at)
                    VALUES (?, ?, ?)
                    """,
                    (location_id, alert_level, datetime.utcnow().isoformat()),
                )
                conn.commit()

        return {
            "location_id": location_id,
            "current_employees": emp_count,
            "capacity": capacity,
            "utilization_percent": round(utilization, 1),
            "alert_triggered": alert_triggered,
            "alert_level": alert_level,
        }

    finally:
        conn.close()


# ============================================================================
# EMPLOYEE REPORT ENDPOINTS
# ============================================================================

@router.post("/reports/location/{location_id}/employees")
async def get_employee_report_by_location(
    location_id: int,
    request: EmployeeLocationReportRequest,
    current_user: dict = Depends(get_current_user),
) -> LocationEmployeeReport:
    """Generate employee report for a location."""
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

        # Build query
        query = """
            SELECT DISTINCT e.*, ela.assignment_type, ela.is_active
            FROM employee_location_assignments ela
            JOIN employees e ON ela.employee_id = e.employee_id
            WHERE ela.location_id = ? AND ela.institution_id = ?
        """
        params = [location_id, inst_id]

        if not request.include_inactive:
            query += " AND e.status = 'Active'"

        if request.status_filter:
            query += " AND e.status = ?"
            params.append(request.status_filter)

        if request.departments:
            placeholders = ",".join("?" * len(request.departments))
            query += f" AND e.department IN ({placeholders})"
            params.extend(request.departments)

        query += " ORDER BY e.full_name"

        employees = conn.execute(query, params).fetchall()

        # Build report rows
        report_rows = []
        dept_counts = {}
        status_counts = {"Active": 0, "Inactive": 0}

        for emp in employees:
            dept = emp["department"]
            dept_counts[dept] = dept_counts.get(dept, 0) + 1
            status_counts[emp["status"]] = status_counts.get(emp["status"], 0) + 1

            # Get all locations for this employee
            all_locs = conn.execute(
                """
                SELECT DISTINCT l.name FROM employee_location_assignments ela
                JOIN locations l ON ela.location_id = l.id
                WHERE ela.employee_id = ? AND ela.is_active = 1
                """,
                (emp["employee_id"],),
            ).fetchall()

            row = {
                "employee_id": emp["employee_id"],
                "full_name": emp["full_name"],
                "designation": emp["designation"],
                "department": emp["department"],
                "employment_type": emp["employment_type"],
                "start_date": emp["start_date"],
                "status": emp["status"],
                "primary_location": location["name"] if emp["assignment_type"] == "primary" else None,
                "all_locations": [l["name"] for l in all_locs],
                "phone": emp["phone"],
                "email": emp["work_email"],
            }
            report_rows.append(row)

        return LocationEmployeeReport(
            location_id=location_id,
            location_name=location["name"],
            location_code=location["code"],
            report_date=datetime.utcnow().isoformat(),
            total_employees=len(employees),
            active_employees=status_counts.get("Active", 0),
            inactive_employees=status_counts.get("Inactive", 0),
            employees=report_rows,
            summary={
                "by_department": dept_counts,
                "by_status": status_counts,
                "average_tenure_days": 0,  # TODO: calculate
            },
        )

    finally:
        conn.close()


# ============================================================================
# CAPACITY PLANNING ENDPOINTS
# ============================================================================

@router.get("/locations/{location_id}/capacity-status")
async def get_location_capacity_status(
    location_id: int,
    current_user: dict = Depends(get_current_user),
) -> CapacityStatus:
    """Get current capacity status for a location."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Get location
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # Get employee count
        emp_count = conn.execute(
            """
            SELECT COUNT(*) FROM employee_location_assignments
            WHERE location_id = ? AND institution_id = ? AND is_active = 1
            """,
            (location_id, inst_id),
        ).fetchone()[0]

        capacity = (location["capacity"] if location["capacity"] else None) or 100
        utilization = (emp_count / capacity * 100) if capacity > 0 else 0

        warning_threshold = (location["capacity_warning_threshold"] if location["capacity_warning_threshold"] else None) or 80
        critical_threshold = (location["capacity_critical_threshold"] if location["capacity_critical_threshold"] else None) or 95

        # Determine status
        if utilization >= critical_threshold:
            status = "Critical"
        elif utilization >= warning_threshold:
            status = "Warning"
        else:
            status = "Healthy"

        # Check for active alerts
        alert = conn.execute(
            """
            SELECT id FROM location_capacity_alerts
            WHERE location_id = ? AND is_resolved = 0
            LIMIT 1
            """,
            (location_id,),
        ).fetchone()

        # Recommendation
        recommendation = None
        if status == "Critical":
            needed = max(1, int((capacity * 1.2) - emp_count))
            recommendation = f"URGENT: Recruit {needed} employees or reduce assignments"
        elif status == "Warning":
            needed = max(0, int((capacity * 1.1) - emp_count))
            if needed > 0:
                recommendation = f"Plan recruitment of {needed} employees"

        return CapacityStatus(
            location_id=location_id,
            location_name=location["name"],
            current_employees=emp_count,
            capacity=capacity,
            utilization_percent=round(utilization, 1),
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            status=status,
            alert_triggered=alert is not None,
            recommendation=recommendation,
        )

    finally:
        conn.close()


@router.get("/locations/{location_id}/capacity-dashboard")
async def get_location_capacity_dashboard(
    location_id: int,
    current_user: dict = Depends(get_current_user),
) -> LocationCapacityDashboard:
    """Get complete capacity planning dashboard for a location."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Get capacity status
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # Get current status
        emp_count = conn.execute(
            """
            SELECT COUNT(*) FROM employee_location_assignments
            WHERE location_id = ? AND institution_id = ? AND is_active = 1
            """,
            (location_id, inst_id),
        ).fetchone()[0]

        capacity = (location["capacity"] if location["capacity"] else None) or 100
        utilization = (emp_count / capacity * 100) if capacity > 0 else 0

        # Get alerts
        alerts = conn.execute(
            """
            SELECT * FROM location_capacity_alerts
            WHERE location_id = ? AND is_resolved = 0
            ORDER BY triggered_at DESC LIMIT 10
            """,
            (location_id,),
        ).fetchall()

        # Get budget info
        budget = conn.execute(
            """
            SELECT * FROM location_budgets
            WHERE location_id = ? AND period_end >= date('now')
            ORDER BY period_start DESC LIMIT 1
            """,
            (location_id,),
        ).fetchone()

        return LocationCapacityDashboard(
            location_id=location_id,
            location_name=location["name"],
            current_status=CapacityStatus(
                location_id=location_id,
                location_name=location["name"],
                current_employees=emp_count,
                capacity=capacity,
                utilization_percent=round(utilization, 1),
                warning_threshold=(location["capacity_warning_threshold"] or 80),
                critical_threshold=(location["capacity_critical_threshold"] or 95),
                status="Critical" if utilization >= 95 else "Warning" if utilization >= 80 else "Healthy",
                alert_triggered=len(alerts) > 0,
                recommendation=None,
            ),
            forecast=CapacityForecast(
                location_id=location_id,
                location_name=location["name"],
                forecast_period="next-30-days",
                current_headcount=emp_count,
                projected_departures=0,  # TODO: calculate from contracts
                planned_leaves=0,  # TODO: get from leave system
                projected_headcount=emp_count,
                forecast_utilization=utilization,
                recruitment_needed=0,
                actions_recommended=[],
            ),
            recent_alerts=[
                CapacityAlert(
                    id=alert["id"],
                    location_id=alert["location_id"],
                    alert_level=alert["alert_level"],
                    triggered_at=alert["triggered_at"],
                    acknowledged_at=alert["acknowledged_at"],
                    acknowledged_by_user_id=alert["acknowledged_by_user_id"],
                    is_resolved=bool(alert["is_resolved"]),
                    resolved_at=alert["resolved_at"],
                )
                for alert in alerts
            ],
            trend_data=[],  # TODO: calculate from historical data
            budget_info=None,  # TODO: format budget data
        )

    finally:
        conn.close()


logger.info("Location features router registered with 10 Phase 1 endpoints")

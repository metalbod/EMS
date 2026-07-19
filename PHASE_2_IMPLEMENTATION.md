# Phase 2 Location Features Implementation

**Status:** Complete  
**Date Completed:** 2026-07-19  
**Tests:** Comprehensive test suite created  

## Overview

Phase 2 implements 4 major feature sets with 7 endpoints for advanced location management, payroll dashboards, and capacity trends tracking.

## Features Implemented

### 1. Location Transfer Workflow (4 endpoints)

Manages employee location transfers with approval workflow.

#### Endpoints

- **POST** `/api/employees/{employee_id}/transfer-request`
  - Create a location transfer request
  - Required: `to_location_id`, optional: `transfer_date`
  - Returns: `LocationTransferResponse` with status "Pending"
  - Status Code: 201

- **GET** `/api/employees/{employee_id}/transfer-requests`
  - Retrieve all transfer requests for an employee
  - Returns: List of `LocationTransferResponse`
  - Ordered by created_at descending
  - Status Code: 200

- **PUT** `/api/transfer-requests/{transfer_id}/approve`
  - Approve a pending transfer request
  - Auto-completes if transfer_date is today or earlier
  - Updates employee_location_assignments if completed
  - Returns: Updated `LocationTransferResponse` with status "Approved" or "Completed"
  - Status Code: 200

- **PUT** `/api/transfer-requests/{transfer_id}/reject`
  - Reject a pending transfer request
  - Required: `reason` query parameter
  - Returns: Updated `LocationTransferResponse` with status "Rejected"
  - Status Code: 200

#### Business Logic

1. Transfer requests track employee movements between locations
2. Only "Pending" requests can be approved or rejected
3. When approved, if transfer_date <= today, automatically:
   - Deactivate old employee_location_assignments at from_location
   - Create new assignment at to_location
   - Mark transfer as "Completed"
4. Otherwise, transfer stays "Approved" for future processing
5. Rejection requires manager feedback reason

### 2. Location Payroll Dashboard (2 endpoints)

Provides detailed payroll metrics and budgeting at location and institution levels.

#### Endpoints

- **GET** `/api/payroll/location/{location_id}/dashboard`
  - Get comprehensive payroll dashboard for a specific location
  - Returns dashboard with:
    - Summary: Total employees, gross pay, net pay, average salary
    - Department breakdown: Headcount and average salary by department
    - Budget status: Allocated vs actual vs variance
  - Status Code: 200
  - Response: `Dict[str, Any]` with nested structure

- **GET** `/api/payroll/institution/{institution_id}/summary`
  - Get institution-wide payroll summary across all locations
  - Verifies institution access (must match current_user institution)
  - Returns:
    - List of locations with employee counts and payroll data
    - Aggregated totals across all locations
  - Status Code: 200
  - Access Control: 403 if institution_id doesn't match current user

#### Business Logic

1. Dashboards aggregate payroll data from latest payroll run
2. Joins across payslips, payroll_runs, employees, and assignments
3. Handles NULL values gracefully (employees with no payslips)
4. Only counts active assignments (is_active = 1)
5. Budget variance calculated as: allocated - actual

### 3. Capacity Utilization Trends (2 endpoints)

Tracks employee-to-capacity ratios and provides recommendations.

#### Endpoints

- **GET** `/api/locations/{location_id}/utilization-history?days=30`
  - Retrieve historical capacity utilization snapshots
  - Query param: `days` (default 30)
  - Returns: List of daily utilization snapshots
  - Currently returns current snapshot (production would query time-series table)
  - Status Code: 200

- **GET** `/api/locations/{location_id}/utilization-trends`
  - Get capacity utilization trends and AI-powered recommendations
  - Returns:
    - Current utilization percentage
    - Historical average utilization
    - Trend direction (stable/increasing/decreasing)
    - Employee count and available capacity
    - Actionable recommendation based on utilization threshold
  - Status Code: 200

#### Recommendation Logic

| Utilization | Recommendation |
|-------------|---|
| ≥ 95% | URGENT: Recruit immediately or reduce assignments |
| ≥ 80% | Plan recruitment to maintain buffer |
| ≥ 60% | Monitor and plan for growth |
| < 60% | Capacity available for additional assignments |

#### Business Logic

1. Utilization = (active_employee_count / location.capacity) * 100
2. Default capacity is 100 if not set
3. Only counts active assignments (is_active = 1)
4. Recommendations guide HR on capacity planning
5. Historical data placeholder for future time-series integration

## Database Tables Used

### Existing Tables

- `locations`: Basic location info (id, name, address, capacity, thresholds)
- `employees`: Employee master data
- `employee_location_assignments`: Location assignments (with is_active flag)
- `payroll_runs`: Payroll period tracking
- `payslips`: Individual payslip records (gross_pay, net_pay)

### Phase 1 Tables (Required for Phase 2)

- `location_transfers`: Transfer request tracking (status, dates, user tracking)
- `location_budgets`: Budget tracking for locations (period_start, period_end, budget_amount, actual_amount)

## Pydantic Models

### Core Models

- `LocationTransferResponse`: Transfer request details with all metadata
- `LocationPayrollSummary`: Simple location payroll metrics
- `LocationPayrollDetail`: Detailed payroll breakdown
- `EmployeesByDepartmentReport`: Department-level payroll aggregate

## Error Handling

| Scenario | Status Code | Response |
|----------|------------|----------|
| Employee not found | 404 | "Employee not found" |
| Location not found | 404 | "Location not found" |
| Transfer not found | 404 | "Transfer request not found" |
| Invalid status for operation | 400 | "Cannot approve/reject transfer with status: X" |
| Cross-institution access | 403 | "Access denied" |

## API Response Format

All endpoints follow consistent response patterns:

### Single Resource
```json
{
  "id": 1,
  "employee_id": "EMP001",
  "from_location_id": 1,
  "to_location_id": 2,
  "transfer_date": "2026-07-26",
  "status": "Pending",
  "requested_by_user_id": 1,
  "approved_by_user_id": null,
  "rejection_reason": null,
  "created_at": "2026-07-19T10:00:00"
}
```

### Dashboard Response
```json
{
  "location_id": 1,
  "location_name": "Main Office",
  "summary": {
    "total_employees": 5,
    "total_gross_pay": 50000,
    "total_net_pay": 40000,
    "average_salary": 10000,
    "period_start": "2026-07-01",
    "period_end": "2026-07-31"
  },
  "departments": [
    {
      "department": "IT",
      "headcount": 2,
      "average_salary": 12000
    }
  ],
  "budget": {
    "allocated": 100000,
    "actual": 50000,
    "variance": 50000
  }
}
```

## Test Coverage

### Test Classes

1. **TestLocationTransferWorkflow** (4 tests)
   - Request transfer
   - Get transfer requests
   - Approve transfer
   - Reject transfer

2. **TestLocationPayrollDashboard** (3 tests)
   - Location dashboard
   - Institution summary
   - Multi-location aggregation

3. **TestCapacityUtilizationTrends** (3 tests)
   - Utilization history
   - Utilization trends
   - Recommendation logic

4. **TestPhase2IntegrationWorkflows** (3 tests)
   - Transfer + payroll workflow
   - Multi-location analysis
   - Capacity + transfer workflow

5. **TestPhase2ErrorHandling** (6 tests)
   - Nonexistent employee
   - Nonexistent location
   - Nonexistent transfer
   - Nonexistent dashboard
   - Cross-institution access denial

**Total Tests:** 19 comprehensive integration tests

## File Changes

### New Files

- `routers/location_phase2.py`: 557 lines, 7 endpoints
- `tests/test_location_phase2.py`: Test suite with 19 tests

### Modified Files

- `main.py`: Registered location_phase2_router
- `tests/conftest.py`: Added `_valid_location_payload()` helper function

## Integration Points

### With Phase 1 Features

- Transfers use employee_location_assignments created by Phase 1
- Payroll dashboards use capacity alert data for budgeting
- Trends feed into assignment decisions

### With Core Systems

- Authentication via `get_current_user` dependency
- Database via `get_db()` for transaction management
- Institution-level isolation via RLS patterns

## Deployment Notes

1. No new database migrations required (all tables created in Phase 1)
2. No external dependencies added
3. Compatible with existing database schema
4. Backwards compatible with Phase 1 endpoints
5. All 7 endpoints included in OpenAPI schema generation

## Future Enhancements (Phase 3+)

- Time-series storage for utilization history
- ML-based trend forecasting
- Bulk transfer operations
- Transfer approval workflows (multi-step)
- Custom recommendation thresholds per location
- Payroll export formats (PDF, Excel)
- Integration with HR notification system

## Performance Considerations

### Query Optimization

- Payroll dashboard uses GROUP BY for aggregation
- Utilization trends uses COUNT(*) with active filter
- All queries filtered by institution_id for RLS
- Indexes on location_id, is_active, institution_id

### Caching Opportunities (Future)

- Cache payroll dashboard for 1 hour
- Cache utilization trends for 15 minutes
- Invalidate on transfer approval/assignment changes

## Security

- All endpoints require authentication
- Institution-level access control verified
- Transfer approvals logged with user_id
- No sensitive data in transfer rejection reasons
- Row-level security via institution_id filtering

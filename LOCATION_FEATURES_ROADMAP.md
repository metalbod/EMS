# Location-Related Features Roadmap

**Status:** In Development  
**Start Date:** 2026-07-19  
**Priority:** High

---

## Feature Overview

Build comprehensive location-based management features for:
1. Employee Assignment Management
2. Location-Based Reporting
3. Payroll Scoping by Location
4. Capacity Planning & Alerts

---

## Feature 1: Employee Assignment Management

### Current State
- ✅ Basic multi-location assignment working
- ✅ Primary/secondary/temporary types supported
- ✅ Bulk operations available

### New Features to Add

#### 1.1 Assignment History & Audit Trail
**Description:** Track employee location changes over time
- View assignment history per employee
- View location staffing history
- Track start/end dates and changes
- Display who made changes and when

**API Endpoints:**
```
GET /api/employees/{id}/locations/history
GET /api/locations/{id}/assignment-history
```

**Database:**
- Use existing `created_at`, `updated_at`, `is_active` fields
- Add `ended_by_user_id` and `end_reason` fields (optional)

#### 1.2 Location Transfer Workflow
**Description:** Manage employee transfers between locations
- Request location transfer
- Approve/reject transfers
- Track transfer dates
- Maintain continuity of records

**API Endpoints:**
```
POST /api/employees/{id}/transfer-request
GET /api/employees/{id}/transfer-requests
PUT /api/transfer-requests/{id}/approve
PUT /api/transfer-requests/{id}/reject
```

#### 1.3 Assignment Validation Rules
**Description:** Enforce business rules for assignments
- Validate assignment type constraints
- Check capacity before assignment
- Prevent conflicting assignments
- Validate date ranges

**Validations:**
- Only 1 primary assignment per employee
- Unlimited secondary/temporary
- No overlapping temporary assignments
- Valid date ranges (start <= end)

#### 1.4 Bulk Location Update
**Description:** Update multiple employees' locations efficiently
- Bulk transfer to new location
- Bulk update assignment types
- Bulk end assignments with date
- Progress tracking and error reporting

**API Endpoints:**
```
POST /api/locations/{id}/bulk-update-employees
POST /api/employees/bulk-transfer-location
```

---

## Feature 2: Location-Based Reporting

### Current State
- ✅ Basic stats endpoint available
- ✅ Dashboard summary working

### New Features to Add

#### 2.1 Employee Reports by Location
**Description:** Generate detailed employee rosters per location
- List all employees at location (with details)
- Filter by department, status, employment type
- Export to CSV/Excel
- Include compensation info (optional)

**API Endpoints:**
```
GET /api/reports/location/{id}/employees
GET /api/reports/location/{id}/employees/export
GET /api/reports/institution/{id}/all-locations/employees
```

**Report Fields:**
- Employee ID, Name, Designation
- Department, Employment Type
- Start Date, Status
- Primary/Secondary location indicator
- Salary info (if authorized)

#### 2.2 Departmental Distribution by Location
**Description:** View department composition across locations
- Department headcount per location
- Department utilization %
- Department budget allocation
- Comparative analysis

**API Endpoints:**
```
GET /api/reports/location/{id}/departments
GET /api/reports/institution/{id}/departments-by-location
```

#### 2.3 Location Performance Report
**Description:** Track performance metrics per location
- Employee productivity metrics
- Turnover rate per location
- Compliance/policy adherence
- Performance ratings distribution

**API Endpoints:**
```
GET /api/reports/location/{id}/performance
```

#### 2.4 Leave & Attendance by Location
**Description:** Analyze leave and attendance patterns
- Leave taken per location
- Absent employees per location
- Attendance rate by location
- Leave policy compliance

**API Endpoints:**
```
GET /api/reports/location/{id}/leave-summary
GET /api/reports/location/{id}/attendance
```

#### 2.5 Export & Scheduling
**Description:** Generate and schedule reports
- Export to CSV/PDF/Excel
- Schedule automated reports (daily/weekly/monthly)
- Email distribution
- Archive historical reports

**API Endpoints:**
```
POST /api/reports/export
POST /api/reports/schedules
GET /api/reports/history
```

---

## Feature 3: Payroll Scoping by Location

### Current State
- ✅ Payroll runs exist
- ✅ Basic payroll calculation working
- ⏳ `payroll_runs.location_id` column added but not used

### New Features to Add

#### 3.1 Location-Specific Payroll Runs
**Description:** Create payroll runs scoped to specific locations
- Create payroll run for single location
- Create payroll run for multiple locations
- Create institution-wide payroll run
- Filter employees by location automatically

**API Endpoints:**
```
POST /api/payroll-runs (with location_id parameter)
GET /api/locations/{id}/payroll-runs
GET /api/payroll-runs?location_id={id}
```

**Changes:**
- Make `payroll_runs.location_id` nullable (NULL = institution-wide)
- Update payroll run creation to filter by location
- Update payslip generation to respect location

#### 3.2 Location-Based Payroll Dashboard
**Description:** View payroll metrics by location
- Total payroll cost per location
- Employee count by payroll status
- Payroll run progress by location
- Cost comparison across locations

**API Endpoints:**
```
GET /api/payroll/location/{id}/dashboard
GET /api/payroll/institution/{id}/summary
```

#### 3.3 Location Payroll Report
**Description:** Detailed payroll analysis by location
- Payroll breakdown per location
- Salary distribution
- Deductions summary
- Net pay comparison

**API Endpoints:**
```
GET /api/reports/payroll/location/{id}
GET /api/reports/payroll/location/{id}/export
```

#### 3.4 Budget Tracking by Location
**Description:** Track payroll budget vs actual
- Monthly budget allocation per location
- Actual spend per location
- Budget variance analysis
- Forecasting for next period

**API Endpoints:**
```
GET /api/payroll/budget/location/{id}
POST /api/payroll/budget/location/{id}/set
PUT /api/payroll/budget/location/{id}/adjust
```

---

## Feature 4: Capacity Planning & Alerts

### Current State
- ✅ Capacity field exists
- ✅ Utilization % calculated
- ⏳ Dashboard shows utilization

### New Features to Add

#### 4.1 Capacity Threshold Alerts
**Description:** Alert when capacity is exceeded or at risk
- Set warning threshold (e.g., 80%)
- Set critical threshold (e.g., 95%)
- Generate alerts when exceeded
- Track alert history

**API Endpoints:**
```
POST /api/locations/{id}/capacity-settings
GET /api/locations/{id}/capacity-alerts
PUT /api/locations/{id}/capacity-alerts/{alert_id}/acknowledge
```

**Database Changes:**
- Add `locations.capacity_warning_threshold` (default 80)
- Add `locations.capacity_critical_threshold` (default 95)
- Create `location_capacity_alerts` table

#### 4.2 Staffing Forecast
**Description:** Predict future staffing needs
- Upcoming employee departures
- Planned leaves/absences
- Projected headcount
- Recruitment recommendations

**API Endpoints:**
```
GET /api/locations/{id}/forecast
GET /api/locations/{id}/forecast/next-{period}
POST /api/locations/{id}/forecast/adjust
```

#### 4.3 Capacity Utilization Trends
**Description:** Track capacity utilization over time
- Historical utilization %
- Trend analysis
- Seasonal patterns
- Recommendations for adjustments

**API Endpoints:**
```
GET /api/locations/{id}/utilization-history
GET /api/locations/{id}/utilization-trends
```

#### 4.4 Capacity Planning Dashboard
**Description:** Comprehensive capacity planning view
- Current utilization across locations
- Alerts and warnings
- Forecast for next quarter
- Recommendations
- Comparative analysis

**Frontend Components:**
- Capacity gauge per location
- Alert indicators (red/yellow/green)
- Trend charts
- Forecast timeline
- Action recommendations

#### 4.5 Capacity Alerts via Dashboard/Email
**Description:** Proactive notification system
- Real-time dashboard alerts
- Email notifications on threshold breach
- Alert acknowledgment tracking
- Alert history and trends

**Email Template:**
```
Subject: Capacity Alert - {Location Name}

Location: {Location Name} ({Code})
Current Utilization: {Percent}%
Capacity: {Current} / {Total}
Alert Level: {Warning/Critical}

Action Required:
- Review staffing levels
- Plan recruitment or transfers
- Adjust capacity if needed
```

---

## Implementation Priority

### Phase 1 (Immediate)
1. ✅ Employee Assignment History
2. ✅ Location-Specific Payroll Runs
3. ✅ Basic Employee Reports by Location
4. ✅ Capacity Threshold Alerts

### Phase 2 (Week 2)
5. Location Transfer Workflow
6. Location-Based Payroll Dashboard
7. Location Payroll Report
8. Capacity Utilization Trends

### Phase 3 (Week 3)
9. Departmental Distribution Reports
10. Staffing Forecast
11. Budget Tracking by Location
12. Advanced Capacity Planning Dashboard

### Phase 4 (Week 4)
13. Leave & Attendance by Location
14. Location Performance Report
15. Report Export & Scheduling
16. Alert Notification System

---

## Database Schema Changes

### New Tables
```sql
-- Transfer requests
CREATE TABLE location_transfers (
    id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL,
    from_location_id INTEGER REFERENCES locations(id),
    to_location_id INTEGER NOT NULL REFERENCES locations(id),
    transfer_date DATE,
    status VARCHAR(20), -- Pending, Approved, Rejected, Completed
    requested_by_user_id INTEGER REFERENCES users(id),
    approved_by_user_id INTEGER REFERENCES users(id),
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Capacity alerts
CREATE TABLE location_capacity_alerts (
    id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    alert_level VARCHAR(20), -- Warning, Critical
    triggered_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    acknowledged_by_user_id INTEGER REFERENCES users(id),
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP
);

-- Budget tracking
CREATE TABLE location_budgets (
    id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    period_start DATE,
    period_end DATE,
    budget_amount DECIMAL(12, 2),
    actual_amount DECIMAL(12, 2),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Report schedules
CREATE TABLE report_schedules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    report_type VARCHAR(100),
    location_id INTEGER REFERENCES locations(id),
    frequency VARCHAR(20), -- Daily, Weekly, Monthly
    scheduled_day_of_week INT,
    scheduled_day_of_month INT,
    email_recipients TEXT[], -- Array of emails
    format VARCHAR(20), -- CSV, PDF, Excel
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Modified Tables
```sql
-- locations table
ALTER TABLE locations ADD COLUMN IF NOT EXISTS capacity_warning_threshold INT DEFAULT 80;
ALTER TABLE locations ADD COLUMN IF NOT EXISTS capacity_critical_threshold INT DEFAULT 95;

-- payroll_runs table (already has location_id)
-- Ensure it's being used properly in payroll calculations

-- employee_location_assignments table
ALTER TABLE employee_location_assignments ADD COLUMN IF NOT EXISTS ended_by_user_id INTEGER REFERENCES users(id);
ALTER TABLE employee_location_assignments ADD COLUMN IF NOT EXISTS end_reason TEXT;
```

---

## API Response Examples

### Employee Assignment History
```json
{
  "employee_id": "EMP001",
  "assignment_history": [
    {
      "location_id": 1,
      "location_name": "KL HQ",
      "assignment_type": "primary",
      "start_date": "2024-01-01",
      "end_date": "2026-06-30",
      "ended_by_user_id": 123,
      "end_reason": "Transfer to new location",
      "status": "ended"
    },
    {
      "location_id": 2,
      "location_name": "Penang Branch",
      "assignment_type": "primary",
      "start_date": "2026-07-01",
      "end_date": null,
      "status": "active"
    }
  ]
}
```

### Capacity Alert
```json
{
  "location_id": 1,
  "location_name": "KL HQ",
  "current_utilization": 92,
  "capacity_warning_threshold": 80,
  "capacity_critical_threshold": 95,
  "alert_level": "warning",
  "current_employees": 92,
  "capacity": 100,
  "alert_triggered_at": "2026-07-19T10:30:00Z",
  "action_required": true,
  "recommendations": [
    "Recruit 10-15 additional staff",
    "Consider transfer from other locations",
    "Increase capacity if possible"
  ]
}
```

### Payroll by Location
```json
{
  "location_id": 1,
  "location_name": "KL HQ",
  "period": "2026-07",
  "total_employees": 92,
  "payroll_run_status": "finalized",
  "total_gross_pay": 1250000.00,
  "total_deductions": 350000.00,
  "total_net_pay": 900000.00,
  "average_salary": 13587.00,
  "budget_allocated": 1300000.00,
  "budget_variance": -50000.00,
  "variance_percent": -3.8
}
```

---

## Success Criteria

### Phase 1 Completion
- [ ] All 4 new tables created and migrated
- [ ] Employee history endpoint working with tests
- [ ] Location-scoped payroll runs working
- [ ] Basic employee reports generating
- [ ] Capacity alerts triggering correctly
- [ ] Dashboard showing alerts
- [ ] 90%+ tests passing
- [ ] Documentation complete

### Overall Completion
- [ ] All 16 features implemented
- [ ] 200+ new tests written
- [ ] All endpoints documented
- [ ] Frontend UI for each feature
- [ ] Performance optimized
- [ ] Zero breaking changes
- [ ] 95%+ tests passing

---

## Timeline Estimate

- **Phase 1:** 1-2 days (4 features)
- **Phase 2:** 2-3 days (4 features)
- **Phase 3:** 2-3 days (4 features)
- **Phase 4:** 2-3 days (4 features)
- **Total:** 7-11 days for full implementation

---

## Next Steps

1. Create database migration for new tables
2. Implement Phase 1 features (employee history, payroll scoping, reports, alerts)
3. Add comprehensive tests for each feature
4. Build frontend UI components
5. Deploy to production with documentation
6. Continue with Phase 2, 3, 4

---

**Status:** Ready to begin implementation  
**Start:** Immediately  
**Next Checkpoint:** Phase 1 complete

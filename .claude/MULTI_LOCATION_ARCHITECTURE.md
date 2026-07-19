# Multi-Location Support Architecture Research

**Date:** 2026-07-18  
**Status:** Design Research  
**Requirement:** Track employee assignments to specific outlets/locations

---

## Executive Summary

To support multi-location businesses, the EMS needs:
1. **New table**: `locations` (outlets/branches)
2. **New junction table**: `employee_location_assignments` (many-to-many)
3. **Updated data model**: Employees can work at one or multiple locations
4. **Dashboard widgets**: Location count, employee distribution by location
5. **API changes**: Filter/search by location, bulk operations by location
6. **Reporting changes**: Payroll, attendance, and leave by location

**Estimated Effort:** 3-5 days of development (schema + API + dashboard)  
**Data Migration:** Low risk (add new tables, existing data unaffected)

---

## Current State Analysis

### Current Schema Relationships

```
institutions (1)
    ├── users (many)
    │   └── location_id: NULL (not location-aware)
    │
    ├── employees (many)
    │   ├── location_id: NULL (all employees tied only to institution)
    │   ├── department: TEXT (not location-aware)
    │   └── designation: TEXT
    │
    ├── payroll_runs (many)
    │   ├── run_id
    │   └── (no location filtering)
    │
    └── leaves, timesheets, projects (many)
        └── (no location awareness)
```

### Key Insight

**Current design**: One institution → multiple employees, but no location hierarchy. All employees are tied directly to the institution with no outlet/branch awareness.

**What's missing**:
- Employees can't be assigned to specific locations
- No way to track "Which outlets does Employee X work at?"
- No way to filter payroll, leaves, attendance by location
- Dashboard can't show "Location A has 45 employees, Location B has 32"

---

## Proposed Data Model

### 1. New Table: `locations`

```sql
CREATE TABLE locations (
    id                  SERIAL  PRIMARY KEY,
    institution_id      INTEGER NOT NULL REFERENCES institutions(id),
    name                TEXT    NOT NULL,              -- "Kuala Lumpur HQ", "Petaling Jaya Branch"
    code                TEXT    NOT NULL,              -- "KL_HQ", "PJ_BR" for easy reference
    address             TEXT,
    city                TEXT,
    state               TEXT,
    postal_code         TEXT,
    country             TEXT    DEFAULT 'Malaysia',
    phone               TEXT,
    manager_user_id     INTEGER REFERENCES users(id), -- Location manager (OPTIONAL)
    location_type       TEXT    DEFAULT 'branch',     -- "hq", "branch", "warehouse", "outlet"
    is_active           INTEGER DEFAULT 1,            -- Soft-delete via status
    capacity            INTEGER,                      -- How many employees this location can have
    
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    
    UNIQUE(institution_id, code)                      -- One code per institution
)

-- Indexes
CREATE INDEX idx_locations_institution ON locations(institution_id);
CREATE INDEX idx_locations_active ON locations(institution_id, is_active);
```

**Note:** `manager_user_id` is nullable (can be NULL). Locations can exist without an assigned manager.

### 2. New Table: `employee_location_assignments`

```sql
CREATE TABLE employee_location_assignments (
    id                      SERIAL  PRIMARY KEY,
    institution_id          INTEGER NOT NULL,
    employee_id             TEXT    NOT NULL,
    location_id             INTEGER NOT NULL REFERENCES locations(id),
    
    -- Assignment details
    assignment_type         TEXT    NOT NULL DEFAULT 'primary',  -- "primary", "secondary", "temporary"
    start_date              TEXT    NOT NULL,
    end_date                TEXT,                                 -- NULL = ongoing
    
    -- Reporting hierarchy per location
    reports_to_id           TEXT,                                 -- Employee ID of location manager (may differ from institution-wide reports_to)
    department_at_location  TEXT,                                 -- Dept assignment can be location-specific
    
    is_active               INTEGER DEFAULT 1,
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL,
    
    FOREIGN KEY (institution_id, employee_id) 
        REFERENCES employees(institution_id, employee_id),
    
    UNIQUE(employee_id, location_id, assignment_type)  -- Employee can only have one primary location
)

-- Indexes
CREATE INDEX idx_assignments_employee ON employee_location_assignments(employee_id);
CREATE INDEX idx_assignments_location ON employee_location_assignments(location_id);
CREATE INDEX idx_assignments_active ON employee_location_assignments(location_id, is_active);
```

### 3. Updates to Existing Tables

#### `employees` table - Add optional default location

```sql
-- Add column (backwards compatible)
ALTER TABLE employees 
    ADD COLUMN default_location_id INTEGER REFERENCES locations(id);

-- Existing employees without location assignment still work
-- (NULL means employee tied to entire institution)
```

#### `users` table - Add location scope for login

```sql
-- Optional: Restrict users to manage specific locations
ALTER TABLE users 
    ADD COLUMN default_location_id INTEGER REFERENCES locations(id);

-- Allows: "HR Manager for Location A only" vs "HR Manager for entire institution"
```

#### `payroll_runs` table - Add location scope

```sql
ALTER TABLE payroll_runs
    ADD COLUMN location_id INTEGER REFERENCES locations(id);
    
-- NULL = payroll run for entire institution
-- Not NULL = payroll run for specific location
```

---

## Data Model Decisions & Tradeoffs

| Decision | Choice | Why | Tradeoff |
|----------|--------|-----|----------|
| **Employee-Location Relationship** | Many-to-many | Employees may work at multiple outlets | Requires junction table, more complex queries |
| **Default Location in Employees** | Optional (nullable) | Existing employees unaffected | Must handle NULL case in queries |
| **Assignment Type** | Enum (primary/secondary/temporary) | Different tracking per assignment type | Adds complexity to assignment logic |
| **Location Manager** | User FK | Each location has manager for admin separation | Adds role management complexity |
| **Soft-delete Locations** | is_active flag | Preserve historical data | NULL values in reporting |

---

## Implementation Plan

### Phase 1: Database Schema (Day 1)

**Migration: `add_multi_location_support`**

```python
def upgrade():
    # 1. Create locations table
    op.execute("""
        CREATE TABLE locations (
            id SERIAL PRIMARY KEY,
            institution_id INTEGER NOT NULL REFERENCES institutions(id),
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            address TEXT,
            city TEXT,
            state TEXT,
            postal_code TEXT,
            country TEXT DEFAULT 'Malaysia',
            phone TEXT,
            manager_user_id INTEGER REFERENCES users(id),
            location_type TEXT DEFAULT 'branch',
            is_active INTEGER DEFAULT 1,
            capacity INTEGER,
            created_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(institution_id, code)
        )
    """)
    
    # 2. Create employee_location_assignments table
    op.execute("""
        CREATE TABLE employee_location_assignments (
            id SERIAL PRIMARY KEY,
            institution_id INTEGER NOT NULL,
            employee_id TEXT NOT NULL,
            location_id INTEGER NOT NULL REFERENCES locations(id),
            assignment_type TEXT NOT NULL DEFAULT 'primary',
            start_date TEXT NOT NULL,
            end_date TEXT,
            reports_to_id TEXT,
            department_at_location TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            FOREIGN KEY (institution_id, employee_id) REFERENCES employees(institution_id, employee_id),
            UNIQUE(employee_id, location_id, assignment_type)
        )
    """)
    
    # 3. Add columns to existing tables
    op.execute("ALTER TABLE employees ADD COLUMN default_location_id INTEGER REFERENCES locations(id)")
    op.execute("ALTER TABLE users ADD COLUMN default_location_id INTEGER REFERENCES locations(id)")
    op.execute("ALTER TABLE payroll_runs ADD COLUMN location_id INTEGER REFERENCES locations(id)")
    
    # 4. Create indexes
    op.execute("CREATE INDEX idx_locations_institution ON locations(institution_id)")
    op.execute("CREATE INDEX idx_assignments_employee ON employee_location_assignments(employee_id)")
    op.execute("CREATE INDEX idx_assignments_location ON employee_location_assignments(location_id)")
```

### Phase 2: API Endpoints (Day 2-3)

#### Location Management Endpoints

```python
# routers/locations.py

@router.post("/api/locations")
async def create_location(
    location_data: LocationCreate,
    current_user: User = Depends(get_current_user)
):
    """Create a new location/outlet for the institution"""
    # Validate permissions: only institution admin/superadmin

@router.get("/api/institutions/{inst_id}/locations")
async def list_locations(inst_id: int):
    """List all locations for an institution
    
    Response:
    {
        "locations": [
            {
                "id": 1,
                "name": "Kuala Lumpur HQ",
                "code": "KL_HQ",
                "employee_count": 45,
                "is_active": true
            }
        ],
        "total_locations": 1
    }
    """

@router.get("/api/locations/{location_id}")
async def get_location(location_id: int):
    """Get location details including employee count, capacity"""

@router.put("/api/locations/{location_id}")
async def update_location(location_id: int, location_data: LocationUpdate):
    """Update location details"""

@router.delete("/api/locations/{location_id}")
async def delete_location(location_id: int):
    """Soft-delete location (is_active = 0)"""
```

#### Employee Location Assignment Endpoints

```python
@router.post("/api/employees/{employee_id}/locations")
async def assign_employee_to_location(
    employee_id: str,
    assignment: EmployeeLocationAssignment
):
    """Assign employee to a location
    
    Body:
    {
        "location_id": 1,
        "assignment_type": "primary",  # "primary", "secondary", "temporary"
        "start_date": "2026-08-01",
        "end_date": null,              # NULL = ongoing
        "reports_to_id": "MGR001"      # Optional: location-specific manager
    }
    """

@router.get("/api/employees/{employee_id}/locations")
async def get_employee_locations(employee_id: str):
    """Get all locations where employee is assigned
    
    Response:
    {
        "locations": [
            {
                "location_id": 1,
                "location_name": "KL HQ",
                "assignment_type": "primary",
                "start_date": "2026-01-01",
                "end_date": null
            }
        ]
    }
    """

@router.put("/api/employees/{employee_id}/locations/{location_id}")
async def update_employee_location_assignment(
    employee_id: str,
    location_id: int,
    updates: EmployeeLocationUpdate
):
    """Update employee's assignment to a location"""

@router.delete("/api/employees/{employee_id}/locations/{location_id}")
async def remove_employee_from_location(employee_id: str, location_id: int):
    """Remove employee from location (set end_date = today)"""
```

#### Location Analytics Endpoints

```python
@router.get("/api/locations/{location_id}/stats")
async def get_location_stats(location_id: int):
    """Get statistics for a location
    
    Response:
    {
        "location_id": 1,
        "location_name": "KL HQ",
        "total_employees": 45,
        "active_employees": 44,
        "capacity": 100,
        "utilization_percent": 44,
        "employees_by_department": {
            "Engineering": 15,
            "Sales": 12,
            "Admin": 8
        },
        "employees_by_status": {
            "Active": 44,
            "On Leave": 1
        }
    }
    """

@router.get("/api/institutions/{inst_id}/location-summary")
async def get_institution_location_summary(inst_id: int):
    """Summary of all locations for an institution
    
    Response:
    {
        "total_locations": 5,
        "active_locations": 5,
        "total_employees": 200,
        "locations": [
            {"name": "KL HQ", "employee_count": 45},
            {"name": "PJ Branch", "employee_count": 38},
            ...
        ]
    }
    """
```

### Phase 3: Dashboard Widgets (Day 3-4)

#### New Dashboard Widgets

1. **Location Count Widget**
   ```
   ┌─────────────────────────────┐
   │ Your Locations              │
   │                             │
   │         5                   │  ← Total locations
   │                             │
   │ Active: 5  Inactive: 0      │
   └─────────────────────────────┘
   ```

2. **Location Distribution Widget**
   ```
   ┌──────────────────────────────┐
   │ Employees by Location        │
   │                              │
   │ KL HQ          ████░ 45      │
   │ PJ Branch      ███░░ 32      │
   │ Shah Alam      ██░░░ 18      │
   │ Subang         █░░░░ 12      │
   │ Petaling       █░░░░ 8       │
   │                              │
   │ Total: 115                   │
   └──────────────────────────────┘
   ```

3. **Location Capacity Widget**
   ```
   ┌──────────────────────────────┐
   │ Location Capacity            │
   │                              │
   │ KL HQ:      45/100 (45%)    │
   │ PJ Branch:  32/60  (53%)    │
   │ Shah Alam:  18/40  (45%)    │
   │                              │
   │ Avg Utilization: 48%         │
   └──────────────────────────────┘
   ```

4. **Location Manager Widget** (Optional)
   ```
   ┌──────────────────────────────┐
   │ Location Managers (Optional) │
   │                              │
   │ KL HQ          John Doe      │
   │ PJ Branch      Jane Smith    │
   │ Shah Alam      —             │  (No manager assigned)
   │                              │
   │ [Assign Managers]            │
   └──────────────────────────────┘
   ```
   *Manager field is optional. Locations can operate without assigned managers.*

#### Dashboard Component Structure

```jsx
// components/Dashboard/LocationWidgets.jsx

export function LocationSummaryWidget() {
  const { locations } = useLocations();
  
  return (
    <DashboardWidget title="Locations">
      <StatCard value={locations.length} label="Total Locations" />
      <StatCard value={locations.filter(l => l.is_active).length} label="Active" />
    </DashboardWidget>
  );
}

export function EmployeesByLocationWidget() {
  const { locations } = useLocations();
  
  return (
    <BarChart
      data={locations.map(l => ({
        name: l.name,
        employees: l.employee_count
      }))}
    />
  );
}

export function LocationCapacityWidget() {
  const { locations } = useLocations();
  
  return locations.map(location => (
    <CapacityBar
      location={location.name}
      used={location.employee_count}
      capacity={location.capacity}
    />
  ));
}
```

### Phase 4: Bulk Operations & Reports (Day 4-5)

#### Bulk Assignment
```python
@router.post("/api/employees/bulk-assign-location")
async def bulk_assign_location(
    assignments: List[BulkLocationAssignment],
    current_user: User = Depends(get_current_user)
):
    """Bulk assign multiple employees to locations
    
    Body:
    {
        "assignments": [
            {"employee_id": "EMP001", "location_id": 1, "start_date": "2026-08-01"},
            {"employee_id": "EMP002", "location_id": 2, "start_date": "2026-08-01"}
        ]
    }
    """
```

#### Location-Scoped Payroll
```python
@router.post("/api/payroll/runs")
async def create_payroll_run(
    run_data: PayrollRunCreate,
    current_user: User = Depends(get_current_user)
):
    """
    Create payroll run with optional location scope
    
    Body:
    {
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "location_id": 1  # Optional: if set, only include employees at this location
    }
    """
```

#### Reporting
```python
@router.get("/api/reports/employee-by-location")
async def report_employees_by_location(institution_id: int):
    """CSV/JSON export of all employees grouped by location"""

@router.get("/api/reports/payroll-by-location")
async def report_payroll_by_location(
    run_id: int,
    location_id: Optional[int] = None
):
    """Payroll report filtered by location"""

@router.get("/api/reports/leave-by-location")
async def report_leave_by_location(
    start_date: str,
    end_date: str,
    location_id: Optional[int] = None
):
    """Leave report filtered by location"""
```

---

## Database Query Patterns

### Get employees at a location

```sql
SELECT e.* FROM employees e
JOIN employee_location_assignments ela ON e.employee_id = ela.employee_id
WHERE ela.location_id = $1 AND ela.is_active = 1;
```

### Get locations for an employee

```sql
SELECT l.* FROM locations l
JOIN employee_location_assignments ela ON l.id = ela.location_id
WHERE ela.employee_id = $1 AND ela.is_active = 1
ORDER BY CASE 
    WHEN ela.assignment_type = 'primary' THEN 1
    WHEN ela.assignment_type = 'secondary' THEN 2
    ELSE 3 
END;
```

### Get location stats

```sql
SELECT 
    l.id,
    l.name,
    COUNT(DISTINCT ela.employee_id) as employee_count,
    l.capacity,
    ROUND(100.0 * COUNT(DISTINCT ela.employee_id) / l.capacity) as utilization_percent
FROM locations l
LEFT JOIN employee_location_assignments ela 
    ON l.id = ela.location_id AND ela.is_active = 1
WHERE l.institution_id = $1
GROUP BY l.id, l.name, l.capacity;
```

### Get location distribution pie chart data

```sql
SELECT l.name, COUNT(DISTINCT ela.employee_id) as count
FROM locations l
LEFT JOIN employee_location_assignments ela 
    ON l.id = ela.location_id AND ela.is_active = 1
WHERE l.institution_id = $1 AND l.is_active = 1
GROUP BY l.id, l.name
ORDER BY count DESC;
```

---

## API Response Models (Pydantic)

```python
# routers/schemas/locations.py

class LocationBase(BaseModel):
    name: str
    code: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "Malaysia"
    phone: Optional[str] = None
    manager_user_id: Optional[int] = None
    location_type: str = "branch"
    capacity: Optional[int] = None

class LocationCreate(LocationBase):
    pass

class LocationUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    manager_user_id: Optional[int] = None
    capacity: Optional[int] = None

class LocationResponse(LocationBase):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": 1,
            "institution_id": 5,
            "name": "Kuala Lumpur Headquarters",
            "code": "KL_HQ",
            "address": "123 Jln Merdeka",
            "city": "Kuala Lumpur",
            "state": "KL",
            "postal_code": "50050",
            "phone": "+603-1234-5678",
            "manager_user_id": 42,
            "location_type": "hq",
            "is_active": True,
            "capacity": 100,
            "employee_count": 45,
            "created_at": "2026-08-01 10:00:00",
            "updated_at": "2026-08-01 10:00:00"
        }
    })
    id: int
    institution_id: int
    is_active: bool
    employee_count: int
    created_at: str
    updated_at: str

class EmployeeLocationAssignmentBase(BaseModel):
    location_id: int
    assignment_type: str = "primary"  # "primary", "secondary", "temporary"
    start_date: str
    end_date: Optional[str] = None
    reports_to_id: Optional[str] = None
    department_at_location: Optional[str] = None

class EmployeeLocationAssignmentCreate(EmployeeLocationAssignmentBase):
    pass

class EmployeeLocationAssignmentResponse(EmployeeLocationAssignmentBase):
    id: int
    employee_id: str
    is_active: bool
    created_at: str
    updated_at: str

class LocationStatsResponse(BaseModel):
    location_id: int
    location_name: str
    total_employees: int
    active_employees: int
    capacity: Optional[int] = None
    utilization_percent: Optional[int] = None
    employees_by_department: Dict[str, int]
    employees_by_status: Dict[str, int]
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_locations.py

def test_create_location():
    """Test creating a new location"""
    
def test_get_location_stats():
    """Test location stats calculation"""
    
def test_assign_employee_to_location():
    """Test employee location assignment"""
    
def test_get_employees_at_location():
    """Test retrieving employees at a location"""
    
def test_remove_employee_from_location():
    """Test soft-deleting assignment"""
    
def test_cannot_assign_same_location_twice_primary():
    """Test unique constraint on primary assignment"""

def test_bulk_assign_locations():
    """Test bulk location assignment"""
```

### Integration Tests

```python
def test_payroll_respects_location_scope():
    """Ensure payroll run at location A only includes location A employees"""
    
def test_location_dashboard_widgets():
    """Test dashboard data calculations"""
    
def test_leave_request_by_location():
    """Test leave requests filtered by location"""
```

---

## Migration Path (For Existing Deployments)

### Step 1: Deploy New Schema
- Add new tables (locations, employee_location_assignments)
- Add columns to existing tables (default_location_id on employees)
- All existing data unaffected (no employee locations yet)

### Step 2: Data Population
```sql
-- Create "Main" location for each institution (no manager required)
INSERT INTO locations (institution_id, name, code, is_active, manager_user_id)
SELECT id, CONCAT(name, ' - Main'), CONCAT(code, '_MAIN'), 1, NULL
FROM institutions;

-- Assign all employees to their institution's main location
INSERT INTO employee_location_assignments (institution_id, employee_id, location_id, assignment_type, start_date)
SELECT i.id, e.employee_id, l.id, 'primary', COALESCE(e.start_date, '2026-01-01')
FROM employees e
JOIN institutions i ON e.institution_id = i.id
JOIN locations l ON l.institution_id = i.id AND l.code LIKE '%_MAIN';
```

**Note:** Location managers are optional - set to NULL by default. Assign managers later if needed.

### Step 3: Gradual API Adoption
- Add location endpoints
- Keep existing endpoints working (treat NULL location = entire institution)
- Gradually migrate UI to use location features

### Step 4: Enable Dashboard Widgets
- Roll out location widgets to dashboard
- Display location stats

---

## Backwards Compatibility

**Key Principle:** Existing code continues to work without location awareness.

| Scenario | Behavior |
|----------|----------|
| Employee with no location assignment | Treated as institution-level employee |
| Payroll run with no location_id | Includes all employees from institution |
| User with no default_location_id | Can manage entire institution |
| Leave/timesheet without location | Associated with employee's primary location |

---

## Performance Considerations

### Indexes Needed
```sql
CREATE INDEX idx_locations_institution ON locations(institution_id, is_active);
CREATE INDEX idx_assignments_employee ON employee_location_assignments(employee_id, is_active);
CREATE INDEX idx_assignments_location ON employee_location_assignments(location_id, is_active);
CREATE INDEX idx_assignments_active_date ON employee_location_assignments(is_active, end_date);
```

### Query Optimization
- Always filter by `is_active = 1` in junction table
- Use appropriate indexes on institution_id + status fields
- Denormalize employee_count on locations if needed (update via trigger)

---

## Security & RLS Considerations

### Multi-Tenancy (RLS Policies)
```sql
-- Locations must belong to correct institution
-- (Postgres RLS already enforced via app.current_institution_id)

-- Users can only see locations in their institution
-- Optionally: Users with default_location_id can only manage that location
```

### Permission Levels
1. **Superadmin** - Full access to all locations in all institutions
2. **Institution Admin** - Full access to all locations in their institution
3. **Location Manager** (Optional) - Can manage their assigned location (if assigned)
4. **HR Manager** - View all locations, manage assignments
5. **Employee** - View only their own locations

*Note: Location manager role is optional. Institutions may operate all locations without individual managers.*

---

## Open Questions & Considerations

1. **Can an employee be at multiple locations simultaneously?**
   - Current design: YES (secondary/temporary assignments)
   - Alternative: Only primary location (simpler)

2. **What if employee transfers between locations?**
   - Current design: Set end_date on old assignment, create new assignment
   - Maintains full audit trail

3. **Should departments be location-specific?**
   - Current design: Optional (department_at_location field)
   - Allows org structure to vary by location

4. **Are location managers mandatory?**
   - ✅ **Decision: NO - Location managers are OPTIONAL**
   - Locations can operate without assigned managers
   - Manager assignment is optional per location
   - All management can be handled centrally by institution admins

5. **How are leaves/timesheets handled for multi-location employees?**
   - Question: Should leave be tracked per location or institution-wide?
   - Recommendation: Requested at employee level, approved by institution admin or location manager (if assigned)

---

## Success Metrics

After implementation:
- ✅ Dashboard shows accurate location count
- ✅ Location distribution charts render correctly
- ✅ Payroll can be run per-location
- ✅ Employees can be assigned to multiple locations
- ✅ All existing functionality unchanged
- ✅ 0 flaky tests (test isolation by location)
- ✅ API response times < 500ms (even with location joins)

---

## Summary of Changes

| Component | Change | Complexity |
|-----------|--------|-----------|
| **Database** | Add 2 tables, 3 columns | Low |
| **API** | ~15 new endpoints | Medium |
| **Dashboard** | 4-5 new widgets | Medium |
| **Reports** | Filter by location | Medium |
| **Payroll** | Location-scoped runs | Medium |
| **Existing Code** | Backwards compatible | Low |

**Total Estimated Effort:** 3-5 days  
**Risk Level:** Low (no breaking changes)  
**Data Migration Risk:** Low (additive schema)

---

Generated: 2026-07-18  
For: Multi-location business support  
Status: Ready for development

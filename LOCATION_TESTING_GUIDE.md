# Production Location Feature Testing Guide

## Quick Test Plan

Test these endpoints in order to verify the multi-location feature is working end-to-end.

---

## 1. Create a Location

**Endpoint:** `POST /api/locations`

```bash
curl -X POST http://localhost:8000/api/locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "institution_id": 1,
    "name": "Kuala Lumpur HQ",
    "code": "KL_HQ",
    "city": "Kuala Lumpur",
    "state": "KL",
    "postal_code": "50000",
    "country": "Malaysia",
    "phone": "+60123456789",
    "location_type": "hq",
    "capacity": 100,
    "manager_user_id": null
  }'
```

**Expected Response (201 Created):**
```json
{
  "id": 1,
  "institution_id": 1,
  "name": "Kuala Lumpur HQ",
  "code": "KL_HQ",
  "city": "Kuala Lumpur",
  "state": "KL",
  "location_type": "hq",
  "capacity": 100,
  "employee_count": 0,
  "is_active": true,
  "manager_user_id": null,
  "created_at": "2026-07-18 15:30:00",
  "updated_at": "2026-07-18 15:30:00"
}
```

**Save the `id` from response** (will use as `{location_id}` below)

---

## 2. Create a Second Location

```bash
curl -X POST http://localhost:8000/api/locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "institution_id": 1,
    "name": "Penang Branch",
    "code": "PENANG_01",
    "city": "Penang",
    "state": "PG",
    "postal_code": "10000",
    "location_type": "branch",
    "capacity": 50
  }'
```

**Save the `id`** (will use as second location_id)

---

## 3. List All Locations

**Endpoint:** `GET /api/institutions/{institution_id}/locations`

```bash
curl http://localhost:8000/api/institutions/1/locations \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response (200 OK):**
```json
{
  "locations": [
    {
      "id": 1,
      "name": "Kuala Lumpur HQ",
      "code": "KL_HQ",
      "city": "Kuala Lumpur",
      "location_type": "hq",
      "employee_count": 0,
      "is_active": true
    },
    {
      "id": 2,
      "name": "Penang Branch",
      "code": "PENANG_01",
      "city": "Penang",
      "location_type": "branch",
      "employee_count": 0,
      "is_active": true
    }
  ],
  "total_count": 2,
  "active_count": 2
}
```

✅ **Verification:** You should see both locations listed

---

## 4. Get Location Details

**Endpoint:** `GET /api/locations/{location_id}`

```bash
curl http://localhost:8000/api/locations/1 \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response (200 OK):**
```json
{
  "id": 1,
  "institution_id": 1,
  "name": "Kuala Lumpur HQ",
  "code": "KL_HQ",
  "address": null,
  "city": "Kuala Lumpur",
  "state": "KL",
  "postal_code": "50000",
  "country": "Malaysia",
  "phone": "+60123456789",
  "location_type": "hq",
  "capacity": 100,
  "employee_count": 0,
  "is_active": true,
  "manager_user_id": null,
  "created_at": "2026-07-18 15:30:00",
  "updated_at": "2026-07-18 15:30:00"
}
```

---

## 5. Assign Employee to Location

**Endpoint:** `POST /api/employees/{employee_id}/locations`

```bash
curl -X POST http://localhost:8000/api/employees/EMP001/locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "location_id": 1,
    "assignment_type": "primary",
    "start_date": "2026-08-01"
  }'
```

**Expected Response (201 Created):**
```json
{
  "id": 1,
  "employee_id": "EMP001",
  "location_id": 1,
  "location_name": "Kuala Lumpur HQ",
  "location_code": "KL_HQ",
  "assignment_type": "primary",
  "start_date": "2026-08-01",
  "end_date": null,
  "is_active": true,
  "created_at": "2026-07-18 15:31:00",
  "updated_at": "2026-07-18 15:31:00"
}
```

✅ **Verification:** Employee is now assigned to location

---

## 6. Assign Same Employee to Second Location (Secondary)

```bash
curl -X POST http://localhost:8000/api/employees/EMP001/locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "location_id": 2,
    "assignment_type": "secondary",
    "start_date": "2026-08-01"
  }'
```

**Expected Response (201 Created):**
```json
{
  "id": 2,
  "employee_id": "EMP001",
  "location_id": 2,
  "location_name": "Penang Branch",
  "assignment_type": "secondary",
  "start_date": "2026-08-01",
  ...
}
```

✅ **Verification:** Employee can have multiple location assignments

---

## 7. Get Employee's All Location Assignments

**Endpoint:** `GET /api/employees/{employee_id}/locations`

```bash
curl http://localhost:8000/api/employees/EMP001/locations \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response (200 OK):**
```json
{
  "employee_id": "EMP001",
  "locations": [
    {
      "location_id": 1,
      "location_name": "Kuala Lumpur HQ",
      "location_code": "KL_HQ",
      "assignment_type": "primary",
      "start_date": "2026-08-01",
      "end_date": null,
      "is_active": true
    },
    {
      "location_id": 2,
      "location_name": "Penang Branch",
      "location_code": "PENANG_01",
      "assignment_type": "secondary",
      "start_date": "2026-08-01",
      "end_date": null,
      "is_active": true
    }
  ]
}
```

✅ **Verification:** Both assignments show correctly

---

## 8. View Location Statistics

**Endpoint:** `GET /api/locations/{location_id}/stats`

```bash
curl http://localhost:8000/api/locations/1/stats \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response (200 OK):**
```json
{
  "location_id": 1,
  "location_name": "Kuala Lumpur HQ",
  "total_employees": 1,
  "active_employees": 1,
  "capacity": 100,
  "utilization_percent": 1.0,
  "employees_by_department": {
    "Engineering": 1
  },
  "employees_by_status": {
    "Active": 1
  }
}
```

✅ **Verification:** Statistics show correct employee count

---

## 9. Update Location

**Endpoint:** `PUT /api/locations/{location_id}`

```bash
curl -X PUT http://localhost:8000/api/locations/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "name": "KL HQ - Updated",
    "capacity": 120
  }'
```

**Expected Response (200 OK):**
```json
{
  "id": 1,
  "name": "KL HQ - Updated",
  "capacity": 120,
  "updated_at": "2026-07-18 15:32:00",
  ...
}
```

✅ **Verification:** Location details updated

---

## 10. Bulk Assign Multiple Employees

**Endpoint:** `POST /api/employees/bulk-assign-locations`

```bash
curl -X POST http://localhost:8000/api/employees/bulk-assign-locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "assignments": [
      {
        "employee_id": "EMP002",
        "location_id": 1,
        "assignment_type": "primary",
        "start_date": "2026-08-01"
      },
      {
        "employee_id": "EMP003",
        "location_id": 1,
        "assignment_type": "primary",
        "start_date": "2026-08-01"
      },
      {
        "employee_id": "EMP004",
        "location_id": 2,
        "assignment_type": "primary",
        "start_date": "2026-08-01"
      }
    ]
  }'
```

**Expected Response (201 Created):**
```json
{
  "successful": 3,
  "failed": 0,
  "results": [
    {"employee_id": "EMP002", "location_id": 1, "status": "success"},
    {"employee_id": "EMP003", "location_id": 1, "status": "success"},
    {"employee_id": "EMP004", "location_id": 2, "status": "success"}
  ]
}
```

✅ **Verification:** Bulk operations work correctly

---

## 11. View Institution Location Summary

**Endpoint:** `GET /api/institutions/{institution_id}/location-summary`

```bash
curl http://localhost:8000/api/institutions/1/location-summary \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response (200 OK):**
```json
{
  "institution_id": 1,
  "total_locations": 2,
  "active_locations": 2,
  "total_employees": 4,
  "locations": [
    {
      "location_id": 1,
      "location_name": "Kuala Lumpur HQ",
      "employee_count": 3,
      "utilization_percent": 3.0,
      "capacity": 100
    },
    {
      "location_id": 2,
      "location_name": "Penang Branch",
      "employee_count": 1,
      "utilization_percent": 2.0,
      "capacity": 50
    }
  ]
}
```

✅ **Verification:** Institution-wide summary is correct

---

## 12. Test Error Conditions

### Try to Create Duplicate Location Code
```bash
curl -X POST http://localhost:8000/api/locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "institution_id": 1,
    "name": "Duplicate",
    "code": "KL_HQ"
  }'
```

**Expected Response (400 Bad Request):**
```json
{
  "detail": "Location code KL_HQ already exists for this institution"
}
```

✅ **Verification:** Duplicate prevention works

---

### Try to Assign Employee to Non-Existent Location
```bash
curl -X POST http://localhost:8000/api/employees/EMP001/locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "location_id": 99999,
    "assignment_type": "primary",
    "start_date": "2026-08-01"
  }'
```

**Expected Response (404 Not Found):**
```json
{
  "detail": "Location not found"
}
```

✅ **Verification:** Validation works

---

## Testing Checklist

- [ ] Create first location (HQ)
- [ ] Create second location (Branch)
- [ ] List all locations (see both)
- [ ] Get location details
- [ ] Assign employee to first location (primary)
- [ ] Assign same employee to second location (secondary)
- [ ] View employee's locations (see both)
- [ ] View location statistics (employee count correct)
- [ ] Update location (change capacity)
- [ ] Bulk assign multiple employees
- [ ] View institution summary (all locations + employees)
- [ ] Test duplicate code rejection
- [ ] Test invalid location reference rejection

---

## Verification Summary

✅ **All Green Indicators:**
- Locations create successfully with unique codes
- Employees can be assigned to multiple locations
- Assignment types enforce single primary per employee
- Statistics and counts are accurate
- Bulk operations work end-to-end
- Error validation prevents invalid operations
- Institution summary is comprehensive

---

## If Issues Occur

### 404 Not Found on Endpoints
- Verify API is running: `ps aux | grep python`
- Verify locations router is imported in `main.py`
- Check tables exist: `SELECT COUNT(*) FROM locations;`

### 500 Internal Server Error
- Check server logs: `tail -f logs/app.log`
- Verify database connection: Test basic query
- Verify migrations were applied

### 401 Unauthorized
- Verify Authorization header is present
- Verify token is valid and not expired
- Get a new token if needed

### Missing Fields in Response
- Tables are created but might be missing data
- Re-verify migration was applied fully
- Check for partial migration (core tables created, columns timed out)

---

## Next: Production Verification

Once these tests pass, you can:
1. **Add more locations** to test scalability
2. **Test with real employee IDs** from your system
3. **Monitor database performance** with location-scoped queries
4. **Plan location-based reporting** dashboards
5. **Consider UI integration** for location management

---

**Test Date:** 2026-07-18  
**Feature Status:** Production Ready  
**Expected Result:** All tests pass ✅

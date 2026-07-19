# Compensation Framework - Sample Data Seeding Guide

**Version:** 1.0  
**Created:** 2026-07-19  
**For Institution:** Mandrill Demo

---

## 📋 Overview

This guide explains how to load realistic software company compensation data into the EMS platform using sample seed data files.

### What Gets Created

✅ **8 Pay Grades** (IC1-IC4, L1, M1-M2, D1)  
✅ **9 Job Levels** (Entry through Director)  
✅ **13 Job Roles** (Junior Engineer through Engineering Director)  
✅ **2 Merit Review Cycles** (Annual + Mid-Year)  
✅ **Role-to-Grade Mappings** (linking roles to compensation bands)

---

## 🚀 Quick Start

### 1. Get Your Authentication Token

Login to the EMS app with an HR Manager or Admin account:

```bash
# Navigate to: https://ems-app.fly.dev
# Login → Open browser DevTools (F12)
# → Application tab → Local Storage
# → Find "token" key and copy the value
export EMS_TOKEN="eyJhbGc..."
```

### 2. Run the Seeding Script

```bash
cd /Users/kenneth/Claude/Code/ems
python seeds/load_compensation_to_api.py
```

**Output will look like:**
```
==============================================================================
  COMPENSATION FRAMEWORK - SAMPLE DATA LOADER
  Loading data into: https://ems-app.fly.dev
==============================================================================

✅ API is healthy

📊 Loading Pay Grades...
  ✓ IC1    (Junior IC - Entry Level) → ID 1
  ✓ IC2    (Mid-Level IC) → ID 2
  ✓ IC3    (Senior IC) → ID 3
  ...

📈 Loading Job Levels...
  ✓ ENTRY           (Entry Level) → ID 1
  ✓ JUNIOR          (Junior) → ID 2
  ...

✨ SEEDING COMPLETE!
```

---

## 📊 Compensation Structure Details

### Pay Grades (8 levels)

| Grade | Name | Level | Min Salary | Midpoint | Max Salary |
|-------|------|-------|-----------|----------|-----------|
| **IC1** | Junior IC - Entry Level | 1 | RM 3,500 | RM 4,200 | RM 5,000 |
| **IC2** | Mid-Level IC | 2 | RM 5,100 | RM 6,300 | RM 7,500 |
| **IC3** | Senior IC | 3 | RM 7,600 | RM 9,000 | RM 11,000 |
| **IC4** | Staff / Principal IC | 4 | RM 11,000 | RM 13,000 | RM 16,000 |
| **L1** | Tech Lead / Lead Engineer | 5 | RM 8,500 | RM 10,000 | RM 12,000 |
| **M1** | Engineering Manager | 6 | RM 10,000 | RM 12,000 | RM 15,000 |
| **M2** | Senior Engineering Manager | 7 | RM 13,000 | RM 15,500 | RM 19,000 |
| **D1** | Engineering Director | 8 | RM 16,000 | RM 19,000 | RM 25,000 |

**Design Philosophy:**
- Supports **individual contributor track** (IC1→IC4) for deep specialists
- Supports **management track** (M1→M2→D1) for leaders
- Supports **tech lead track** (L1) for hybrid roles
- Pay ranges include 30-40% spread (min to max) for merit room

### Job Levels (9 levels)

| Code | Name | Order | Description |
|------|------|-------|-------------|
| ENTRY | Entry Level | 1 | Fresh graduates or career starters (0-1 years) |
| JUNIOR | Junior | 2 | Junior engineers (1-2 years experience) |
| MID | Mid-Level | 3 | Mid-level engineers (2-5 years experience) |
| SENIOR | Senior | 4 | Senior engineers (5+ years experience) |
| STAFF | Staff/Principal | 5 | Staff-level engineers driving technical direction |
| LEAD | Tech Lead | 6 | Technical leads managing projects or small teams |
| MANAGER | Manager | 7 | Engineering managers overseeing teams |
| SENIOR_MANAGER | Senior Manager | 8 | Senior managers with multiple teams |
| DIRECTOR | Director | 9 | Director-level leadership |

### Job Roles (13 total)

**Individual Contributor Track:**
- Junior Software Engineer (ENG_JR) → IC1
- Software Engineer I (ENG_1) → IC1-IC2
- Software Engineer II (ENG_2) → IC2-IC3
- Senior Software Engineer (ENG_SR) → IC3-IC4
- Staff Engineer (ENG_STAFF) → IC4

**Specialized Tracks:**
- Frontend Engineer II (FE_2) → IC2-IC3
- Senior Frontend Engineer (FE_SR) → IC3-IC4
- Backend Engineer II (BE_2) → IC2-IC3
- Senior Backend Engineer (BE_SR) → IC3-IC4

**Leadership Track:**
- Engineering Tech Lead (TECH_LEAD) → L1
- Engineering Manager (ENG_MGR) → M1
- Senior Engineering Manager (ENG_SR_MGR) → M2
- Engineering Director (ENG_DIR) → D1

### Merit Review Cycles (2 cycles)

#### 1. Annual Merit Review
- **Period:** Jan 1 - Feb 28, 2026
- **Submission Deadline:** Feb 15, 2026
- **Budget Pool:** RM 1,500,000
- **Purpose:** Annual merit increase cycle for all employees

#### 2. Mid-Year Bonus Review
- **Period:** Jun 1 - Jul 31, 2026
- **Submission Deadline:** Jul 15, 2026
- **Budget Pool:** RM 800,000
- **Purpose:** Mid-year performance bonus distribution

---

## 💻 How to Use (Step-by-Step)

### Step 1: Verify Setup in UI

After seeding completes:

1. Navigate to **Settings → Compensation**
2. Check **Pay Grades** tab - should show 8 grades (IC1-D1)
3. Check **Job Levels** tab - should show 9 levels
4. Check **Merit Cycles** tab - should show 2 cycles

### Step 2: Assign Roles to Employees

1. Go to **Employees** list
2. Click an employee to open their profile
3. In the **Employment** tab, set their:
   - **Role:** e.g., "Software Engineer II" (role_code: ENG_2)
   - **Level:** Automatically determined by role
   - **Pay Grade:** Select from available grades (e.g., IC2 or IC3)
4. Click **Save**

### Step 3: Set Employee Compensation

1. In employee profile, go to **Employment** tab
2. Click "Set Compensation" or look for compensation section
3. Set:
   - **Base Salary:** e.g., RM 6,000 (within IC2 range: 5,100-7,500)
   - **Effective Date:** e.g., 2026-01-01
   - **Pay Grade:** IC2 (pre-filled based on role)
4. Save

### Step 4: Create Merit Recommendations

1. Go to **Settings → Compensation → Merit Cycles**
2. Click on a cycle (e.g., "2026 Annual Merit Review")
3. Click "Add Recommendation"
4. Fill in:
   - **Employee:** Select from list
   - **Recommended Increase %:** e.g., 5%
   - **Reason:** e.g., "Outstanding performance on Platform Migration"
5. Submit
6. After approval, salary adjustment is tracked in history

### Step 5: Monitor Pay Equity

1. Go to **Settings → Compensation**
2. Check **Pay Equity Analysis** tab
3. View reports on:
   - Gender pay gap
   - Department salary distribution
   - Role-based compensation consistency

---

## 🔄 Advanced Usage

### Custom Salary Structures

To create role-specific compensation packages:

```bash
# Use the API to add salary structure templates
curl -X POST https://ems-app.fly.dev/api/compensation/salary-structures \
  -H "Authorization: Bearer $EMS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "structure_name": "Frontend Engineer II - Standard",
    "structure_type": "role",
    "applicable_to_id": 5,  # FE_2 role ID from seeding
    "description": "Base + housing allowance + performance bonus"
  }'
```

### Bulk Merit Cycle Import

To import merit recommendations in bulk:

```bash
# Prepare CSV: employee_id, recommended_increase_percent, reason
# Then POST to /api/compensation/merit-recommendations with array of objects
```

### Salary History Tracking

All salary changes are automatically tracked with:
- **Previous salary & grade**
- **New salary & grade**
- **Change type** (merit_increase, promotion, adjustment, role_change)
- **Approval status** (Pending, Approved, Rejected)
- **Audit trail** with dates and approver info

---

## 🛠️ Troubleshooting

### Script Returns 401 Unauthorized

```bash
# Fix: Token is invalid or expired
# Re-login and get fresh token:
export EMS_TOKEN="new_token_here"
python seeds/load_compensation_to_api.py
```

### Script Returns 403 Forbidden

```bash
# Fix: User account doesn't have HR Manager role
# Check:
# 1. Are you logged in with an HR Manager account?
# 2. Go to Settings → Users, verify your role is 'hr_manager' or 'superadmin'
```

### Pay Grades Show But Roles Don't Appear

```bash
# Fix: Job levels must exist before roles can be created
# Check the script ran all steps:
#   1. ✓ Pay Grades loaded
#   2. ✓ Job Levels loaded
#   3. ✓ Job Roles loaded
#   4. ✓ Mappings created
```

### Error: "Duplicate grade_code"

```bash
# Fix: Pay grade with that code already exists
# Solution A: Delete existing grade and re-run seeder
# Solution B: Modify SAMPLE_DATA to use different codes
```

---

## 📖 Sample Queries

### Get All Pay Grades

```bash
curl -X GET https://ems-app.fly.dev/api/compensation/pay-grades \
  -H "Authorization: Bearer $EMS_TOKEN"
```

### Get Employee's Current Compensation

```bash
curl -X GET https://ems-app.fly.dev/api/compensation/employees/EMP001/compensation \
  -H "Authorization: Bearer $EMS_TOKEN"
```

### Get Salary History for Employee

```bash
curl -X GET https://ems-app.fly.dev/api/compensation/salary-changes/EMP001 \
  -H "Authorization: Bearer $EMS_TOKEN"
```

### Generate Pay Equity Report

```bash
curl -X GET https://ems-app.fly.dev/api/compensation/pay-equity/report \
  -H "Authorization: Bearer $EMS_TOKEN"
```

---

## 📝 Typical Software Company Compensation Benchmarks (Reference)

**Malaysia (KL/Selangor, 2026):**
- Junior Engineer (0-2 yrs): RM 3.5K-5K
- Mid Engineer (2-5 yrs): RM 5K-8K
- Senior Engineer (5+ yrs): RM 8K-12K
- Tech Lead: RM 8.5K-12K
- Engineering Manager (5-10 direct): RM 10K-15K
- Senior Manager (10+ direct): RM 13K-20K
- Director: RM 16K-25K

*Sample data uses mid-range benchmarks suitable for Kuala Lumpur tech hub.*

---

## 🔐 Security Notes

- **Tokens are sensitive** - store in environment variables, not in code
- **API requires authentication** - all endpoints check `Authorization: Bearer` header
- **Role-based access** - only HR Manager/Admin can modify compensation
- **Data is multi-tenant** - isolated by institution_id automatically
- **Audit trail enabled** - all changes logged with timestamps and user info

---

## 📚 Related Files

- **Schemas:** `core/compensation_schemas.py` - Pydantic validation models
- **API Routes:** `routers/compensation.py` - 15 endpoints for CRUD operations
- **Tests:** `tests/test_compensation.py` - 27 integration tests
- **Documentation:** `COMPENSATION_FRAMEWORK.md` - Complete technical reference
- **Frontend:** `static/js/compensation.js` - UI management functions

---

## ✨ Next Steps

After seeding:

1. ✅ Verify all data loads into UI
2. 🎯 Assign roles to 5-10 test employees
3. 📊 Set compensation for those employees
4. 🔄 Create merit recommendations for the annual cycle
5. 📈 Review pay equity report for any gaps
6. 🎓 Train HR team on compensation workflows

---

## 📞 Support

For issues or questions:
- Check logs: `python seeds/load_compensation_to_api.py --verbose`
- Review API docs: See `/COMPENSATION_FRAMEWORK.md`
- Test endpoints: Use the curl examples above
- Check health: `curl https://ems-app.fly.dev/api/health`

---

**Happy seeding! 🚀**

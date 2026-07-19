# EMS Seed Data - Compensation Framework

Sample data files for quickly setting up a realistic software company compensation structure in the EMS platform.

## Files

- **`compensation_setup_software.py`** - Sample data definition with realistic Malaysian tech company salary ranges
- **`load_compensation_to_api.py`** - Python script to load sample data via API
- **`COMPENSATION_SEEDING_GUIDE.md`** - Complete guide with examples and troubleshooting
- **`__init__.py`** - Python package marker

## Quick Start

### 1. Login and Get Token

```bash
# Login at: https://ems-app.fly.dev
# DevTools (F12) → Application → Local Storage → copy "token"
export EMS_TOKEN="your_token_here"
```

### 2. Load Sample Data

```bash
cd /Users/kenneth/Claude/Code/ems
python seeds/load_compensation_to_api.py
```

**Expected output:**
```
✅ API is healthy
📊 Loading Pay Grades...  [8 created]
📈 Loading Job Levels...  [9 created]
👨‍💼 Loading Job Roles...    [13 created]
🎯 Loading Merit Cycles... [2 created]
✨ SEEDING COMPLETE!
```

### 3. Verify in UI

Navigate to **Settings → Compensation** and check:
- ✅ Pay Grades tab shows 8 grades (IC1-D1)
- ✅ Job Levels tab shows 9 levels
- ✅ Merit Cycles tab shows 2 cycles

## What Gets Created

### 💰 8 Pay Grades
Individual contributor, tech lead, manager, and director tracks with realistic salary ranges:
- IC1: RM 3,500-5,000 (entry)
- IC2: RM 5,100-7,500 (mid)
- IC3: RM 7,600-11,000 (senior)
- IC4: RM 11,000-16,000 (staff)
- L1: RM 8,500-12,000 (tech lead)
- M1: RM 10,000-15,000 (manager)
- M2: RM 13,000-19,000 (senior manager)
- D1: RM 16,000-25,000 (director)

### 📊 9 Job Levels
Hierarchical levels: Entry → Junior → Mid → Senior → Staff → Lead → Manager → Senior Manager → Director

### 👨‍💼 13 Job Roles
- 5 general engineer roles (Junior → Staff)
- 4 specialized roles (Frontend & Backend II, Senior)
- 3 leadership roles (Tech Lead, Engineering Manager, Senior Manager, Director)

### 🎯 2 Merit Cycles
- Annual Merit Review: Jan-Feb 2026 (RM 1.5M budget)
- Mid-Year Bonus Review: Jun-Jul 2026 (RM 800K budget)

## Configuration

### Custom Token
```bash
python seeds/load_compensation_to_api.py --token "eyJhbGc..."
```

### Custom API URL (for local testing)
```bash
python seeds/load_compensation_to_api.py --api-url http://localhost:8000
```

### Verbose Output
```bash
python seeds/load_compensation_to_api.py --verbose
```

## After Seeding

1. **Assign roles to employees** - Set their job role in Employee profile
2. **Set compensation** - Assign base salary and pay grade
3. **Track salary changes** - Automatic audit trail with history
4. **Create merit recommendations** - Propose increases via merit cycles
5. **Analyze pay equity** - Generate reports for gender/department gaps

## Troubleshooting

See `COMPENSATION_SEEDING_GUIDE.md` for:
- 401/403 authentication errors
- Duplicate key errors
- Missing dependencies
- API health checks
- Sample curl commands

## For Malaysia-Based Companies

The sample data uses realistic salary benchmarks for Kuala Lumpur tech companies (2026):
- Accounts for cost of living in major KL tech hub
- Follows market standards for experienced engineers
- Includes proper spacing for merit increases (30-40% range per grade)
- Compatible with Malaysian employment laws and Bursa Malaysia corporate practices

## File Sizes

- `compensation_setup_software.py` - ~11 KB (sample data + display)
- `load_compensation_to_api.py` - ~11 KB (seeding CLI + API client)
- `COMPENSATION_SEEDING_GUIDE.md` - ~11 KB (complete guide + examples)

## Next Steps

After successful seeding:
1. ✅ View data in Settings → Compensation
2. 🎯 Assign roles to test employees
3. 📊 Set up employee compensation packages
4. 🔄 Create merit review recommendations
5. 📈 Run pay equity analysis reports

---

**Status:** Production-ready seed data ✨  
**Institution:** Mandrill Demo  
**Date Created:** 2026-07-19

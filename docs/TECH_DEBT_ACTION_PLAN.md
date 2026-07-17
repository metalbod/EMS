# Tech-Debt Action Plan - Updated

**Status**: Skipping CRITICAL backups/rotations, focusing on remaining tech-debt  
**Updated**: 2026-07-17  
**Scope**: HIGH and MEDIUM priority items

---

## Decisions Made

| Item | Status | Reason |
|------|--------|--------|
| ✅ Sentry Alerts | COMPLETED | Wired today |
| ✅ UptimeRobot | COMPLETED | Set up today |
| ⏭️ Backup Policy | DEFERRED | Requires paid plan |
| ⏭️ Secrets Rotation | DEFERRED | Focus on code improvements |
| ❌ On-Call Runbook | KEEP DOCS | Reference only |

---

## Remaining Tech-Debt Roadmap

### HIGH Priority (8 days total)

#### 1. Manual Connection Cleanup 🔴 Priority 24
**Effort**: 3 days | **Impact**: High | **Risk**: Medium

**Problem**: 325 `conn.close()` calls scattered across code  
**Solution**: Create `@db_session` decorator for auto-cleanup

**Benefits**:
- Prevents connection pool exhaustion
- Reduces boilerplate code
- Safer against forgotten close() calls

**Files affected**: All routers (13 files, ~13 functions each)

**Approach**:
1. Create `core/db_session.py` with decorator
2. Refactor 20% of endpoints as PoC (payroll, employees)
3. Roll out to remaining routers
4. Remove manual try/finally patterns

**Timeline**: Week of 2026-07-22

---

#### 2. Split main.py 🟠 Priority 24
**Effort**: 2 days | **Impact**: High | **Risk**: Low

**Problem**: main.py is 1200 lines (800+ is schema DDL)  
**Solution**: Move remaining schema to Alembic migrations

**Benefits**:
- Improves readability
- Schema is versioned like code
- Easier to maintain

**Current state**:
- init_db() = 800 lines of CREATE TABLE
- Alembic migrations = 5 files

**Approach**:
1. Audit current schema in init_db_body()
2. Create Alembic migrations for CREATE TABLE statements
3. Keep only ALTER TABLE ADD COLUMN (for backwards compat)
4. Delete old schema from main.py

**Timeline**: Week of 2026-07-22

---

#### 3. Monitoring Dashboard 🟠 Priority 32
**Effort**: 3 days | **Impact**: High | **Risk**: Low

**Status**: 50% complete (Sentry + UptimeRobot wired)

**What's left**:
- Fly.io metrics dashboard
- Add to on-call runbook
- Daily monitoring checklist

**Approach**:
1. Create Fly.io metrics dashboard (CPU, memory, response time)
2. Document in on-call runbook
3. Add to daily standup checklist

**Timeline**: Week of 2026-07-29

---

### MEDIUM Priority (11 days total)

#### 4. Type Hints 🟡 Priority 15
**Effort**: 5 days | **Impact**: Medium | **Risk**: Low

**Problem**: ~180 functions missing return type hints  
**Solution**: Add return types to endpoints and helpers

**Benefits**:
- Better IDE autocomplete
- Improved code documentation
- Catches type errors earlier

**Quick wins**:
- All endpoint functions (30 min)
- Core helpers: db.py, audit.py, deps.py (1 hour)
- Remaining routers (3 days)

**Timeline**: Week of 2026-07-29

---

#### 5. Split Large Routers 🟡 Priority 12
**Effort**: 4 days | **Impact**: Medium | **Risk**: Medium

**Problem**: 
- recruitment.py = 858 lines (31 functions)
- performance.py = 650 lines (26 functions)

**Solution**: Split into sub-routers by domain

**Recruitment splits**:
- candidates.py (interviews, scores)
- requisitions.py (job postings)
- offers.py (offer letters)

**Performance splits**:
- cycles.py (performance cycles)
- appraisals.py (employee reviews)
- payouts.py (merit increments, bonuses)

**Timeline**: Week of 2026-08-05

---

#### 6. Architecture Decision Records 🟡 Priority 8
**Effort**: 2 days | **Impact**: Low | **Risk**: Low

**Purpose**: Document design choices for future contributors

**ADRs to create**:
1. Two-role database split (app role vs admin role)
2. Celery for async operations
3. Vanilla JS instead of framework
4. Postgres RLS for multi-tenancy
5. Alembic migrations + init_db()

**Format**: docs/ADR-001-two-role-database-split.md

**Timeline**: Week of 2026-08-12

---

### OPTIONAL (10+ days)

#### 7. Test Database Isolation
**Effort**: 5 days | **Priority**: 8

Docker Compose test environment for full test isolation

#### 8. WebSocket Task Progress
**Effort**: 5 days | **Priority**: 14

Real-time task status updates (polling works fine, this is enhancement)

---

## Recommended Starting Order

**This Week (Week of 2026-07-22)**:
1. **Connection Cleanup** (3 days) - High impact, foundational
2. **Split main.py** (2 days) - Improves codebase navigation

**Next Week (Week of 2026-07-29)**:
3. **Type Hints** (5 days) - Developer experience improvement
4. **Monitoring Dashboard** (3 days) - Complete monitoring setup

**Following Week (Week of 2026-08-05)**:
5. **Split Routers** (4 days) - Code organization
6. **ADRs** (2 days) - Documentation

---

## Effort Summary

| Priority | Count | Est. Effort | Value |
|----------|-------|-------------|-------|
| HIGH | 3 | 8 days | Foundation for codebase |
| MEDIUM | 3 | 11 days | Code quality |
| OPTIONAL | 2 | 10+ days | Future enhancements |
| **TOTAL** | **8** | **~3 weeks** | Significant improvement |

---

## Implementation Path

### Week 1: Foundation (HIGH priority)
```
Mon-Wed: Connection Cleanup (3 days)
  - Create @db_session decorator
  - Test with payroll endpoints
  - Roll out gradually

Thu-Fri: Split main.py (2 days)
  - Move schema to Alembic
  - Keep backwards compat
  - Test thoroughly
```

### Week 2: Code Quality (MEDIUM)
```
Mon-Fri: Type Hints (5 days)
  - Endpoints first (quick wins)
  - Core helpers (1 day)
  - Routers (3 days)
  
  PARALLEL:
  - Monitoring Dashboard (3 days)
```

### Week 3: Organization (MEDIUM)
```
Mon-Thu: Split Routers (4 days)
  - Recruitment (2 days)
  - Performance (2 days)

Fri: ADRs (1 day)
```

---

## Success Criteria

When complete, you'll have:

```
✅ Connection management automated (@db_session)
✅ main.py reduced to ~400 lines
✅ All endpoints have return types
✅ Large routers split into focused modules
✅ Monitoring dashboard operational
✅ Architecture decisions documented
✅ Code quality significantly improved
✅ Easier for new contributors to navigate
✅ Less boilerplate/manual patterns
```

**Result**: ~3 weeks of focused tech-debt reduction  
**Impact**: Improved codebase quality, reduced maintenance burden

---

## Next Step

Ready to start **Connection Cleanup** this week? I can:

1. Create the `@db_session` decorator
2. Refactor payroll and employees routers as PoC
3. Document the pattern for other routers

Or pick a different HIGH priority item to start with.

---

**Status**: Ready to proceed  
**No code changes needed yet** - waiting for your choice

---

*All docs and verification scripts from CRITICAL items are still available for future reference.*

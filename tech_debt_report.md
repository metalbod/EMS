# EMS Technical Debt Audit
Generated: 2026-07-17

## 1. CODE QUALITY DEBT

### 1.1 Incomplete Type Hints (180 functions)
- **Impact**: 3/5 - IDE autocomplete, future refactoring harder
- **Risk**: 2/5 - Type safety for future changes reduced
- **Effort**: 3/5 - Systematic but time-consuming
- **Priority**: (3+2) x (6-3) = 15

Type hints missing on ~180 functions across routers and core modules.
Especially problematic for functions returning complex dicts or handling
multiple data types.

**Quick wins**:
- Add return type hints to all endpoint functions (affects client contracts)
- Add type hints to core helpers (db.py, audit.py, deps.py)
- Use mypy --strict to validate

### 1.2 Manual Connection Management (325 conn.close() calls)
- **Impact**: 2/5 - Boilerplate noise, forgetting to close leaks connections
- **Risk**: 4/5 - Connection pool exhaustion under load
- **Effort**: 2/5 - Context manager abstraction
- **Priority**: (2+4) x (6-2) = 24

Every endpoint manually calls conn.close() in try/finally. Risk of
connection leaks if new code forgets the pattern. Better: context manager
or dependency that auto-closes.

**Solution**: Create @db_session decorator or context manager:
```python
@db_session
def my_endpoint(...):
    conn = get_db()  # auto-closed on exit
```

### 1.3 Repetitive Error Handling (75 try-except blocks)
- **Impact**: 2/5 - Code duplication, maintenance burden
- **Risk**: 1/5 - Low risk but high noise
- **Effort**: 3/5 - Extract error handler middleware
- **Priority**: (2+1) x (6-3) = 9

Endpoints repeat the same error patterns: catch IntegrityError, ValidationError,
HTTPException, then rollback and raise. Could be unified in middleware.

---

## 2. ARCHITECTURE DEBT

### 2.1 main.py is 1200 Lines (Including Schema)
- **Impact**: 4/5 - Hard to navigate, onboarding friction
- **Risk**: 2/5 - Low immediate risk, but fragile for changes
- **Effort**: 2/5 - Move schema to separate file
- **Priority**: (4+2) x (6-2) = 24

_init_db_body() is 800+ lines of raw SQL and migrations. This is not
easily testable or versionable compared to Alembic migrations (which are
now the official path). The init_db() logic itself (the lock, etc.) is
good and can stay, but schema should be Alembic-only.

**Plan**: 
1. Create migration that stamps current schema as baseline
2. Migrate remaining init_db() CREATE TABLE statements to alembic versions
3. Delete CREATE TABLE from init_db_body(); keep only ALTER TABLE ADD COLUMN
   for backwards-compat idempotency

### 2.2 Recruitment & Performance Routers are Large (858 + 650 lines)
- **Impact**: 2/5 - Navigation and testing overhead
- **Risk**: 2/5 - Becoming harder to understand
- **Effort**: 3/5 - Split into sub-routers
- **Priority**: (2+2) x (6-3) = 12

Both files could be split by domain (e.g., recruitment into
candidates/requisitions/interviews/offers, performance into
cycles/appraisals/payouts). Currently monolithic.

**Benefit**: Easier to test, easier to find relevant code, clearer
responsibility boundaries.

---

## 3. TEST DEBT

### 3.1 Missing WebSocket Tests for Task Progress
- **Impact**: 3/5 - Async task progress isn't validated in tests
- **Risk**: 4/5 - Unknown behavior in production
- **Effort**: 4/5 - Requires WebSocket test client setup
- **Priority**: (3+4) x (6-4) = 14

Celery tasks run in tests via CELERY_TASK_ALWAYS_EAGER=true and clients
poll via GET /api/tasks/{id}. WebSocket progress updates (Phase 2.2.3
optional) have no test coverage yet.

**Note**: This is optional; polling pattern is already solid.

### 3.2 Integration Tests Only Use Shared DB
- **Impact**: 2/5 - Can't test dangerous operations, test isolation concerns
- **Risk**: 2/5 - Tests are read-only; low risk
- **Effort**: 4/5 - Requires test DB container setup
- **Priority**: (2+2) x (6-4) = 8

All tests use the real DATABASE_URL in .env. No test isolation at DB
level; relies on read-only test discipline. Works but not ideal for
team growth.

**Future**: Docker Compose test database for full isolation.

---

## 4. INFRASTRUCTURE DEBT

### 4.1 No Fly.io Secrets Rotation Policy
- **Impact**: 3/5 - Secrets sit unchanged indefinitely
- **Risk**: 5/5 - Exposure from leaked credentials, employee turnover
- **Effort**: 2/5 - Document + automate via GitHub Actions
- **Priority**: (3+5) x (6-2) = 40 🔴 HIGH

JWT_SECRET, DATABASE_URL, etc. are set once in Fly.io and never rotated.
If leaked or employee leaves, no automated way to refresh.

**Solution**: Quarterly manual rotation documented; future: GitHub Actions
scheduled job to rotate via Fly.io API.

### 4.2 No Monitoring / Alerting
- **Impact**: 4/5 - Incidents undetected until customer reports
- **Risk**: 4/5 - Silent failures, data corruption, etc.
- **Effort**: 3/5 - Sentry already configured; wire up dashboard
- **Priority**: (4+4) x (6-3) = 32 🔴 HIGH

Sentry is configured but has no alerts wired. Fly.io has no custom
metrics (CPU, memory, request latency tracked by platform but no
thresholds). No on-call runbook.

**Solution**:
1. Configure Sentry issue alerts (email on new errors)
2. Set up Fly.io metrics dashboard (response time, error rate)
3. Write oncall runbook (what to check, who to page)

### 4.3 No Backup Policy
- **Impact**: 5/5 - Data loss means service down
- **Risk**: 5/5 - Supabase can fail; no disaster recovery
- **Effort**: 1/5 - Supabase automated backups are free tier option
- **Priority**: (5+5) x (6-1) = 50 🔴🔴 CRITICAL

Supabase (PostgreSQL) is the single source of truth. No documented backup
plan. If the database is corrupted or deleted, the service is gone.

**Solution**: Enable Supabase automated backups (daily), test restore
monthly.

---

## 5. DOCUMENTATION DEBT

### 5.1 No Oncall / Incident Response Runbook
- **Impact**: 4/5 - Oncall person has no guide
- **Risk**: 4/5 - Slow response time, mistakes under pressure
- **Effort**: 2/5 - Write markdown + checklist
- **Priority**: (4+4) x (6-2) = 32 🔴 HIGH

No documentation for: how to check health, common errors, rollback procedure,
when to wake up senior eng, escalation paths.

**Template**:
- Health checks (GET /health, Fly.io dashboard, Sentry)
- Common errors and fixes (deadlock, connection pool exhausted, etc.)
- Rollback (git revert, fly deploy --image)
- Escalation (who is on-call, who to page)

### 5.2 No Architecture Decision Records (ADRs)
- **Impact**: 2/5 - New contributors confused about design choices
- **Risk**: 2/5 - Re-opening settled decisions
- **Effort**: 2/5 - Write ADRs retroactively
- **Priority**: (2+2) x (6-2) = 8

Why two database roles? Why Celery for async? Why vanilla JS? These are
documented inline but not in a searchable format.

---

## 6. DEPENDENCY DEBT

### 6.1 fastapi==0.139.0 (Check for updates)
- **Impact**: 1/5 - Security/stability but infrequent changes
- **Risk**: 2/5 - Future breaking changes
- **Effort**: 1/5 - Update and test
- **Priority**: (1+2) x (6-1) = 15

Dependabot is configured. Should auto-create PRs weekly. Verify PRs are
being created and merged.

---

## PRIORITIZED TECH-DEBT ROADMAP

### CRITICAL (Do ASAP)
1. **Backup Policy** - Priority 50 - Estimate 1 day
   - Enable Supabase automatic backups
   - Document restore procedure
   - Test monthly restore

2. **Secrets Rotation Policy** - Priority 40 - Estimate 2 days
   - Document quarterly rotation process
   - Create GitHub Actions workflow (or manual checklist)
   - Test JWT_SECRET rotation end-to-end

### HIGH (Next Sprint)
3. **Monitoring & Alerting** - Priority 32 - Estimate 3 days
   - Wire Sentry alerts
   - Create Fly.io metrics dashboard
   - Write oncall runbook

4. **Manual Connection Cleanup** - Priority 24 - Estimate 3 days
   - Create @db_session decorator or context manager
   - Refactor 20% of endpoints as PoC
   - Measure connection pool improvements

5. **Split main.py Schema** - Priority 24 - Estimate 2 days
   - Move remaining init_db() DDL to Alembic
   - Keep only ALTER TABLE idempotency checks
   - Simplify onboarding

### MEDIUM (Nice-to-have)
6. **Type Hints** - Priority 15 - Estimate 5 days
   - Add return types to all endpoints
   - Add types to core helpers
   - Run mypy --strict

7. **Split Recruitment & Performance Routers** - Priority 12 - Estimate 4 days
   - Split recruitment into sub-routers
   - Split performance into sub-routers
   - Update imports and tests

8. **Architecture Decision Records (ADRs)** - Priority 8 - Estimate 2 days
   - Document two-role DB split
   - Document Celery choice for async
   - Document vanilla JS choice

### OPTIONAL (Future)
9. **Test DB Isolation** - Priority 8 - Estimate 5 days
   - Docker Compose test database
   - Update conftest.py
   - Run full integration test suite in isolation

10. **WebSocket Task Progress** - Priority 14 - Estimate 5 days
    - Implement WebSocket endpoint for task progress
    - Add client-side WebSocket listener
    - Write WebSocket tests (requires test setup)

---

## SUMMARY

| Priority | Count | Est. Effort | Impact |
|----------|-------|-------------|--------|
| CRITICAL | 2 | 3 days | Service availability & security |
| HIGH | 3 | 8 days | Observability, maintainability |
| MEDIUM | 3 | 11 days | Code quality, developer experience |
| OPTIONAL | 2 | 10 days | Nice-to-have improvements |

**Recommended First Sprint**: CRITICAL + HIGH items = 11 days effort
- High impact on production stability
- Relatively low effort (mostly documentation + configuration)

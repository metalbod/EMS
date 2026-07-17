# EMS On-Call Runbook

**Last Updated**: 2026-07-17  
**On-Call Owner**: Kenneth Yong

This guide helps you respond to production incidents quickly and accurately.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Health Check Procedures](#health-check-procedures)
3. [Common Incidents](#common-incidents)
4. [Escalation & Communication](#escalation--communication)
5. [Post-Incident Review](#post-incident-review)

---

## Quick Start

### 🚨 You've Been Paged

**First 30 seconds**:

```
1. Take a deep breath — most issues are recoverable
2. Check Sentry or alert details for what triggered it
3. Determine severity:
   - 🔴 CRITICAL: Service completely down, data at risk
   - 🟠 HIGH: Major feature broken, customers affected
   - 🟡 MEDIUM: Feature degraded, non-critical errors
   - 🔵 LOW: Single user affected, error traces
```

### Access Your Tools

Keep these bookmarks ready:

| Tool | URL | Purpose |
|------|-----|---------|
| **Fly.io Dashboard** | https://fly.io/dashboard | App status, deployments, logs |
| **Sentry** | https://sentry.io | Error tracking, alerts |
| **Supabase** | https://app.supabase.com | Database, backups |
| **GitHub** | https://github.com/metalbod/EMS | Source code, CI/CD |

### Login Reminders

```bash
# Fly.io CLI
fly auth login

# Check current deployment
flyctl status
flyctl logs --tail 20

# Check if app is responding
curl https://yourdomain.com/health
```

---

## Health Check Procedures

### Level 1: Basic Health Check (2 minutes)

```bash
# 1. Application health endpoint
curl -s https://yourdomain.com/health | jq .
# Expected: {"status": "ok"}
# If connection refused → app is down
# If any error → database connection failed

# 2. Check Fly.io dashboard
flyctl status
# Look for: all instances "Running", no recent crashes

# 3. Check recent logs
flyctl logs --tail 30
# Look for: ERROR, exception, panic, failed to connect
```

### Level 2: Database Health (2 minutes)

If `/health` returns error or database-related logs appear:

```bash
# Via Supabase Dashboard:
# 1. Go to Settings → Database
# 2. Look for "Connection state" — should be green
# 3. Check "Query performance" — any unusual slowness?

# Via psql (if available):
psql $DATABASE_URL -c "SELECT 1;"
# If connection successful, database is up
# If "connection refused" → network or Supabase issue
# If timeout → connection pool exhausted or slow queries
```

### Level 3: Service Dependencies (2 minutes)

```bash
# Sentry status (error tracking)
curl -I https://sentry.io/health
# Should return 200

# Redis status (if using Celery workers)
redis-cli -u $REDIS_URL ping
# Expected: PONG
# If error → Redis is down or credentials wrong

# GitHub Actions (CI/CD)
https://github.com/metalbod/EMS/actions
# Are recent deployments failing? Check last 5 runs
```

### Summary: If Everything Looks OK

```
✅ Health endpoint returning 200
✅ Fly.io status all green
✅ Logs show no errors
✅ Database is responding

→ The alert might be false positive or transient issue
→ Monitor for 15 minutes to see if it repeats
→ If stable, mark incident as "resolved"
```

---

## Common Incidents

### Incident #1: Application is Down (500 Errors)

**Symptoms**: 
- `/health` returns 503 or connection refused
- Customer reports "website not loading"
- Fly.io shows crash/restart loops

**Diagnosis** (5 minutes):

```bash
# Get most recent logs
flyctl logs --tail 50

# Look for specific errors:

# A) "listen EADDRINUSE" → port is already in use
#    Usually from failed graceful shutdown

# B) "deadlock detected" → database lock conflict
#    This is transient; usually resolves itself

# C) "connection refused" → DATABASE_URL is wrong or DB is down
#    Check environment variables: flyctl secrets list

# D) "ModuleNotFoundError" → dependency missing
#    Check requirements.txt and deployment

# E) "SyntaxError" → code deploy issue
#    Check recent git commits

# F) No logs at all → app didn't start
#    Check app generation: flyctl logs --source app
```

**Quick Fixes**:

```bash
# Try 1: Redeploy (often fixes transient issues)
git push origin main
# Fly.io will auto-deploy

# Monitor: flyctl logs --tail
# Check: curl https://yourdomain.com/health

# Try 2: If push didn't trigger deploy, manual deploy:
flyctl deploy

# Try 3: If redeploy didn't work, check env variables:
flyctl secrets list
# Compare with .env.example — are required ones set?

# Try 4: Scale down and up (nuclear option, causes brief downtime)
flyctl scale count=0
sleep 5
flyctl scale count=1
flyctl logs --tail
```

**Escalation** (if not resolved in 10 min):

```
→ Check Supabase status page: https://status.supabase.com
→ If Supabase has incident, wait for their recovery
→ If no status page issue, contact Supabase support
→ Notify customers of incident (if known issue)
```

---

### Incident #2: High Error Rate in Sentry

**Symptoms**:
- Sentry alert: "50+ errors in last 5 minutes"
- Specific error type (e.g., "DeadlockDetected", "ValidationError")
- Customers report failures on specific features

**Diagnosis** (5 minutes):

```bash
# 1. Go to Sentry.io → Issues
# 2. Look at top error by frequency
# 3. Click through to see examples
# 4. Look for pattern:
#    - Is it one endpoint? (e.g., POST /api/payroll/runs)
#    - Is it one user or all users?
#    - Did it start just now or gradually?

# In Sentry, check:
# - Stack trace (where in code?)
# - Context (which user, which institution?)
# - Breadcrumbs (what happened leading up to error?)
```

**Common Errors & Fixes**:

#### DeadlockDetected
```
Status: Known issue, temporary
Cause: Concurrent requests to same table/rows
Mitigation: Retry logic built in (conftest.py has 3 retries)
Fix: No immediate action, auto-resolves
Monitor: If persists > 1 hour, escalate
```

#### ValidationError
```
Cause: Client sent invalid input
Example: posting {"period_end": "invalid-date"} to payroll endpoint
Fix: Client issue, not server issue
Action: Notify customer to send correct format
Escalation: Only if error is in internal code (bug)
```

#### ConnectionError
```
Status: Likely database issue
Cause: Connection pool exhausted or DB unresponsive
Check: psql $DATABASE_URL -c "SELECT 1;"
Fix: If DB is OK, connection pool issue
  → Redeploy to get fresh pool: flyctl deploy
```

#### ValueError / TypeError
```
Status: Application bug
Cause: Code tried to process unexpected data type
Example: int("abc") → ValueError
Fix: Requires code change, submit PR
Escalation: Notify team lead, create bug ticket
Temporary: If blocking critical feature, rollback last deploy:
  flyctl releases list
  flyctl releases rollback <PREVIOUS_VERSION>
```

**Quick Fix Pattern**:

```bash
# Step 1: Identify the problematic endpoint/feature
# (via Sentry issue details)

# Step 2: If error is transient (deadlock, connection):
flyctl deploy  # Fresh deployment often resolves

# Step 3: If error is code-level (bug):
# Option A (ideal): Fix code and git push origin main
# Option B (emergency): Rollback previous deploy:
flyctl releases list
flyctl releases rollback <VERSION_SHA>

# Step 4: Monitor Sentry for 10 minutes
# Should see error count return to baseline
```

---

### Incident #3: Slow Response Times

**Symptoms**:
- Customer reports "website is slow"
- Fly.io metrics show high response time (e.g., 10+ seconds)
- Timeouts on specific endpoints

**Diagnosis** (5 minutes):

```bash
# 1. Check Fly.io Metrics dashboard
# https://fly.io/dashboard → YOUR_APP → Metrics
# Look for: Response time over last 24 hours

# 2. Check database query performance
# Supabase → Settings → Database → Query Performance
# Which queries are slow?

# 3. Check application logs for slow operations
flyctl logs | grep "slow\|duration"

# 4. Check CPU/Memory usage
# Fly.io Metrics → CPU, Memory graphs
# If CPU is at 100%, app is bottlenecked
```

**Common Causes & Fixes**:

#### Slow Database Queries

```
Symptom: POST /api/payroll/runs takes 30+ seconds
Cause: Full-table scan (missing index)
Check: Run query directly:
  SELECT COUNT(*) FROM payslips WHERE institution_id = 123;
  -- EXPLAIN ANALYZE to see query plan
Fix: Add missing index (migration)
Temporary: Increase Fly.io timeout in fly.toml
```

#### Connection Pool Exhausted

```
Symptom: Random timeouts, increasing errors
Cause: Too many concurrent requests, pool limit hit
Check: Sentry → Look for "connection pool" errors
Fix: Increase pool size OR reduce concurrent requests
Temporary: Scale up instances (flyctl scale count=2)
```

#### Memory Leak / Unbounded Load

```
Symptom: Memory usage steadily increases over hours
Cause: Unreleased connections, cached objects growing
Check: Fly.io Metrics → Memory graph (saw spike?)
Fix: Redeploy to reset memory (flyctl deploy)
Long-term: Add connection pooling, memory profiling
```

---

### Incident #4: Database Corruption or Data Loss

**Symptoms**:
- Customer reports missing data
- Audit logs show data that shouldn't exist
- Constraints being violated

**Diagnosis & Response** (CRITICAL — 10 minutes):

```bash
# 1. FIRST: Preserve evidence
# Screenshot the broken state
# Query the problem data:
psql $DATABASE_URL -c "SELECT * FROM employees WHERE id = 123;"

# 2. Check backup status (Do we have a restore point?)
# Supabase → Settings → Backups
# Look for green checkmark on recent backup

# 3. Assess blast radius
# How much data is affected?
SELECT COUNT(*) FROM employees WHERE status = 'CORRUPT';
# Is it one record or entire table?

# 4. If issue is accidental delete/bad migration:
# FOLLOW: docs/BACKUP_POLICY.md → Restore Procedure
```

**Recovery**:

```
CRITICAL: Do not attempt to manually fix corrupted data
→ This risks making it worse
→ Use backup restore (proven safe)

Steps:
1. Take screenshot of current broken state
2. Take app offline: flyctl scale count=0
3. Restore from Supabase backup (see BACKUP_POLICY.md)
4. Verify data integrity
5. Bring app back online: flyctl scale count=1
6. Post-incident: investigate root cause
```

---

## Escalation & Communication

### When to Escalate

**Escalate to Kenneth Yong** if:

```
🔴 CRITICAL issues:
  - App is completely down (status code 503)
  - Database is unreachable
  - Data has been corrupted/deleted
  - Security incident (suspected breach)
  - Can't resolve within 30 minutes

🟠 HIGH issues:
  - Major feature broken (e.g., payroll processing unavailable)
  - High error rate (>5% of requests failing)
  - Performance degradation (>10 second response times)
  - Can't resolve within 60 minutes

Otherwise: Keep monitoring, try fixes listed above
```

### Communication Template

**To Customers** (if service is impaired):

```
Subject: [Incident] EMS Service Degradation - Updates

We are aware of [brief description of issue]. Our team is 
investigating and we expect to have an update in [time].

In the meantime: [workaround if available, or "please standby"]

We apologize for the inconvenience and appreciate your patience.

— The EMS Team
```

**To Kenneth** (when escalating):

```
🔴 INCIDENT REPORT

Issue: [One sentence summary]
Severity: [CRITICAL / HIGH / MEDIUM]
Impact: [How many users/features affected?]
Symptoms: [What did customer see/report?]
Diagnosis: [What I've checked so far]
Actions Taken: [What I tried, results]
Needs: [What I need help with]

Sentry link: [if applicable]
Affected endpoint: [if applicable]
First seen: [timestamp]
```

---

## Post-Incident Review

### After Any Incident (Even Minor Ones)

Create an incident report (within 24 hours):

**Template**:

```markdown
# Incident Report: [Title]

**Date**: 2026-07-17  
**Duration**: 14:30 - 14:45 UTC (15 minutes)  
**Severity**: 🔴 CRITICAL / 🟠 HIGH / 🟡 MEDIUM / 🔵 LOW  
**Impact**: [How many users affected? Which features?]  

## Timeline

| Time | Event |
|------|-------|
| 14:30 | Sentry alert: High error rate |
| 14:31 | Checked /health → 503 |
| 14:32 | Reviewed logs → DeadlockDetected |
| 14:35 | Triggered redeploy |
| 14:45 | Service recovered, errors dropped to baseline |

## Root Cause

[What actually caused this? Was it:]
- A recent code change?
- Infrastructure issue (Fly.io, Supabase)?
- External dependency (Redis, third-party API)?
- Environmental (too much traffic, concurrent load)?

## What Went Well

- ✅ Alert triggered quickly
- ✅ Logs were informative
- ✅ Redeploy fixed it (proves not a persistent bug)

## What Could Be Better

- 🔧 Deadlock retry logic could be more aggressive
- 🔧 Need better visibility into database lock waits
- 🔧 Customer notification was manual (automate?)

## Action Items

- [ ] (Optional) If code bug: create GitHub issue + PR
- [ ] (Optional) If infrastructure: file support ticket
- [ ] Update monitoring if needed
- [ ] Share learnings with team

## Follow-Up

- Check Sentry for 24h post-incident
- Look for related errors in following week
- Share findings in team meeting
```

### Sample Post-Incident Actions

**If it was a code bug**:
```
→ Create GitHub issue with reproduction steps
→ File PR with fix
→ Add test case to prevent regression
→ Tag issue with "incident" label
```

**If it was transient (deadlock, fluke)**:
```
→ No code change needed
→ Document in incident report
→ Increase monitoring on that endpoint
→ Discuss with team if pattern emerges
```

**If it was infrastructure**:
```
→ File support ticket with Fly.io or Supabase
→ Add to tech-debt if systemic (e.g., need better pooling)
→ Consider redundancy or failover for next architecture review
```

---

## Incident Severity Levels

### 🔴 CRITICAL (Page immediately, start incident)

```
Customer-facing service is entirely down:
- API returns 503 or connection refused
- All users affected
- Data integrity at risk
- Security incident

Response time: < 5 minutes
On-call: Answer page immediately
Escalation: Automatic, wake up primary
```

### 🟠 HIGH (Wake up lead, start incident)

```
Major feature is broken:
- Specific endpoint failing (e.g., /api/payroll/runs)
- Significant subset of users affected (>20%)
- High error rate (>5%)
- Performance severe (>20 seconds)

Response time: < 30 minutes
On-call: Investigate and attempt fixes
Escalation: If not resolved in 30 min, escalate
```

### 🟡 MEDIUM (Create ticket, non-urgent)

```
Feature partially degraded:
- Specific error type (<5% of requests)
- Single user/customer affected
- Non-critical feature unavailable
- Performance degraded but within tolerance

Response time: < 8 hours (next business day OK)
On-call: Create ticket, investigate during work hours
Escalation: No escalation needed
```

### 🔵 LOW (Information only)

```
Single error, non-user-facing:
- Internal error logs
- Single user reports (might be client-side)
- Non-critical background job failed

Response time: No hurry
Action: Log it, investigate when convenient
```

---

## Useful Commands Cheat Sheet

```bash
# Fly.io
flyctl auth login
flyctl status
flyctl logs --tail 50
flyctl logs --source app --tail 30
flyctl logs --source postgres --tail 20
flyctl scale count=2          # Scale up
flyctl scale count=0          # Scale down
flyctl deploy                 # Manual deploy
flyctl secrets list           # Show all secrets
flyctl releases list          # Show deployment history
flyctl releases rollback <VERSION>  # Rollback

# Database
psql $DATABASE_URL -c "SELECT 1;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM users;"

# Health checks
curl https://yourdomain.com/health
curl -v https://yourdomain.com/health  # Verbose

# Git
git log --oneline -10
git diff HEAD~1
git show <COMMIT_HASH>

# Tests (if you need to verify fix)
pytest tests/test_auth.py -v
pytest tests/ -k "test_login" -v
```

---

## Contact & Escalation Chain

| Role | Name | Contact |
|------|------|---------|
| **Primary On-Call** | Kenneth Yong | kenneth@users-MacBook-Pro.local |
| **Secondary** | (To be assigned) | _____ |
| **Manager** | (To be assigned) | _____ |

### Escalation Path

```
1. Try fixes in runbook (5 min)
   ↓
2. If not resolved, contact on-call primary (Kenneth)
   ↓
3. If Kenneth unresponsive, try secondary
   ↓
4. If still unresolved, notify manager
   ↓
5. For security incidents, also notify info-sec team
```

### External Contacts

- **Supabase Support**: support@supabase.io (dashboard or email)
- **Fly.io Support**: https://fly.io/docs/getting-started/support/
- **GitHub Support**: https://support.github.com

---

## Monthly Check-In

Every first Monday of the month:

- [ ] Review last month's incidents (if any)
- [ ] Verify backups are running (docs/BACKUP_POLICY.md)
- [ ] Check secret rotation schedule (docs/SECRETS_ROTATION_POLICY.md)
- [ ] Update this runbook if needed
- [ ] Test database restore procedure (monthly)

---

## Related Documentation

- [BACKUP_POLICY.md](BACKUP_POLICY.md) — Database backup & recovery
- [SECRETS_ROTATION_POLICY.md](SECRETS_ROTATION_POLICY.md) — Key management
- [README.md](../README.md) — General project info
- [tech_debt_report.md](../tech_debt_report.md) — Known issues to work on

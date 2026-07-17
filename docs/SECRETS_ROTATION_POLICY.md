# Secrets Rotation & Key Management Policy

## Overview

Secrets (JWT_SECRET, DATABASE_URL credentials, API keys) must be rotated periodically to mitigate exposure risk from leaks, employee turnover, or compromised devices.

**Policy**: Quarterly rotation (every 3 months)

---

## Secrets Inventory

| Secret | Location | Type | Rotation Freq | Critical? |
|--------|----------|------|---------------|-----------|
| `JWT_SECRET` | Fly.io env vars | Symmetric key | Quarterly | 🔴 YES |
| `DATABASE_URL` | Fly.io env vars | Connection string (app user) | Quarterly | 🔴 YES |
| `ADMIN_DATABASE_URL` | Fly.io env vars | Connection string (admin user) | Quarterly | 🔴 YES |
| `SENTRY_DSN` | Fly.io env vars | API token | Annually | 🟡 Medium |
| `REDIS_URL` | Fly.io env vars | Connection string | Quarterly | 🟡 Medium |
| GitHub Deploy Key | GitHub repo settings | SSH key | Annually | 🟠 High |

---

## Rotation Schedule

### 2026 Rotation Calendar

| Quarter | Start Date | Secret(s) | Owner | Status |
|---------|-----------|----------|-------|--------|
| Q2 (Apr-Jun) | 2026-04-01 | JWT_SECRET, DATABASE_URL*, ADMIN_DATABASE_URL* | Kenneth | Pending |
| Q3 (Jul-Sep) | 2026-07-01 | JWT_SECRET, DATABASE_URL*, ADMIN_DATABASE_URL* | Kenneth | **NOW** 🔴 |
| Q4 (Oct-Dec) | 2026-10-01 | JWT_SECRET, DATABASE_URL*, ADMIN_DATABASE_URL* | Kenneth | Pending |

*Database credentials managed by Supabase; coordinate with their rotation policy.

---

## JWT_SECRET Rotation Procedure

**Time required**: 30-45 minutes  
**Downtime**: None (rolling update)  
**Risk level**: Medium (brief period where old/new keys coexist)

### Prerequisites

- [ ] Admin access to Fly.io dashboard
- [ ] Read access to current `.env` (to copy existing secrets)
- [ ] SSH access to production if needed for verification

### Step 1: Generate New JWT_SECRET

```bash
# Generate a cryptographically random 256-bit hex string
openssl rand -hex 32
# Example output: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0

# Copy the output (new JWT_SECRET)
```

### Step 2: Update Fly.io Secrets

```bash
# Verify current secret (for rollback if needed)
flyctl secrets list | grep JWT_SECRET

# Set new JWT_SECRET
flyctl secrets set JWT_SECRET="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"

# Verify it was set
flyctl secrets list | grep JWT_SECRET
```

### Step 3: Monitor Deployment

```bash
# Fly.io automatically triggers a rolling restart
# This means old instances shut down and new ones start with the new key
# Clients with valid tokens using the old key will still work during transition

# Watch the deployment
flyctl status

# Monitor logs for errors
flyctl logs
# Look for any "invalid token" or "authentication failed" patterns
```

### Step 4: Verification

Test the application works with the new secret:

```bash
# Test login (new token should be issued with new secret)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "superadmin",
    "password": "Admin@123",
    "institution_code": null
  }'

# Grab the access_token from response

# Test authenticated endpoint with new token
curl -H "Authorization: Bearer <ACCESS_TOKEN>" \
  http://localhost:8000/api/users

# Should return 200 (not 401)
```

### Step 5: Document Rotation

```bash
# Create entry in SECRETS_ROTATION_LOG.md
# 2026-07-17: JWT_SECRET rotated
# - Old secret: (first 8 chars) a1b2c3d4...
# - New secret: (first 8 chars) f0e9d8c7...
# - Fly.io deployment: ✅ Succeeded
# - Tests: ✅ Passed
# - Incidents: None
```

### Rollback if Needed

If authentication errors occur:

```bash
# Revert to old secret immediately
flyctl secrets set JWT_SECRET="<OLD_SECRET_HERE>"

# This triggers another rolling restart
flyctl logs  # Monitor for recovery
```

---

## Database Credential Rotation

### Via Supabase Dashboard

**Time required**: 15-20 minutes  
**Downtime**: None (Supabase handles seamless rotation)

#### Step 1: Reset App User Password (DATABASE_URL)

```
Supabase Dashboard → Settings → Database → Users
→ ems_app user → Edit
→ Reset password
→ Copy new password
```

#### Step 2: Update Fly.io Environment Variable

```bash
# New connection string format:
# postgresql://ems_app.YOUR_PROJECT_REF:NEW_PASSWORD@YOUR_POOLER_HOST:6543/postgres

flyctl secrets set DATABASE_URL="postgresql://ems_app.YOUR_PROJECT_REF:new_password_here@..."

# Verify
flyctl secrets list | grep DATABASE_URL
```

#### Step 3: Monitor for Issues

```bash
# Fly.io rolling restart
flyctl status
flyctl logs

# Should see successful database connections
# No "invalid password" or "access denied" errors
```

#### Step 4: Repeat for ADMIN_DATABASE_URL

```
Supabase Dashboard → postgres user (superuser)
→ Edit → Reset password
→ Copy new password
→ Update Fly.io: flyctl secrets set ADMIN_DATABASE_URL="..."
```

---

## Redis Connection Rotation

If using managed Redis (e.g., Redis Cloud, Upstash):

```bash
# 1. Rotate password in Redis provider dashboard
# 2. Get new connection string
# 3. Update Fly.io:
flyctl secrets set REDIS_URL="redis://new_connection_string_here"

# 4. Monitor Celery worker logs for connection errors
flyctl logs --app ems-worker  # if separate app
# or check main app logs if Celery runs there
```

---

## Automated Rotation via GitHub Actions (Future)

When secrets become truly sensitive, automate via GitHub Actions:

```yaml
# .github/workflows/rotate-secrets.yml
name: Quarterly Secret Rotation

on:
  schedule:
    # Run at 2 AM UTC on the 1st of Apr, Jul, Oct, Jan
    - cron: '0 2 1 4,7,10,1 *'

jobs:
  rotate-jwt:
    runs-on: ubuntu-latest
    steps:
      - name: Generate new JWT_SECRET
        run: openssl rand -hex 32 > jwt_secret.txt
      
      - name: Update Fly.io
        run: |
          NEW_SECRET=$(cat jwt_secret.txt)
          flyctl secrets set JWT_SECRET="$NEW_SECRET"
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
      
      - name: Send notification
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK }} \
            -d '{"text":"✅ JWT_SECRET rotated successfully"}'
```

**Status**: TODO (add in Q3 2026)

---

## Employee Offboarding Checklist

When an employee leaves (especially with production access):

- [ ] Revoke Fly.io dashboard access
- [ ] Revoke GitHub repository access
- [ ] Revoke Supabase dashboard access
- [ ] Rotate JWT_SECRET (they may have it from config files)
- [ ] Rotate DATABASE_URL (if they had admin access)
- [ ] Rotate REDIS_URL (if they had worker access)
- [ ] Revoke SSH keys
- [ ] Review git history for accidentally committed secrets

---

## Incident Response: Suspected Secret Compromise

**If you suspect a secret is compromised** (e.g., committed to git, leaked in logs):

### Immediate Actions (First 5 Minutes)

1. **Don't panic** — most secrets can be rotated without downtime
2. **Identify which secret** — JWT_SECRET? DATABASE_URL? Which layer?
3. **Check if it's actually in public** — GitHub search, StackOverflow, etc.

### Short Term (15-30 Minutes)

```bash
# Immediately rotate the suspected secret
flyctl secrets set JWT_SECRET="$(openssl rand -hex 32)"

# Or DATABASE_URL if database credentials are compromised
# (Requires Supabase password reset + Fly.io update)

# This triggers immediate rolling restart
flyctl status
flyctl logs
```

### Investigation (Next 24 Hours)

```bash
# Search git history for the exposed secret
git log -S "YOUR_SECRET_HERE" --all

# If found, create a new commit that removes it
# (git-filter-repo or BFG can permanently remove from history)

# Check if secret was in:
# - Docker image layers (redeploy after rotation)
# - Slack messages (request deletion)
# - Email logs (likely cannot remove)
# - GitHub Actions logs (disable visibility in repo settings)

# Notify stakeholders if production data was accessed
```

### Root Cause Analysis

- Was it committed to git?
- Was it logged?
- Was it in environment variables?
- How long was it exposed?
- Which systems had access?

### Prevention Going Forward

- Use `.env.local` and add to `.gitignore` (already done ✅)
- Use GitHub Secrets for Actions (not in code)
- Enable Fly.io Secrets Manager best practices
- Use secret rotation as "routine maintenance" not "emergency response"

---

## Rotation Test Template

After each rotation, document:

```markdown
## Rotation: 2026-07-17 - JWT_SECRET

**Executor**: Kenneth  
**Start time**: 14:30 UTC  
**End time**: 14:45 UTC  

**Before**:
- Secrets list: ✅ Verified
- Current JWT_SECRET (first 8 chars): a1b2c3d4

**During**:
- New secret generated: ✅ openssl rand -hex 32
- Fly.io update: ✅ flyctl secrets set
- Rolling restart: ✅ 2 instances restarted
- Deployment status: ✅ Green

**After**:
- Health check: ✅ GET /health → 200
- Login test: ✅ Token issued and verified
- API tests: ✅ Authenticated requests pass
- Logs: ✅ No auth errors
- Sentry: ✅ No new errors

**Incidents**: None  
**Notes**: Smooth rotation, no issues
```

---

## Monitoring & Alerts

### What to Monitor

```bash
# After secret rotation, watch these logs for 24 hours:

# Authentication failures
flyctl logs | grep -i "invalid\|authentication\|unauthorized"

# Connection failures (if rotating DATABASE_URL)
flyctl logs | grep -i "connection\|refused\|timeout"

# Any sudden spike in 401/403 errors
flyctl logs | grep -E "401|403"
```

### Sentry Monitoring

If using Sentry, check for:
- Spike in authentication errors
- Spike in database connection errors
- New errors after rotation

---

## Policy Review Schedule

This policy should be reviewed:

- **Annually** (January) — for procedure updates, role changes
- **After an incident** — if secrets are compromised, update this doc
- **When new team members join** — ensure they know the procedure

---

## Quick Reference Card

Print this and keep at your desk:

```
╔════════════════════════════════════════════════════════════╗
║         EMS Secrets Rotation Quick Reference               ║
╠════════════════════════════════════════════════════════════╣
║ QUARTERLY ROTATION (1st of: Jan, Apr, Jul, Oct)            ║
║                                                            ║
║ 1. Generate new secret: openssl rand -hex 32               ║
║ 2. Update Fly.io:      flyctl secrets set SECRET="..."     ║
║ 3. Monitor:            flyctl logs                         ║
║ 4. Verify:             curl -H "Authorization: Bearer..." ║
║ 5. Document:           Add entry to ROTATION_LOG.md        ║
║                                                            ║
║ EMERGENCY ROTATION (suspected compromise):                 ║
║ Do steps 1-4 immediately, investigate later                ║
║                                                            ║
║ Need help? See: docs/SECRETS_ROTATION_POLICY.md            ║
╚════════════════════════════════════════════════════════════╝
```

---

## Related Documentation

- [BACKUP_POLICY.md](BACKUP_POLICY.md) — Disaster recovery procedures
- [ONCALL_RUNBOOK.md](ONCALL_RUNBOOK.md) — Incident response procedures
- [README.md](../README.md) — General project setup

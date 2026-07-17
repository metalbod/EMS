# Monitoring & Alerting Setup Guide

**Status**: Setup guide for Sentry + Fly.io metrics  
**Last Updated**: 2026-07-17  
**Effort**: 1-2 hours  
**Priority**: 🔴 HIGH

This guide walks through wiring up production monitoring and alerts.

---

## Part 1: Sentry Alert Configuration

### Current Status

✅ Sentry SDK is installed and configured in `main.py`  
❌ Alerts are NOT configured (no email notifications)

### Setup: Enable Email Alerts

1. **Log in to Sentry**: https://sentry.io/auth/login/
2. **Navigate to Project Settings**:
   - Select your EMS project
   - Settings (left sidebar) → Alerts
3. **Create New Alert Rule**:
   - Click "Create Alert Rule"
   - **Alert Name**: "High Error Rate (EMS)"
   - **Conditions**:
     ```
     IF    an event is seen
     THEN  for each issue
     WHEN  Event count rises above 10 in the last 1 hour
     ```
   - **Actions**:
     - Add Action → "Send Email"
     - Email to: kenneth@users-MacBook-Pro.local
   - **Save**

4. **Create Second Rule for New Issues**:
   - **Alert Name**: "New Issue Alert (EMS)"
   - **Conditions**:
     ```
     IF    a new issue is created
     WHEN  Resolved issue is seen again
     ```
   - **Actions**:
     - Add Action → "Send Email"
     - Email to: kenneth@users-MacBook-Pro.local
   - **Save**

### Verify Alerts Work

```bash
# Trigger a test error:
curl https://yourdomain.com/api/test-error

# You should receive email alert within 1-2 minutes
# Check Sentry Issues page for the error
```

### Sentry Alert Destinations

Later you can add more channels:

- ✅ Email (configured above)
- 🟢 Slack (medium effort) — DM notifications
- 🟢 PagerDuty (hard) — Incident management
- 🟢 Discord (medium effort) — If using Discord

---

## Part 2: Fly.io Metrics Dashboard

### Current Status

✅ Fly.io tracks metrics automatically  
❌ No custom dashboard or alerts configured

### Setup: Create Custom Dashboard

1. **Log in to Fly.io**: https://fly.io/
2. **Go to App**: Dashboard → YOUR_APP (ems)
3. **Click "Metrics" tab**
4. **View available metrics**:
   - Response time (histogram)
   - Request rate (requests/sec)
   - Error rate (5xx status codes)
   - CPU usage (%)
   - Memory usage (MB)

### Add Metrics to Monitoring

**Response Time Alert** (optional):

```
Coming soon — Fly.io doesn't have built-in alerts on free tier.
When/if upgraded to paid tier, enable:
- Alert if response time > 5 seconds for 5 min
- Alert if error rate > 5% for 5 min
```

### Create Grafana Dashboard (Advanced)

Fly.io metrics can be exported to Grafana for richer dashboards:

```
Coming soon — requires Grafana account + configuration
For now, manually check Fly.io Metrics tab during incidents
```

---

## Part 3: Custom Health Checks

### Current Status

✅ Basic health endpoint exists: `GET /health`  
❌ No distributed health checks (uptime monitoring)

### Setup: Uptime Monitoring Service

Add a free uptime monitor (e.g., UptimeRobot):

1. **Sign up**: https://uptimerobot.com (free tier)
2. **Create Monitor**:
   - URL: https://yourdomain.com/health
   - Check interval: 5 minutes
   - Alert method: Email to kenneth@users-MacBook-Pro.local
3. **Verify**:
   - Should see "All monitors up" on dashboard
   - Wait 5 minutes, should see check requests in Fly.io logs

---

## Part 4: Sentry Cron Monitoring (Optional)

If you have background jobs, track them in Sentry:

```python
# Example: Monitor a scheduled job
import sentry_sdk

@app.get("/api/scheduled-job")
def scheduled_job():
    # This creates a Cron Monitor in Sentry
    with sentry_sdk.get_client().cron.monitor(
        monitor_slug='payroll-generation',
        monitor_config=crons.MonitorConfig(
            schedule=crons.CrontabSchedule(hour=2, minute=0),  # Daily 2 AM
            checkin_margin=1,  # Minutes grace period
            max_runtime=30,    # Expected job duration
            timezone='UTC',
        ),
    ):
        # Your job logic here
        generate_payroll_run()

# Sentry will alert if job doesn't check in on time
```

**Status**: Not implemented yet (background jobs not set up)

---

## Part 5: Log Aggregation (Future)

When you scale beyond single instance:

```
Coming soon:
- Collect logs from all instances
- Centralized search (e.g., ELK stack, Datadog)
- Alerts based on log patterns
- Performance correlations

For now: flyctl logs --tail 50 is sufficient
```

---

## Monitoring Checklist

After setup, verify:

- [ ] Sentry alerts are working (send test error)
- [ ] Email alerts are delivered (check inbox)
- [ ] Uptime monitor is configured
- [ ] Fly.io Metrics page loads
- [ ] Database backups are enabled (see BACKUP_POLICY.md)
- [ ] Oncall runbook is accessible (print a copy)

---

## Daily Monitoring Tasks

### Start of Day

```bash
# 1. Check Sentry Issues
# https://sentry.io → Issues
# Any new errors overnight? (Should be none or very few)

# 2. Check Fly.io Metrics
# https://fly.io/dashboard → YOUR_APP → Metrics
# Any spikes in response time or error rate?

# 3. Quick health check
curl https://yourdomain.com/health
# Expected: {"status": "ok"}
```

### Weekly Review

```bash
# 1. Check Sentry trend
# Issues → Trends (last 7 days)
# Is error rate increasing or stable?

# 2. Review Fly.io deployments
# https://fly.io → Deployments
# Any failed deploys? Any rollbacks?

# 3. Database backups (first Monday of month)
# See BACKUP_POLICY.md → Testing Schedule
```

---

## Alert Response Examples

### Alert: "High Error Rate (EMS)"

```
Email from Sentry:
Subject: High Error Rate in EMS — 42 events in the last 1h

Response:
1. Check Sentry link in email
2. Identify error type (see ONCALL_RUNBOOK.md → Common Incidents)
3. Take action (redeploy, rollback, etc.)
4. Monitor for 15 minutes
5. Create incident report if it took > 30 minutes to resolve
```

### Alert: "Uptime Monitor Failed"

```
Email from UptimeRobot:
Subject: Down — yourdomain.com/health is down

Response:
1. Check Fly.io logs immediately: flyctl logs --tail 20
2. Check health endpoint: curl https://yourdomain.com/health
3. If down, follow ONCALL_RUNBOOK.md → Incident #1
4. If false positive (recovers in 1 min), no action needed
5. Monitor for 10 minutes
```

---

## Cost Tracking

| Service | Cost | Status |
|---------|------|--------|
| Sentry (100k events/month) | Free | ✅ Configured |
| Fly.io (free tier) | Free | ✅ Running |
| UptimeRobot (3 monitors) | Free | 🟡 To configure |
| Supabase (PostgreSQL) | Free tier | ✅ Running |
| **Total** | **Free** | ✅ No cost |

---

## Escalation & Troubleshooting

### Sentry Alert Isn't Working

```
1. Check email isn't in spam folder
2. Verify alert rule is enabled (Settings → Alerts)
3. Test by triggering an error: curl /test-error
4. Check email delivery logs (Sentry Settings → Email)
5. Try alternative: Slack integration (Settings → Integrations)
```

### Fly.io Metrics Not Showing

```
1. Refresh dashboard (hard refresh: Ctrl+Shift+R)
2. Wait 5 minutes for metrics to populate
3. Make a request to app: curl https://yourdomain.com/
4. Check logs: flyctl logs
5. Metrics should appear within 1-2 minutes
```

### Uptime Monitor False Positives

```
1. Check if app is actually up: curl https://yourdomain.com/health
2. If app is up but monitor says down, it's network issue
3. Disable monitor temporarily
4. Wait 5 minutes, re-enable
5. If persists, switch to different uptime service
```

---

## Next Steps (Optional Enhancements)

Once basic monitoring is working:

1. **Slack Integration** (2 hours)
   - Sentry → Slack notifications
   - Real-time incident alerts

2. **Custom Dashboards** (4 hours)
   - Grafana for deeper metrics
   - Correlate errors with resource usage

3. **Incident Management** (8 hours)
   - PagerDuty integration
   - On-call scheduling
   - Escalation policies

4. **Data Retention** (2 hours)
   - Sentry → increase event retention
   - Fly.io → log retention policy

---

## Related Documentation

- [ONCALL_RUNBOOK.md](ONCALL_RUNBOOK.md) — Incident response
- [BACKUP_POLICY.md](BACKUP_POLICY.md) — Database monitoring
- [README.md](../README.md) — General setup

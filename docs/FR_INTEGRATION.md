# FR integration — EMS-side implementation

Implements the contract requested in `FR/docs/ems-api.md`. This document is
the EMS-side reference: what actually exists, how it differs from the
original ask, and what's still open.

## Auth

Reuses the existing `attendance_devices` API-key scheme (built for exactly
this — "facial-recognition office cameras", see
`migrations/versions/20260725_0018_add_attendance_devices.py`), not OAuth2.
An FR kiosk is provisioned exactly like a clock-in camera device:

1. HR generates a key via Settings → Attendance → Devices (`POST
   /api/attendance/devices`, HR-role JWT-authed). The full key
   (`adk_<prefix>_<secret>`) is shown once and never retrievable again.
2. FR sends it on every call as `X-Device-Api-Key: <key>` — not
   `Authorization: Bearer`.
3. The key is bound to one institution; every response below is
   automatically scoped to that institution (Postgres RLS), no separate
   `institution_id` param needed anywhere.

`FR_EMS_BASE_URL` should point at `https://ems-app.fly.dev/api/integrations/fr`.

## 1. Roster pull

```
GET {base}/employees?changed_since={iso8601}&cursor={opaque}&page_size={n}
```

Response is a bare JSON array (matches the original contract's documented
shape exactly):

| field | type | source |
|---|---|---|
| `ems_employee_id` | string | `employees.employee_id` |
| `full_name` | string | `employees.full_name` |
| `display_name` | string | `employees.preferred_name` or `full_name` if unset |
| `department` | string \| null | `employees.department` |
| `email` | string \| null | `employees.work_email` or `personal_email` if unset |
| `start_date` | `YYYY-MM-DD` | `employees.start_date` |
| `date_of_birth` | `YYYY-MM-DD` \| null | `employees.date_of_birth` |
| `status` | `"active"` \| `"inactive"` | lowercased from `Active`/`Inactive` |
| `consent_recognition` | bool | new column, **default false** |
| `consent_display_name` | bool | new column, **default false** |
| `consent_dob` | bool | new column, **default false** |

**Consent defaults to false for every employee, existing and new.** FR
will see `consent_recognition: false` for the entire roster until HR
opts each employee in individually via the Employee detail page's new
"FR Consent" tab (Settings-tier role: superadmin/hr_manager only). This
was a deliberate choice, not an oversight — treat it as the expected
initial state, not a bug to report.

**`changed_since`** filters on `employees.updated_at` (inclusive, `>=`),
which is already trigger-maintained on every column change — no new
column was needed for this.

**Pagination**: `cursor`/`page_size` are honored (keyset on `id`, not
offset). When a page is truncated, the id to pass as the next `cursor` is
returned in an **`X-Next-Cursor` response header**, not a JSON envelope —
the body stays a pure array either way. Omitting `page_size` returns the
full matching roster in one call, which the original contract says is
acceptable.

## 2. Push attendance

```
POST {base}/attendance
Content-Type: application/json

[ { "ems_employee_id": "EMP-002",
    "work_date": "2026-08-29",
    "clock_in_ts": "2026-08-29T01:03:11Z",
    "clock_out_ts": "2026-08-29T10:30:44Z" } ]
```

Max 500 rows/batch (matches the original ask). **Idempotent upsert keyed
on `(ems_employee_id, work_date)`** — re-sending the same row (a retry, or
a corrected day) always safely overwrites, never double-counts. This is a
genuinely different code path from EMS's older single live-event webhook
(`POST /api/attendance/webhook/clock-event`), which rejects a repeat
clock-in with a 400 — that endpoint is for a device reporting one punch as
it happens; this one is for FR reporting an already-finalized day, so it
sets both timestamps directly on every call instead.

**One exception to "always overwrites":** if HR has already reviewed and
reclassified that specific `(employee, work_date)` — Excused, Reclassified
as Leave, or Confirmed Absent — the row is rejected with reason
`day_already_finalized_by_hr` instead of being overwritten, so a
late-arriving or re-synced kiosk batch can never silently clobber an HR
decision.

**Response:**

```json
{ "ok": true, "accepted": 1, "rejected": [], "detail": null }
```

| field | notes |
|---|---|
| `ok` | always `true` for a completed response; a hard failure surfaces as a non-2xx status instead |
| `accepted` | count of rows upserted |
| `rejected` | `[{ ems_employee_id, work_date, reason }]` |
| `detail` | human-readable summary when `rejected` is non-empty, else `null` |

**Rejection reasons:** `unknown_employee`, `invalid_work_date`,
`invalid_clock_in_ts`, `invalid_clock_out_ts`, `clock_out_before_clock_in`,
`day_already_finalized_by_hr`, `db_error` (rare — a row FR should retry
next cycle rather than treat as permanently bad).

## Answers to the original "To agree" list

- **Auth**: API-key header (`X-Device-Api-Key`), not OAuth2 — see above.
- **Base URL**: `https://ems-app.fly.dev/api/integrations/fr` (prod).
  Staging URL: none exists yet — flag if FR needs a separate staging EMS.
- **`changed_since`**: inclusive, server clock, filters `updated_at >=`.
- **Pagination**: keyset cursor (opaque `id`), `X-Next-Cursor` response
  header, default page size = full roster (no limit) if `page_size` omitted,
  max 1000 if given.
- **Field names/formats**: exact casing/shape is the table above; dates
  `YYYY-MM-DD`, timestamps ISO 8601 UTC (`Z` or `+00:00` both accepted).
  `status` values are lowercase `active`/`inactive`.
- **Rejection reason vocabulary**: fixed list above.
- **Rate limits**: none — the push is expected from one known, keyed
  device on a schedule, not open traffic.
- **Error model**: standard FastAPI — `HTTPException` → `{"detail": "..."}`
  on 4xx (401 unauthenticated/bad key, 400 malformed batch), Pydantic 422
  on a malformed body. Nothing here is retryable except a genuine network
  failure or 5xx — a 4xx means the request itself needs fixing, not a
  resend.
- **Timezone**: confirmed UTC throughout, naive (no offset stored),
  matching how the rest of this app already stores every timestamp.

## Open / not built

- **`GET /health`** — already exists, unauthenticated, at the app root
  (`/health`, not under `/api/integrations/fr`) — checks DB connectivity.
  No new work needed.
- **`GET /employees/{ems_employee_id}`** (single fetch) — not built. Low
  cost to add if FR wants it for debugging; ask if needed.
- **Change webhook (EMS → FR)** — not built. Would need an outbound HTTP
  call from EMS on hire/consent-change, which nothing in this codebase
  does today (no existing outbound-webhook infrastructure) — real, if
  small, new work. Not started.
- **Enrolment-status readback (FR → EMS)** — not built, not requested by
  this pass. Flag before building — see the original doc's own caveat
  about confirming EMS wants it first.

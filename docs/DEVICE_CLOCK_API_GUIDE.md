# Device Clock-In/Out API — Integration Guide

This guide is for integrating external attendance hardware (facial-recognition
office cameras, fingerprint scanners, turnstiles, etc.) with EMS so that
clock-in/out events are reported automatically, without a user having to log
in through the web app.

The device authenticates with a long-lived **API key**, not a user login —
there is no username/password or JWT involved on the device side.

---

## 1. How it works

1. An HR Manager or HR Admin registers the device once in EMS (via the
   Attendance Settings page, or the `POST /api/attendance/devices` endpoint
   below) and is shown an API key **exactly once**.
2. The device stores that key and sends it on every request in the
   `X-Device-Api-Key` header.
3. Whenever the device recognizes an employee clocking in or out, it calls
   `POST /api/attendance/webhook/clock-event` with the employee's ID and
   the event type.
4. EMS trusts the device's own identity match (face/fingerprint/badge) —
   this API only records the punch. Liveness detection, anti-spoofing, and
   matching a face to an `employee_id` are entirely the device's
   responsibility.

```
┌─────────────────┐   X-Device-Api-Key   ┌──────────────────────────┐
│  Camera / Kiosk  │ ───────────────────► │ POST /api/attendance/    │
│  (recognizes     │                      │   webhook/clock-event    │
│   employee)      │ ◄─────────────────── │                          │
└─────────────────┘   200/201 + record    └──────────────────────────┘
```

---

## 2. One-time setup: register the device

**Who can do this:** `superadmin`, `hr_manager`, or `hr_admin`, authenticated
the normal way (JWT bearer token from `/api/auth/login`).

```
POST /api/attendance/devices
Authorization: Bearer <hr manager/admin JWT>
Content-Type: application/json

{
  "name": "Front Lobby Camera",
  "location_id": 4          // optional — ties clock events to a location for geofencing
}
```

**Response (201) — the API key is shown only this once:**

```json
{
  "id": 7,
  "name": "Front Lobby Camera",
  "location_id": 4,
  "location_name": "HQ — Level 1",
  "key_prefix": "9f2a7c1e0b3d",
  "is_active": true,
  "last_used_at": null,
  "created_at": "2026-07-27T05:00:00",
  "api_key": "adk_9f2a7c1e0b3d_kR8sT2...redacted..."
}
```

> **Important:** Copy `api_key` immediately and store it securely on the
> device (e.g. in the device's local config, not hardcoded in firmware you
> can't update). EMS stores only a bcrypt hash of the key — if it's lost,
> the only recovery is deleting the device and registering a new one.

Other device-management endpoints (also HR Manager/Admin only, JWT auth):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/attendance/devices` | List active devices for the current institution |
| `DELETE` | `/api/attendance/devices/{device_id}` | Deactivate a device (its API key stops working immediately) |

---

## 3. Sending a clock-in/out event

**Endpoint:**

```
POST /api/attendance/webhook/clock-event
X-Device-Api-Key: adk_9f2a7c1e0b3d_kR8sT2...
Content-Type: application/json
```

**Request body:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `employee_id` | string | yes | Must match an existing employee's `employee_id` in this institution |
| `event_type` | `"in"` \| `"out"` | yes | |
| `event_time` | string (ISO 8601, UTC) | no | Use this if the device buffers events and reports them late (e.g. was offline). Defaults to "now" if omitted. |
| `confidence` | number 0–1 | no | Optional facial-match confidence score, stored for audit only — not used for any decision |

**Example — clock in:**

```json
{
  "employee_id": "EMP0123",
  "event_type": "in",
  "confidence": 0.98
}
```

**Example — clock out, reporting a buffered/delayed timestamp:**

```json
{
  "employee_id": "EMP0123",
  "event_type": "out",
  "event_time": "2026-07-27T09:31:04Z"
}
```

**Response (201):**

```json
{
  "id": 5501,
  "employee_id": "EMP0123",
  "work_date": "2026-07-27",
  "shift_id": 3,
  "shift_name": "Morning Shift",
  "clock_in_at": "2026-07-27T01:00:12",
  "clock_out_at": null,
  "clock_in_distance_meters": 12,
  "outside_geofence": false,
  "clock_in_source": "device",
  "clock_out_source": null,
  "worked_minutes": null,
  "status": "Present",
  "suggested_action": null,
  "reviewed_by_user_id": null,
  "review_notes": null,
  "reviewed_at": null,
  "leave_application_id": null,
  "created_at": "2026-07-27T01:00:12"
}
```

If the device was registered with a `location_id` that has latitude/longitude
set, EMS automatically checks the punch against that location's geofence and
sets `outside_geofence`/`clock_in_distance_meters` — this is **advisory only**
and never blocks the clock-in/out from being recorded.

---

## 4. Error responses

| Status | Meaning | Typical cause |
|---|---|---|
| `401` | `X-Device-Api-Key header required` | Header missing entirely |
| `401` | `Malformed API key` | Key doesn't match the `adk_<prefix>_<secret>` format |
| `401` | `Invalid API key` | Key doesn't match any active device, or the device was deleted/deactivated |
| `404` | `Employee not found for this institution` | `employee_id` doesn't exist (or belongs to a different institution than the device) |
| `400` | `event_time must be a valid ISO 8601 timestamp` | Malformed `event_time` |
| `422` | Validation error | Missing/invalid `event_type`, `employee_id`, etc. — see FastAPI's standard validation error body |

A device should treat `401`/`404` as configuration errors worth alerting an
admin about (bad key, deactivated device, unknown employee ID) rather than
retrying indefinitely.

---

## 5. Security notes

- The API key is a **bearer credential** — anyone with it can post clock
  events for any employee in that institution. Treat it like a password:
  transmit over HTTPS only, don't log it, don't commit it to source control.
- Deactivating a device (`DELETE /api/attendance/devices/{id}`) invalidates
  its key immediately — use this instead of trying to "disable" a device by
  any other means.
- There's no key rotation endpoint — to rotate, register a new device,
  update the hardware's stored key, then deactivate the old device.
- Devices are scoped to a single institution; a key issued for one
  institution cannot report events for another.
- **Uniqueness:** the key's prefix (and therefore the key itself) is
  unique across the *entire* platform, not just within one institution —
  the database enforces a global unique constraint on it. Scope, however,
  is still per-institution: each key is permanently tied to the
  institution it was created for, so a valid key from Institution A is
  simply rejected (`404 Employee not found for this institution`) if
  pointed at an `employee_id` belonging to Institution B.

---

## 6. Quick reference (curl)

```bash
# One-time setup (as HR Manager/Admin)
curl -X POST https://<your-ems-host>/api/attendance/devices \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Front Lobby Camera", "location_id": 4}'

# Every clock event (as the device)
curl -X POST https://<your-ems-host>/api/attendance/webhook/clock-event \
  -H "X-Device-Api-Key: adk_9f2a7c1e0b3d_kR8sT2..." \
  -H "Content-Type: application/json" \
  -d '{"employee_id": "EMP0123", "event_type": "in"}'
```

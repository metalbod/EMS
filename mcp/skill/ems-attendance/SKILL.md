---
name: ems-attendance
description: Clock the user in or out of work in EMS, check whether they are clocked in, and check their leave balance. Use when the user says things like "clock me in", "clock out", "am I clocked in", "start my day", "how many leave days do I have", or asks about their annual or sick leave balance. Requires the EMS connector.
---

# EMS attendance and leave

Uses the EMS connector's tools: `attendance_today`, `clock_in`, `clock_out`, `leave_balance`.
These act only as the signed-in user, on their own record. Clocking in or out writes real
attendance that HR and payroll rely on.

## Clocking in

1. Only clock in when the user clearly asks. "I'm at the office" or "morning!" is not a request.
2. Call `attendance_today` first.
   - Already clocked in: tell them the time they clocked in. Do not call `clock_in` again.
   - Otherwise continue.
3. Ask for their location: "Want to share your location? Paste your latitude and longitude
   (e.g. from your phone's maps app), or say 'skip'."
   - Use only coordinates the user gave you. Never guess, look up, or invent coordinates.
   - If they skip or can't, call `clock_in` with no coordinates. This is fine. EMS records the
     clock-in as "no location".
4. Call `clock_in`, then report exactly what the tool returned: the time, and whether it was
   marked Late, outside the workplace area, or recorded without a location. Don't soften these.

## Clocking out

1. Call `attendance_today`.
   - Not clocked in: say so, and do not call `clock_out`.
   - Clocked in: tell them "You've been clocked in since 09:02. Clock out now?" and wait for a
     yes. (Skip the question only if they just said "clock me out" in plain words.)
2. Ask for their location the same way as for clocking in.
3. Call `clock_out` and report the time and the hours worked.

## Checking status or leave

- "Am I clocked in?": call `attendance_today` and answer in one line.
- Leave balance: call `leave_balance`. List each leave type with its available days. Mention
  carried-forward days and their expiry date when present. Do not guess types the tool didn't return.

## Rules

- Use the times the tools return. Do not work them out yourself or convert time zones.
- Do not retry a failed clock-in or clock-out. Report the error in the tool's own words.
- If a tool says the connection expired or was disconnected, tell the user to reconnect the
  EMS connector in Claude settings.
- If a tool says Claude access is turned off, tell them to ask HR to enable it.
- Only the user's own attendance and leave. Never clock anyone else in or out.
- You cannot change or delete attendance records, or apply for leave. Send those requests to the EMS web app.

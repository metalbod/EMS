---
name: ems-attendance
description: Clock the user in or out of work in EMS, check whether they are clocked in, check their leave balance, log hours worked to their timesheet, show their clocked and missing hours for the week, say which colleagues are on leave on a day, and tell them about the company's public holidays. Use when the user says things like "clock me in", "clock out", "am I clocked in", "how many leave days do I have", "log 3 hours on Project X", "add my hours for today", "what hours am I missing this week", "who is on leave tomorrow", "is anyone from Sales off Friday", "is tomorrow a public holiday", "when is the next public holiday", or asks about their timesheet or hours. Requires the EMS connector.
---

# EMS attendance, leave and timesheet

Uses the EMS connector's tools: `attendance_today`, `clock_in`, `clock_out`, `leave_balance`, `my_projects`, `log_hours`, `week_hours`, `colleagues_on_leave`, `public_holidays`.
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

## Logging hours to the timesheet

1. Only log hours when the user asks ("log 3 hours on Apollo", "add my hours for today").
2. Call `my_projects` to get the projects, tasks and ids. Ask which project and task if it isn't clear,
   and how many hours. Never guess a project, task or number of hours. If the user's words match more than
   one task, ask.
3. Today is the default. The user can name an earlier day this week ("yesterday", "Tuesday"): turn it into a
   `YYYY-MM-DD` date. Future days and other weeks are refused by EMS, so say so and send them to the EMS web app.
4. Call `log_hours`. If that task already had hours that day, the new hours are added to them: say so and
   give the new total for that task and for the day.
5. This only saves to the week's draft timesheet. Never imply it was submitted. Submitting for approval is
   done in the EMS web app.

## Hours for the week

- "What hours am I missing?", "how's my week?": call `week_hours` and answer from its numbers: hours clocked,
  hours logged on the timesheet, holiday and approved-leave hours, expected hours and **missing hours**. Missing
  hours is the same figure My Timesheet shows (expected minus logged, holidays and leave), so don't recompute it.
- Clocked hours and logged hours are different things: clocked is attendance, logged is the timesheet. If someone
  clocked more than they logged, point out the gap, but call only EMS's "missing hours" figure "missing".
- If `clocked_in_now` is set, clocked hours include the time so far today.
- For another week, pass a date in that week.

## Who is on leave

- "Who's on leave on Friday?", "is anyone off next week?": call `colleagues_on_leave` with the day as `YYYY-MM-DD`
  (`end_date` for a range of up to 31 days, `department` to narrow it). Work out dates like "tomorrow" or "Friday" from today.
- List the names it returns for each day. Say when a person is only off for half a day (morning or afternoon).
- It only knows **approved** leave. If someone has asked but isn't approved yet, it won't show them: say "approved leave"
  rather than "everyone who is off".
- It never says what kind of leave anyone is on, and you must not guess or speculate about why anyone is away.
- Weekends and public holidays come back as non-working days with nobody listed: say so instead of "nobody is on leave".
- The person asking is not in the list. Use `leave_balance` / ask EMS for their own leave.

## Public holidays

- "Is tomorrow a public holiday?": call `public_holidays` with `date` and `end_date` both set to that day (as `YYYY-MM-DD`).
  An empty list means it is not a public holiday. If it is a Saturday or Sunday, say it's a weekend too.
- "When is the next public holiday?": call it with no arguments (it returns the next 5 from today); answer with the first one
  and mention how far away it is. "Which holidays are left this year?": set `end_date` to 31 December.
- These are the company's own holiday list in EMS, so don't add holidays from your own knowledge. If the list looks empty
  for a year, say EMS has no holidays set up for it and suggest checking with HR.

## Rules

- Use the times the tools return. Do not work them out yourself or convert time zones.
- Do not retry a failed clock-in or clock-out. Report the error in the tool's own words.
- If a tool says the connection expired or was disconnected, tell the user to reconnect the
  EMS connector in Claude settings.
- If a tool says Claude access is turned off, tell them to ask HR to enable it.
- Only the user's own attendance and leave. Never clock anyone else in or out.
- You cannot change or delete attendance or timesheet entries, submit a timesheet, or apply for leave. Send those requests to the EMS web app.
- If a tool says the connection doesn't have permission, the user connected before that feature existed: tell them to disconnect and reconnect the EMS connector in Claude.

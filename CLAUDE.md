# CLAUDE.md — EMS project guide

This file is read automatically at the start of every Claude Code session
in this repo. It's the map — deep-dive details already live in `README.md`
and inline code comments; this file exists so a **fresh session with no
prior context** can get oriented fast and avoid re-discovering the same
gotchas.

## What this is

Multi-tenant HR platform (EMS = Employee Management System) for
Malaysian companies: employees, recruitment (ATS), onboarding/offboarding
checklists, L&D, leave, timesheets/projects, overtime, payroll (EPF/
SOCSO/EIS/PCB), performance management, compensation (pay grades, bonus/
commission plans, equity), benefits (enrollment, dependents, claims),
attendance (shifts, clock-in/out, geofencing, device webhooks), and
per-institution custom roles.

**Stack**: FastAPI + Postgres (Supabase) backend, vanilla JS frontend (no
framework), deployed to Fly.io. No ORM — raw SQL via a thin `db.py`
wrapper everywhere.

## Read README.md first for these (already documented in depth)

- Two-database-role RLS setup (`DATABASE_URL` vs `ADMIN_DATABASE_URL`)
- Frontend structure, Tailwind build step, asset versioning
- Async ops via Celery (payroll runs, bulk upload)
- Testing (pytest, Vitest, xdist deadlock retries)
- Alembic migration workflow
- Currency storage (`NUMERIC(12,2)`, not float)
- Row-level security / tenant isolation mechanics
- Benefits, Attendance, Leave, and Approval Workflow module internals

## Module map (routers/*.py — what exists, even if not in README yet)

| Router | Covers |
|---|---|
| `employees.py` | Employee CRUD, bulk upload, rehire, org data |
| `orgchart.py` | Org chart tree/reporting-line queries |
| `recruitment.py` | Requisitions, candidates/ATS, interviews, offers |
| `onboarding.py` | Onboarding/offboarding templates + checklists, item attachments |
| `ld.py` | Learning & Development courses/enrollments |
| `leave.py` | Leave types, applications, balances, carry-forward |
| `timesheets.py` | Timesheet entries against projects/tasks |
| `overtime.py` | Auto-detected overtime (vs. Attendance shift), leave/pay conversion |
| `projects.py` | Projects, tasks, task assignments, project managers |
| `attendance.py` | Shifts, clock-in/out, geofencing, device webhooks |
| `payroll.py` | Payroll runs, payslips, statutory calculations |
| `performance.py` | Appraisal cycles, calibration, manager review |
| `compensation_*.py` | Pay grades/bands, bonus, commission, equity, merit cycles, total rewards |
| `benefits.py` | Plan catalog, enrollment, dependents, claims, compliance |
| `locations.py`, `location_features.py`, `location_phase2.py` | Multi-location: assignments, transfers, budgets, capacity alerts |
| `approval_workflow_settings.py` | Configurable approval chains (see README) |
| `roles.py` | Per-institution custom roles (built-ins + additions like "IT Infra") |
| `assistant.py` | AI self-service chatbot (Claude Haiku) over the caller's own/team's leave, payroll, benefits, timesheet data — read-only, server-side-scoped tools, Redis-backed hourly rate limit |
| `users.py` | User accounts, role assignment |
| `institutions.py` | Tenant (company) CRUD, superadmin-only |
| `dashboard.py` | Personal To-Do widget (aggregates pending items across modules) |
| `holidays.py`, `notifications.py`, `hr_notes.py`, `audit.py`, `meta.py`, `auth.py`, `tasks.py`, `health.py`, `frontend.py` | Supporting/cross-cutting |

## Recently added (not yet in README's prose — check git log for detail)

- **AI usage report** (Settings → AI Assistant → **Usage** tab,
  `ai_usage_log` via `20261004_0001_add_ai_usage_log`, `core/ai_usage.py`,
  `GET /api/assistant/usage` in `routers/assistant.py`,
  `static/js/ai-assistant-settings.js`) — token counts (input + output) per
  person, split into AI chat vs. resume extraction, for This month / Last
  30 / Last 90 days / All time. **hr_manager only**, same gate as the API
  key tab (`ASSISTANT_SETTINGS_ROLES`) — hr_admin deliberately gets
  nothing here (asked explicitly; the page also holds the billing key).
  Tokens only, no dollar estimate (would mean hardcoding a price that goes
  stale). Recording is `log_ai_usage()` after each successful Claude call:
  one row per chat *message* (the tool loop's several Claude calls are
  summed via `_run_tool_loop`'s `usage` accumulator) and one per resume
  extraction — logged even if the extraction's response then turns out
  unusable (502), since the tokens were spent anyway. Best-effort: a
  logging failure is swallowed, never fails the chat/extraction itself.
  Rate-limited, canned-reply and failed-API requests spend no tokens and
  log nothing. **Nothing was recorded before 2026-10-04**, so earlier
  usage can't be recovered. `user_id` has no FK on purpose (deleting a
  user must not erase or be blocked by their history); `username` is a
  snapshot so a deleted account still shows up labelled. The report names
  people by linked employee name → user full name → username. Date range
  is applied in the institution's own timezone (`created_at` is UTC text),
  but the Usage tab computes "today"/"this month" from the *browser's*
  local date — fine when the viewer is in the org's timezone. The table
  is per-institution (RLS `tenant_isolation`).
- **Add Candidate → "Extract details with AI"** (`routers/recruitment.py`'s
  `extract_resume_fields`, `static/js/recruitment.js`) — reads an attached
  resume and prefills the Add Candidate form, reducing manual entry.
  Attachments moved from the Education tab to the top of Personal Info
  (attach-resume-first workflow); once a PDF or image is attached (new
  candidate only — editing an existing one never shows this), an "✨
  Extract details with AI" button appears. Reuses the AI assistant
  chatbot's BYOK-or-platform Anthropic key resolution
  (`core.anthropic_client.get_client_for_institution`) and model
  (`claude-haiku-4-5`), but inverted: a single *forced* tool call
  (`tool_choice`) whose `input_schema` is the candidate-fields schema, so
  Claude returns structured JSON instead of choosing from read tools —
  the first use of document/image content blocks or structured-extraction
  tool use in this codebase (the chatbot is text-only, tools there are
  zero-arg reads). PDF and image only — Anthropic's API doesn't accept
  Word natively; a Word resume can still be attached as a file, there's
  just no AI button for it (`CAND_AI_EXTRACTABLE_MIMES` client-side,
  `AI_EXTRACTABLE_MIME_PREFIXES` in core/validators.py server-side).
  Extracted fields only ever fill a *blank* input, never overwrite
  something HR already typed — including two fields that come pre-filled
  with a non-empty default in the markup (`candExp` starts at `"0"`,
  `candNationality` at `"Malaysian"`), which needed an explicit
  `BLANK_SENTINELS` check in `fillBlankCandidateFields` since a plain
  "is this field empty" test would otherwise treat the untouched default
  as something HR had already set and never let extraction override it —
  worth remembering if another field with a non-empty default needs the
  same treatment later. Expected Salary/Notice Period/Referral
  By/Source/requisition are deliberately not AI-filled — a resume doesn't
  reliably state those, so guessing would create bad data; stays
  HR-entered. After filling name/email/IC, the existing duplicate-
  candidate check (`onCandIdentityInput()`) still fires automatically.
  Own Redis rate limit (`recruitment_extract_resume_rl:`, 5/user/hour —
  tighter than the chatbot's 30, since each call is a heavier
  document/vision request), same fail-open-on-Redis-error pattern as
  `routers/assistant.py`. Nothing persisted and no audit log entry for an
  extraction call itself (same "ephemeral, not logged" treatment as the
  read-only assistant chat) — the candidate's eventual save still logs
  normally.
- **Hash-based page routing** (`static/js/core.js`'s `showPage()`/
  `bootApp()`) — added 2026-10-01 so a refresh (or Back/Forward) restores
  whichever of the 58 `ALL_PAGES` entries was open instead of always
  landing on Home/dashboard. `showPage()` syncs `location.hash` to the
  page it's showing (skipped when the hash already matches, so it never
  fights the browser's own Back/Forward navigation); a `hashchange`
  listener calls `showPage()` for Back/Forward and hand-edited hashes;
  `bootApp()` reads `location.hash` on login instead of hardcoding
  `showPage('dashboard')`. A hash is only honored if
  `isPageReachableFromNav()` — the page has a nav entry not role-hidden by
  `applyRoleUI()` (skipping `.nav-submenu.hidden`, which is just a
  collapsed fold, not role-hiding) — otherwise it falls back to Home, both
  at boot and in the `hashchange` listener. Added after a live report: an
  hr_manager on #requisitions hit F5, the session had expired, and
  re-login came back as the default `manager` role still on the (now
  empty, shouldn't-be-visible) Job Requisitions page. Backend access was
  never affected — this is purely about not opening a screen the sidebar
  itself wouldn't show. Scoped to the top-level page only — no other
  UI state is persisted anywhere in this app (open tab, open modal, list
  filters/sort/pagination all stay in-memory-only, reset on reload), so
  restoring page-only state matches what the rest of the app already
  does rather than being a partial version of something deeper. Doesn't
  cover a superadmin viewing a specific institution:
  `currentInstitution` is in-memory only and always resets to `null` on
  a fresh load (same as before this change) — unrelated to the hash, a
  superadmin always lands back on the institution picker regardless of
  which page they were on. No backend change needed —
  `routers/frontend.py`'s catch-all already serves `index.html` for any
  path and never even sees the hash (fragments aren't sent to the
  server). Doesn't touch or conflict with `public_careers.js`'s
  path-based routing for the unauthenticated `/careers/...` pages —
  different mechanism (`location.pathname`, checked before login) and
  different URL namespace (path vs. hash) entirely.
- **Sticky modal footers (Save/Cancel always visible, no scroll needed)**
  — rolled out 2026-10-01 to ~45 modals across the app (started with just
  `#projectModal` after it was reported live, then swept the rest the
  same day). The pattern: the modal's outer panel is `flex flex-col`
  with a fixed `style="max-height:85vh"`; header and tab bar are
  `shrink-0`; the scrollable body is `.overflow-y-auto.flex-1`; and the
  action buttons live in their own `shrink-0` bar *outside* that
  scrollable div, not inside it — `#populateHolidaysModal` already did
  this correctly and was the template copied everywhere else. Where the
  buttons used to sit inside a `<form>`, the form itself became the
  scrollable element (`id="xForm"` added where missing) and its submit
  button moved into the external footer bar via `<button type="submit"
  form="xForm">` (HTML5 form association — works regardless of DOM
  nesting, confirmed no JS in this codebase relies on
  `event.target`/`FormData` assuming the button is a form descendant).
  For a tabbed modal where **each tab needs different buttons**
  (Projects' Details vs. Tasks), use one footer div per tab, toggled
  alongside the tab panes themselves (e.g. `switchProjectTab()`'s
  `projectModalFooter-${t}` toggle). For a tabbed modal that shares
  **one** footer across all tabs regardless of which is active (Add
  Employee's wizard Next/Previous/Save, Add Candidate's 4 tabs), a
  single footer with `form="xForm"` is simpler and is what most tabbed
  modals here actually need. Also fixed in the same pass: a handful of
  modals (`leaveApplyModal`, `resignModal`, `holidayModal`,
  `employeeDocumentModal`, `startObModal`, `ldCourseModal`,
  `ldEnrollModal`, `employeeDocTypeModal`, `obTmplItemModal`) used a
  *different*, worse backdrop pattern (`items-center justify-center`
  with no `overflow-y-auto` at all) — tall content there didn't just
  need scrolling, it was **clipped with no way to reach it**; all were
  switched to the same `items-start overflow-y-auto py-8` backdrop every
  other modal uses. Left unfixed (checked and judged low-risk — short,
  static, no dynamically-growing content): `deviceModal`, `payoutModal`,
  `probGoalTemplateModal`, `offerViewModal` (already caps its content at
  `max-h-96`), `compensationMeritModal`, `ldModulesModal`,
  `equitySettleModal`, `enrollmentPeriodModal`, `cycleModal`,
  `compensationJobLevelModal`, `payrollRunModal`, `claimDecideModal`,
  `changePasswordModal`, `applyModal`, `payslipViewModal` (print-layout,
  deliberately left alone), `pipDetailModal`. If one of these grows a
  dynamically-expanding list later (like the LD quiz builder questions
  did), it needs the same fix — don't assume "already checked" stays
  true forever.
- **Fixed: `has_permission()` silently never enforced overrides for
  per-institution custom roles** (`core/permission_matrix.py`,
  `routers/roles.py`). Found live in institution 4: HR granted the custom
  "Hiring Manager" role access via Settings → Roles → Permission Matrix
  (the UI showed it as granted), but the user still couldn't see
  Recruitment at all. Root cause — `routers/roles.py`'s
  `get_permission_matrix` (display) and `_validate_overridable`
  (write-time) both already proxied a custom role to `"employee"` for its
  default/eligibility check (`eligibility_proxy_role`, now exported from
  `core/permission_matrix.py` so both files share one copy instead of
  drifting again), but `has_permission()` — the actual runtime enforcement
  every `require_permission()` call goes through — checked the raw custom
  role string directly against MATRIX's static access dicts (which only
  ever have the 6 built-in roles as keys). That always missed, so
  `is_override_eligible()` returned `False` and the override table was
  never even queried — a custom role was hard-denied for every enforced
  action with no way to grant it back, regardless of what the matrix UI
  displayed. `has_permission()` now applies the same `eligibility_proxy_role`
  for its default/eligibility check, while still looking up the override
  row by the *literal* role key — a custom role's override is stored (and
  must stay) independent of Employee's, so a custom role and real
  employees can be granted different access for the same action.

- **Recruitment's "View requisitions / candidates / interviews / offers"
  permission-matrix action is now enforced** (`core/permission_matrix.py`,
  `routers/recruitment.py`) — second module retrofitted into
  `ENFORCED_ACTION_KEYS` after the Employees pilot. `list_requisitions`/
  `get_requisition`/`list_candidates`/`get_candidate`/`list_interviews`
  previously had no gate at all; `list_offers`/`get_offer` were tied to
  the *write* action's key instead of their own (a pre-existing doc/
  reality mismatch) — all seven now call `require_permission(conn, user,
  "recruitment.view_requisitions_candidates_interviews_offers")`, whose
  matrix row defaults to `hr_manager`/`hr_admin` only (locked) with
  `manager`/`payroll_manager`/`compensation_manager`/`employee`
  denied-by-default but override-eligible via Settings → Roles →
  Permission Matrix. First time an enforced action's default/override
  state also drives **frontend nav visibility**, not just backend 403s:
  `GET /api/auth/me`'s new `can_view_recruitment` field (`core/deps.py`'s
  `build_current_user_out`, computed via `has_permission()`) is what
  `static/js/core.js`'s `applyRoleUI()` checks to show/hide
  `#nav-recruit-group` — reflects this institution's own
  `role_permission_overrides`, not a static role list, so granting
  `manager` access makes the nav reappear without a code change. The Home
  dashboard's own Recruitment tab (Open Positions for non-recruiting
  roles — see the entry below) is unrelated and unaffected: it reads the
  public careers listing endpoint, which has no permission check at all.
  Home's "Open Roles" KPI tile already had a generic "hide the link,
  keep the number" fallback for exactly this case (`dashboard.js`'s
  `_canOpenPage`), so it needed no changes — once the nav item is hidden,
  the tile stops being clickable automatically.

- **Recruitment screens' write/history controls follow the permission answer, not a role
  list** (`can_manage_recruitment`, `can_view_candidate_history`,
  `can_view_candidate_stage_time` on `GET /api/auth/me`, `core/deps.py`'s
  `build_current_user_out` → `has_permission()`; `canManageRecruitment()` etc. in
  `static/js/recruitment.js`) — found live in institution 4: the custom "Hiring Manager" role had
  "Create / edit requisition, candidate, interview, offer" overridden to *allow* and the API
  accepted it, but "+ New Requisition" (and Add Candidate / Interview / Offer, the public-link
  toggle, the candidate History and Time-in-Stage tabs) were still hidden by
  `HR_MANAGE_ROLES.includes(role)`. Same pattern as `can_view_recruitment`. Approving a
  requisition is untouched (approval-workflow engine, `HR_MANAGER_ONLY_ROLES`). When another
  module's action is added to `ENFORCED_ACTION_KEYS`, its screen's buttons need the same
  server-computed flag or the override will work in the API and not in the UI.

- **Public (no-login) job applications** (`routers/public_careers.py`,
  `static/js/public_careers.js`, `20261001_0002_add_requisition_public_token`):
  the only unauthenticated, no-pre-shared-secret write path anywhere in this
  app — everything else is gated by `core/deps.py`'s `get_current_user` (JWT)
  or `routers/attendance.py`'s `get_device` (a provisioned device API key).
  HR enables it per requisition (`POST/DELETE .../requisitions/{id}/
  public-link`, only while `Approved`), which mints/clears a random UUID
  `job_requisitions.public_token` — deliberately not the requisition's own
  sequential `id` (shared across every institution; would let someone
  enumerate other companies' postings) and not institution code + id. Two
  public routes read it: `GET /api/public/careers/{institution_code}` (a
  listing of that institution's Approved + public-enabled roles) and `GET`/
  `POST /api/public/careers/apply/{token}` (one job's details / the
  application itself) — both re-check the requisition's status live on
  every request, so closing it takes effect immediately without HR needing
  to separately revoke the link. Institution/tenant RLS scoping is resolved
  from the token (or institution code) rather than from a logged-in user —
  `resolve_public_requisition` must stay `async def` with its DB calls made
  directly (not `asyncio.to_thread`, not `@db_session`), the same
  constraint `get_device`'s own docstring documents: `set_rls_context`'s
  ContextVar only propagates to this request's later `get_db()` calls if
  the mutation happens on the request's own asyncio task. The same two
  endpoints serve a logged-in employee too (no separate "internal" flow) —
  `static/index.html`'s `#publicCareersScreen` is shown instead of the
  login screen when the URL matches `/careers/...`, checked first in
  `app-init.js`'s boot IIFE, regardless of whether a session token exists;
  `loadPublicApplyForm` prefills from `/api/auth/me` when one does, and the
  submit tags `source="Internal"` only when that session's own
  `institution_id` matches the requisition's (never for an employee of a
  *different* institution applying to this one). Deliberately has **no**
  "is this an existing candidate?" prompt back to the caller (unlike the
  HR-facing duplicate-detection panel in Add Candidate) — telling an
  anonymous visitor "we already have a candidate with this email" would
  leak who else is in the system; the match-by-email-and-reuse-or-create
  in `submit_public_application` is silent, and the response is identical
  either way, including when the same email re-submits to the same job.
  Resume uploads here use a tighter allowlist than HR's own
  `candidate_documents` upload (`validate_public_resume_data_url` — PDF/
  Word only, no plain text or images), since this is the one truly public
  upload surface in the app. Abuse protection is new, not reused: an
  in-memory per-IP rate limit (same deliberate single-process tradeoff as
  `routers/auth.py`'s login limiter — move to Redis if this ever runs as
  multiple workers/machines) and optional Cloudflare Turnstile (`TURNSTILE_
  SITE_KEY`/`TURNSTILE_SECRET_KEY` — set as **Fly secrets**
  (`fly secrets set`), not `.env`, so local dev/tests keep skipping
  verification unset; live and verified working in prod as of 2026-10-01).
  Also surfaced inside the app itself: Home's **Recruitment** tab
  (`static/js/dashboard.js`'s `loadRecruitmentDash`/
  `loadOpenPositionsForEmployee`) is now shown to every role, not just
  HR/manager — HR still sees the existing analytics section
  (`recruitDashSection`), but any other role (employee, etc) sees an "Open
  Positions" list instead, fetched straight from the same
  `GET /api/public/careers/{institution_code}` the public page itself
  uses, each with an Apply link into `/careers/apply/{token}` (opened in a
  new tab) — the logged-in-prefill/`source="Internal"` tagging in
  `routers/public_careers.py` kicks in automatically since it's the exact
  same endpoint.

- **Approval workflow** now also covers **Timesheet** and **Overtime**,
  supports a **Project Manager** approver type (resolved via the
  request's own project(s) — direct on Leave/Claims/Timesheet, via the
  parent timesheet on Overtime), and a per-step **alternative ("OR")
  approver** (`alt_approver_type`).
- **Overtime module** (`core/overtime.py`, `routers/overtime.py`):
  detected automatically at timesheet submission by comparing logged
  hours against the employee's resolved Attendance shift
  (`core/attendance_helpers.py`, shared with `routers/attendance.py`).
  Goes through its own approval-workflow chain; on approval, converts to
  either credited leave or a tracked pay amount per an institution-level
  setting (`institutions.overtime_conversion_mode`) — pay is
  tracking-only, not yet wired into payroll.
- **Per-institution custom roles** (`core/roles.py`'s
  `get_valid_roles`, `routers/roles.py`, Settings → Roles UI): 6 built-in
  roles are fixed; HR can add more, usable as a user's `role` and as an
  onboarding/offboarding item's `assigned_role`. Role validation lives in
  the endpoint body (needs a DB connection + inst_id), not a static
  Pydantic `field_validator`.
- **Onboarding/offboarding checklist item attachments**
  (`ob_item_attachments` table): optional proof-of-completion file
  upload per item (photo/document, ~6MB cap, base64 data URI — same
  pattern as `candidate_documents`), never required to mark an item Done.
- **Dashboard To-Do** now also surfaces pending onboarding/offboarding
  checklist items (one row per item, not an aggregate count) alongside
  the approval-workflow items.
- **Settings → Roles → Permission Matrix** (`core/permission_matrix.py`,
  `routers/roles.py`): a hand-curated, read-only reference of role access
  across ~90 actions/24 modules — not derived from the routers at
  runtime, since most gates are inline checks, not a uniform decorator.
  On top of that, `manager`/`employee`/custom-role access is now actually
  **editable per institution** via `role_permission_overrides`
  (`PUT`/`DELETE /api/roles/permission-matrix/override`) —
  `hr_manager`/`hr_admin`/`payroll_manager`/`compensation_manager` are
  permanently locked and can never be overridden. This is a deliberate
  **pilot**, wired into only 6 of `routers/employees.py`'s actions so far
  (`ENFORCED_ACTION_KEYS`) — retrofitting the other ~23 modules to call
  `has_permission()` instead of their existing `require_roles(...)`/inline
  checks is intentionally left as separate, incremental follow-up work,
  not a one-shot rewrite of the app's access control. See
  `permission_matrix.py`'s module docstring before touching either file.

- **"One candidate, many requisitions" — all 4 phases shipped**
  (`candidate_requisitions`, `migrations/versions/
  20260930_0002_add_candidate_requisitions.py` and
  `20261001_0001_drop_candidates_legacy_application_columns.py`,
  `routers/recruitment.py`, `static/js/recruitment.js`,
  `static/index.html`): `candidates.requisition_id` used to be a single
  nullable FK — one `candidates` row per application, so the same real
  person applying to a second requisition meant a second, unrelated row
  with no link to the first. `candidate_requisitions` is the real
  per-application record (`stage`/`source`/`notes`/`expected_salary`/
  `notice_period`/`referral_by`, `UNIQUE(candidate_id, requisition_id)` plus
  a partial unique index limiting a candidate to at most one NULL-requisition
  "general interest" row); `candidate_stage_history` grew a `requisition_id`
  column alongside it, since it used to assume at most one open stage per
  candidate. `create_candidate` inserts the person's first application
  there too; `POST /api/recruitment/candidates/{cand_id}/apply` applies an
  *existing* person to another requisition without duplicating their
  profile; `GET .../candidates/search` is the person-level lookup (by
  name/IC/email/phone, each match's `applications` array included) driving
  the Add Candidate modal's duplicate-detection panel; `PATCH .../
  candidates/{cand_id}/requisitions/{requisition_id}/stage` moves one
  application's stage explicitly (`requisition_id=0` in the URL means the
  NULL/general-interest application — a path param can't carry NULL).
  `_transition_candidate_stage` (the single place a `candidate_requisitions`
  row's stage is ever written, called from `move_stage`/`schedule_interview`/
  `create_offer`/`update_offer_status` too) is the one to read before
  touching stage transitions again.
  **Phase 4** (`20261001_0001_drop_candidates_legacy_application_columns.py`)
  dropped `candidates.requisition_id`/`.stage`/`.source`/`.notes`/
  `.expected_salary`/`.notice_period`/`.referral_by` outright — every
  remaining read of them was rewired first, in the same commit:
  `list_candidates` (the Candidate Bank table, and the Interview/Offer
  "select candidate" pickers that reuse it) is now one row per
  APPLICATION, not per person, matching `list_requisitions`'s/
  `get_requisition`'s own per-application counts;
  `_candidate_with_derived_fields` (routers/recruitment.py) is the read-side
  replacement for the old mirror columns — it derives a candidate's
  top-level `stage`/`requisition`/`source`/`notes`/`expected_salary`/
  `notice_period`/`referral_by` from their SOLE application when they have
  exactly one, else `None` (there's no single answer once a person has more
  than one — the Applications section in Candidate Detail, Phase 3, is the
  real multi-application view, and the header stage badge there just hides
  rather than showing "undefined"). `schedule_interview` and `create_offer`
  now resolve a missing `requisition_id` from the candidate's sole
  application too (`_sole_application_requisition_id`) — the Interview
  modal never had a requisition picker of its own, and the Offer modal's
  defaults to blank, so before this fix every interview silently landed on
  NULL/general-interest regardless of which real requisition the candidate
  was for; the Interview/Offer candidate pickers now carry a `data-req-id`
  per option (one per application) so this is explicit, not guessed, when a
  specific application is picked.
  Phase 3 (frontend, `static/js/recruitment.js`): the Add Candidate modal's
  Full Name/IC/Email inputs debounce-search `.../candidates/search` as HR
  types and surface matches in a dismissible `#candDupPanel` ("is this the
  same person?") — picking one calls `.../apply` with whatever the form's
  already filled in, instead of creating a duplicate `candidates` row.
  Email is mandatory (`CandidateIn.email`, backend-validated, not just the
  input's `required` attribute) and wired into this same search
  (`candDupSearchQuery`'s priority: IC > email > name) — added
  2026-10-01, since it's the identity signal HR actually recognizes a
  repeat applicant by, and the public careers application endpoint
  (`routers/public_careers.py`) already required it for the same reason.
  Candidate Detail's Profile tab conditionally shows an Applications
  section with its own per-row stage control once `c.applications.length >
  1` (`shouldShowPerApplicationStages`) — until then the legacy single
  `#cdStageSelect` keeps working exactly as before, unchanged, since
  `move_stage` (the endpoint behind it) 400s past one application. A
  standalone "+ Apply to Another Req" button/modal on Candidate Detail is
  the second entry point into `.../apply`, for an already-open candidate
  instead of mid-Add-Candidate.

- **Generic audit trail (`entity_audit_log`)** (`core/audit.py`'s
  `write_entity_audit` + `diff_fields`, `GET /api/entity-audit-log` in
  `routers/audit.py`, Settings → Audit → System Activity tab, shared
  `openEntityHistory()` modal in `core.js`): one tenant-scoped table for
  modules that have no dedicated `*_audit_log` of their own — call
  `write_entity_audit(...)` right before the endpoint's `conn.commit()`,
  never with secret values (mask via `diff_fields(..., sensitive=...)`).
  Rolled out in four phases (all shipped): payroll, users/roles/permission
  overrides, approval workflows, institution/email/AI-key settings;
  compensation/leave/overtime/timesheet settings; attendance, benefits,
  holidays, locations, projects, onboarding, L&D, recruitment, performance,
  documents, notifications; then the remaining approval decisions (overtime,
  PIP, resignation, location transfers), system-wide notifications and role
  switching. The read endpoint also unions the older per-module trails
  (candidate, requisition, onboarding, L&D, leave, timesheet, appraisal)
  read-only. Platform-level events (no tenant: superadmin accounts,
  system-wide notifications) are stored with `institution_id` NULL and only a
  superadmin's view returns them. Deliberately NOT logged: draft timesheet
  entry edits (submit/approve already are), clock in/out and device events
  (the attendance record is the trail), and the read-only assistant chat. A
  new module needs no new table — just log in its endpoints (and, if the
  endpoint reads `conn._last_id`/`last_insert_rowid()` afterwards, capture it
  *before* the audit insert, which overwrites both).

- **Add User: "Send random-generated password to email"** (`routers/users.py`'s
  `create_user`/`generate_random_password`, `static/js/users.js`'s
  `onSendPasswordToggle`) — `send_password: true` on `POST /api/users`
  ignores any typed password, generates a 12-char one (no look-alike chars,
  all four character classes), emails it via the institution's own SMTP
  (`core/email_engine.send_email`, category `new_user_password`) with the
  company code + username, and forces `must_change_password` for every role
  (including hr_manager/hr_admin, who are otherwise exempt). Nobody — not
  even HR — ever sees the password, so the account is **only created if the
  email goes out**: no SMTP configured / email notifications off / platform
  admin with no institution → 400 before anything is inserted; SMTP send
  fails → rollback and 502. Email is mandatory in the Add form and, server
  side, whenever `send_password` is set; it is *not* enforced server-side
  for plain typed-password creates (53 test call sites create users without
  one) and stays optional on Edit so older accounts without an email can
  still be saved. The checkbox only exists on Add. The modal is a single
  column and the role checkboxes stack vertically.
  - **Re-send password + Cc** (added after a live report that the emailed
    password never arrived — the email log showed `sent`, i.e. Gmail
    accepted it; most likely spam-filtered): Edit User has a "Re-send
    password" button → `POST /api/users/{id}/resend-password` generates a
    *new* random password (the old one can't be recovered, only hashed),
    forces change at first sign-in, audits it, and emails it; if the email
    fails the password is **not** changed (rollback, 502). Refuses an
    inactive user, one with no stored email, or an institution with email
    not set up. Note a password *typed* by HR in Edit still clears
    `must_change_password` (existing `update_user` behavior) — only the
    emailed paths force a change. The "CC <address>" checkbox (Add, once
    "send password" is ticked, and Edit) copies the institution's own sender
    mailbox (`institutions.smtp_from_address`), not a hardcoded address;
    `GET /api/users/email-options` tells the form whether email is ready and
    which address that is. `send_email(..., cc=)` is the new generic Cc
    support in `core/email_engine.py`.

- **Login by username or email** (`routers/auth.py`'s `_find_login_user`;
  login box label "Username or Email") — the request field is still named
  `username`. An exact username match always wins (usernames are unique per
  institution, and some are themselves email-shaped, e.g. `sarmini.devi@
  mandrill.com.my`); only if none matches and the text contains `@` is it
  tried as an email — case-insensitive, trimmed, scoped to the same company
  code (or platform-level users when no code is given). `users.email` is not
  unique, so an address shared by two accounts in the institution matches
  **nobody** by email (generic 401, no hint) and those people sign in by
  username. Rate limiting and the login audit still key on whatever was typed.

- **Onboarding/offboarding progress + auto-complete** (`routers/onboarding.py`):
  the list's `done_items` counts Done **and** N/A (same rule as the detail
  modal and auto-complete), computed live from `ob_checklist_items`, and the
  screen refreshes the list after adding/removing an item. Removing the last
  unfinished item now completes an In Progress checklist, exactly like ticking
  it would (`_auto_complete_if_all_done`, shared by both paths); a checklist
  with zero items left is never auto-completed.

- **Onboarding/offboarding template board** (Settings → Workforce → Onboarding/
  Offboarding → Manage Templates; `renderObSwimlane` in `static/js/onboarding.js`,
  `PUT /api/ob/template-sets/{id}/layout` in `routers/onboarding.py`) — replaced the
  old horizontal swimlane (roles as rows, items left-to-right with sequence arrows).
  Now one **column per role, always shown** (classic 4 first, then every other
  `rolesCache` role, then any orphaned role an item still holds), each stacking that
  role's items from the top; cards drag within a column (re-order) or to another
  column (hand to that role), saved on drop as the whole set's ordered
  `[{id, assigned_role}]` in one transaction (409 if the set changed under you,
  optimistic UI with rollback). Up/down buttons per card are the touch/keyboard
  alternative (HTML5 drag-and-drop doesn't work on touch). **No arrows**: nothing in
  the data says one item depends on another — `ob_templates.order_index` is only list
  order (kept as one global sequence; a role's column order is the relative order of
  its items), and checklists don't enforce order at runtime, so none are drawn until
  real dependencies exist (planned "Phase 2": a prerequisites table copied onto
  checklist items at start). Reordering a template never touches already-started
  checklists (they snapshot at start). The old `POST /api/ob/templates/{id}/move`
  (swap with the global neighbour) is no longer used by the UI.
  **Phase 2a — item dependencies** (`ob_template_dependencies`, migration
  `20261008_0001`; `PUT /api/ob/templates/{id}/dependencies` replaces an item's
  "starts after" list; `GET /api/ob/templates` and the layout endpoint return
  `depends_on` per item): HR links items by dragging a card's link handle onto
  another card (or via "Starts After" in the item dialog). Rows are computed, not
  stored (`obComputeRows`): no prerequisites = top of its column; otherwise one row
  below the lowest prerequisite, bumped down if the cell is taken — so arrows (straight
  lines, drawn only for real links, under the cards) always point down/across. Server
  refuses self-links, other-set items and loops (`_would_create_cycle`); removing an
  item deletes its links. **Template-only for now**: started checklists don't copy or
  enforce links. Decided for "2b" (not built): checklists snapshot the links; a blocked
  item can't be ticked by anyone but HR Manager/HR Admin until every prerequisite is
  Done or N/A; blocked items stay out of the To-Do list.
  **Phase 2b — built** (`ob_checklist_item_dependencies`, migration `20261008_0002`):
  `_create_ob_checklist` copies the template's links onto the new items (snapshot; manually
  added items have none). `GET /api/ob/checklists/{id}` annotates each item with
  `depends_on`, `waiting_for` (unfinished prerequisites: id/title/role) and `blocked`
  (Pending with something unfinished); an employee viewer gets `title: null` for other
  roles' prerequisites (their tasks stay hidden). `update_ob_item` returns 403 "waiting
  for: …" when a non-HR role (anyone but superadmin/hr_manager/hr_admin,
  `BLOCK_OVERRIDE_ROLES`) marks a blocked item Done or N/A — un-ticking back to Pending
  is never blocked. A prerequisite counts as satisfied when Done **or** N/A. Blocked
  items are excluded from the dashboard To-Do list, the list's "Action Required"
  (`my_pending`) and the overdue-checklist reminder emails
  (`scripts/send_reminders.py`) until unblocked. Not affected: the L&D course
  auto-complete path (`core/ob_ld_shared.py`, a course finishing is a fact), the
  checklist calendar, and auto-completing a checklist. Removing a prerequisite item from
  a running checklist unblocks its dependents (FK `ON DELETE CASCADE`). The checklist
  window shows "⏳ Waiting for: …" (with "(HR can override)" for HR).

- **Button convention** (Oct 2026; `static/css/styles.css`, block starting "Button
  convention", plus "Pointer" and "Close X" at the end) — **clear pill** = transparent,
  1px `--line-strong` (#8C979E, ~3:1 on white; `--line` stays for dividers) border,
  `--ink` text, light fill on hover: `.btn-ghost` (Cancel, Close, Prev/Next, secondary
  buttons, filter chips), `.pill-btn-outline`, inactive tabs/chips. **Active option** =
  `--accent-tint` fill + `--accent` border + bold `--accent-ink` text; every option group
  toggles its own class from JS (`ob-filter-active`, `leave-filter-active`, `tab-active`,
  `view-tab-active`, `pill-tab-active`, ...), so the look is defined once in CSS and the JS
  was left alone — a new group just needs its `*-active` class added to that list.
  **Primary** stays solid `--accent-ink`. **Tabs of every style are pills now**
  (`.view-tab-btn/.tab-btn/.project-tab-btn/.cand-form-tab`); the bar's old bottom
  divider is removed by a `:has(> tab-button)` rule, so new tab bars need no extra markup.
  **Close X** = `.btn-close` (round clear pill; `-sm`, `-on-dark` variants; the 74 modal X
  buttons were converted by markup). **Row actions** written as small coloured text links
  (`text-xs … hover:underline` buttons: Edit/Delete/Approve/Reject…) become compact clear
  pills via an attribute selector, text colour kept (Delete/Reject red). **Pointer**:
  Tailwind 4 no longer gives buttons `cursor:pointer`, so one global rule covers every
  clickable control (buttons, tabs, selects, `[onclick]`, file/checkbox inputs). Gotcha:
  styles.css is *unlayered* so it beats Tailwind utilities on the same element (e.g.
  `px-4 py-3 text-slate-500` on a tab button are ignored) — change the CSS, not the
  utility classes. Icon-only row buttons (trash/edit icons) are deliberately left as icons.

- **Approval emails are sent in the background** (`queue_email`/`_deliver` in
  `core/email_engine.py`, `Conn.after_commit` in `db.py`; used by
  `core/approval_workflow.py`'s two notification helpers) — added after Resign/Approve
  took several seconds: each email costs ~3 s (fresh SMTP connection + TLS + login) and
  a resignation filing notifies ~3 approvers inside the request. `queue_email()` only
  remembers the message on the request's `Conn`; when that connection **commits** the
  batch goes to a 2-thread pool that sends it over **one** SMTP session on its own DB
  connection and writes the `email_log` rows there (so those rows now appear a moment
  after the request). A rollback or `close()` without a commit drops the queue, so an
  email never announces a change that didn't persist; a send failure is logged
  (`status='failed'`), never shown. A queued email needs the request to commit afterwards
  — true for every approval path today. **Synchronous on purpose**: `send_email()` (the
  Settings test email, the new-user / re-send-password emails, which must know the send
  worked, and the reminder sweeps). `EMAIL_DISPATCH=inline` runs the batch in the
  committing thread — `tests/conftest.py` sets it so existing tests can assert on
  `email_log` right after a request; `tests/test_email_async.py` covers the real
  background path by stubbing the pool. The batch runs in a copied `contextvars` context
  so setting its own RLS scope can't leak into the request.

- **Leave type carry-forward rules** (`leave_types.carry_forward_percent_basis` /
  `carry_forward_cap_rule`, migration `20261009_0001`; `_compute_carry_forward` in
  `core/leave_balance_ops.py`; the two option-pill pairs in the Edit Leave Type dialog,
  `setLeaveCarryOption` in `static/js/leave.js`) — "Max % carried" is a percentage of
  either the unused **balance** (default; unused = entitlement + carried in - used) or the
  employee's **own entitlement** for the year being carried from
  (`prior_bal["entitled_days"]`, so pro-rated years are respected, not the type's
  current default). With both "Max days" and "Max %" set, the rule carries the **lower**
  (default) or the **higher** of the two; with one set, that one applies; 0 = skipped.
  Either way the carry never exceeds the unused balance — and "higher" is deliberately
  allowed to pass the max-days limit (asked and confirmed 2026-10-09). Defaults reproduce
  the old behaviour, so existing leave types are unchanged. Carry-forward is computed once,
  when an employee's new-year balance row is first created, so changing a type's rules
  never touches balances that already exist.

- **Carried-forward leave: used first, judged on the leave's START date, split recorded**
  (`core/leave_balance_ops.py`: `_carry_usable_for`/`_available_for`/`_consume_balance`/
  `_release_balance`; `leave_applications.carried_days_used`, migration `20261009_0002`).
  Carry-forward was already drawn down before the year's entitlement; what changed:
  carried days are only usable for leave that **starts on or before**
  `carried_forward_expires_on` — judged on the leave's own start date, not on the day
  it is booked/approved (so a late approval of earlier leave can still use them, even
  after the lazy sweep forfeited them: `_consume_balance` revives them from
  `carried_forward_forfeited_days`; and leave starting after the expiry never uses them,
  nor does the availability check count them). `_consume_balance` returns how many days
  came from carry and callers store that on the application; `_release_balance` (cancel,
  holiday shortening) gives back exactly that split — and if the carry has expired by
  then those days **lapse** (forfeited) instead of coming back to life. `NULL` =
  approved before the migration → old "carried bucket first" fallback. Availability
  (`_available_for`) = usable carry + entitlement − regular (non-carry) used.
  UI: `GET /api/leave/balances` adds `carried_forward_remaining`; My Leave cards show
  "N carried forward · use by <date>" (amber in the last 30 days, "N forfeited" after),
  the Apply Leave dialog judges availability on the chosen start date and says how many
  days will come from carry, the Home leave table has a "Carried Fwd Left" column, and
  application lists show "(n carried fwd)". Helpers: `leaveCarry*`/`leaveAvailableFor`
  in `static/js/leave.js`.

- **Shared-entitlement leave types keep their own yearly limit and day counting**
  (`_check_yearly_cap`/`_year_usage` in `routers/leave.py`, `GET /api/leave/type-limits`,
  migration `20261009_0003`). A type with `shares_entitlement_with_id` draws its days from
  the pool owner's balance (`_balance_leave_type_id`) but its own `annual_entitlement`
  now means **"yearly limit for this type within the pool"** (0 = none; confirmed:
  *within* the pool, not an extra allowance) and its own `count_calendar_days` is honoured
  and editable (the server always used it; only the dialog hid it — the whole entitlement
  row was hidden, and the stored value, usually the form default 14, was never read, which
  is why the migration zeroed existing shared types so nobody is suddenly capped). Counted
  like the monthly cap: Approved + Pending Approval of *this type*, half-days 0.5, leave
  straddling New Year split by year. A booking must fit both the limit and the pool; the
  pool error names the pool ("Insufficient balance in the X pool"). Calendar-counting on
  a type whose pool counts working days charges the pool the type's own count. The pool's
  accrual mode governs the check for a sharing type (previously the sharing type's hidden,
  always-default mode was read by mistake). Screens: Edit Leave Type relabels the field
  "Yearly limit for this type (days)" when a pool is chosen (switching to "shares" starts it
  at 0), the leave type list shows "N days/yr limit", the Apply Leave note adds "n of N <type>
  day(s) left this year", My Leave shows a limit card ("taken from <pool>"). Carry-forward
  and accrual settings are hidden for a sharing type (the pool's apply), and the server drops any carry-forward settings sent for one (`_drop_own_carry_forward_if_sharing`) so the list never claims "Carries forward" for a type that can't.

- **Course documents (PDF / Word / PowerPoint) in the L&D course catalog**
  (`ld_module_files` + `ld_course_modules.file_id`, migration `20261010_0001`;
  `upload_course_file` / `download_module_file` / `replace_course_modules` in
  `routers/ld.py`; `static/js/ld.js`) — a new **"document" lesson type** next to text and
  video in Course Content: one file per lesson, ordered with the others, counted in the
  "lessons viewed" progress. Bytes are stored in Postgres (`BYTEA`, 20 MB cap —
  `LD_FILE_MAX_BYTES`; extension whitelist `.pdf/.doc/.docx/.ppt/.pptx` **plus** a
  magic-byte check so a renamed file can't pass; the DB was only ~131 MB at the time, so
  watch capacity if decks pile up — object storage is the next step). They are **not**
  inside the lesson row because `replace_course_modules` deletes and re-inserts every
  lesson on each save: HR uploads at once (`POST .../files`, base64 JSON like the app's other
  attachments), the lesson keeps only `file_id`, and the save re-links it and **deletes any
  file no lesson uses** (so a removed/abandoned upload is cleaned up on the next save;
  a deactivated course keeps its files). Download is `GET /api/ld/modules/{module_id}/file`
  (auth header, so the UI fetches a blob): HR/managers open anything; anyone else needs
  their own Approved / In Progress / Completed enrollment in that course (else 403).
  Passing the caller's **own** `enrollment_id` marks the lesson viewed — opening or
  downloading counts as reading it. `inline=true` serves a PDF for the browser viewer, every
  other type downloads; responses carry `X-Content-Type-Options: nosniff` and
  `Cache-Control: private, no-store`. The catalog shows a 📎 count; the HR Preview and the
  employee Course Viewer both render the document lesson with Open (PDF) / Download buttons.

- **API docs/schema are opt-in** (`core/api_docs.py`, `ENABLE_API_DOCS` env
  var) — `/api/docs`, `/api/redoc` and `/api/openapi.json` are served only
  when it's truthy. Local `.env`/`.env.example` set it; production never does
  (no Fly secret), so they 404 there. Before 2026-10-07 they were always on
  and the full endpoint/field map was readable without a login. If you need
  the live API surface, run locally or generate the schema from the code.

- **Timesheets were filed Sun–Sat, so the Monday reminder nagged people who had
  submitted** (found live in institution 4, 2026-10-12): My Timesheet's `tsFmt`
  (`static/js/timesheet.js`) used `toISOString()`, which converts to UTC — in
  Malaysia (UTC+8) Monday 00:00 became the Sunday, so every timesheet got
  `period_start` = Sunday (21 of 22 live rows). `sweep_pending_timesheets` looks
  for the Monday-start week, found nothing, and reminded. Fixed twice: `tsFmt` now
  formats local date parts (new timesheets start on Monday), and the sweep treats
  any Submitted/Approved timesheet that **overlaps** the Mon–Sun week as submitted,
  so the existing Sunday-dated rows are covered without re-dating them (left as is:
  approvals, overtime and payroll reference them). General rule: never build a
  `YYYY-MM-DD` from a local `Date` with `toISOString()` in a UTC+ zone — use
  `localDateStr(d)` (`static/js/core.js`). Follow-up sweep (same day) replaced the
  other date uses: the Apply Leave workday preview (`ldLeaveComputeWorkdays`
  matched holidays one day early), the Clock page's "Clocked Out" status, Benefits
  window expiry, Home calendar "today", and the Resign / Assign Compensation
  default dates. `notifications.js` is deliberately left (it converts local time
  to UTC on purpose). Regression test: `static/js/__tests__/local-dates.test.js`
  (runs the real functions with TZ=Asia/Kuala_Lumpur).
  **Follow-up regression (v0.53):** making the page ask for Mon–Sun weeks meant
  `POST /api/timesheets` (get-or-create by exact period) no longer found the existing
  Sun–Sat rows and created empty overlapping Drafts — a user saw their submitted week
  "missing" (hours were safe on the Sunday-dated row). `start_timesheet` now returns the
  employee's legacy Sunday-start timesheet for a Monday-start request (same week shifted
  one day) before creating anything; the three empty drafts it had created were deleted.
  Known leftover: a Sunday entry in a legacy-dated week (e.g. Sun 11 Oct on a 4–10 Oct row)
  is outside the stored range and is rejected, as it always was. Lesson: changing how a
  key (period_start) is computed needs a check of how existing rows are looked up by it.
  **Re-dating (migration `20261012_0001`)**: shifts Sunday-start/Sat-end timesheets (and
  the period copied onto `timesheet_project_approvals`) forward one day to Mon–Sun; entries
  keep their own dates. Skips a row when the employee already has a Monday-start timesheet
  that week (clash) or it has an entry on the old Sunday (would fall outside the range) —
  on prod that left 2 July rows for a person to decide (ts 4 inst 2 EMP0001, a Draft beside
  an Approved Monday row; ts 5 inst 4 EMP0002, Approved, 1h logged on Sun 5 Jul). Downgrade
  is a no-op. The `start_timesheet` legacy fallback stays as a safety net.
- **Home → Recruitment KPI cards count active items only** (`recruitment_dashboard_stats`,
  `loadRecruitmentDash`): "Active Candidates" = applications in New/Screening/Interview/
  Pending Checks/Offer on an **Approved** requisition (Hired, rejected, withdrawn,
  no-requisition and closed/filled/draft/pending-requisition applications are left out);
  "Upcoming Interviews" (next 7 days, Scheduled) and its "this month" line, and "Offers
  Pending" (status Sent) are likewise limited to Approved requisitions, so closing a
  requisition drops its items at once. Decided with the owner (2026-10-12). The pipeline
  and requisitions-by-status charts and the "Open Requisitions" card (Approved + Draft)
  are unchanged and still count everything; `total_candidates` stays in the response for
  the pipeline chart, `active_candidates` is the new field the card reads.
- **Requisition approve/reject says why it was refused** (live report 2026-10-12: Kenneth
  clicked Approve on a requisition he created and "nothing happened"): the approval
  workflow never lets a requester decide their own request (`is_eligible_approver`; only
  superadmin is exempt), the API returned 403, and `approveReq` swallowed it. Now
  `reqActionFailed()` (recruitment.js) alerts the server's message for submit/approve/close;
  `approve_requisition` answers "You can't approve or reject a requisition you created
  yourself"; `GET /api/recruitment/requisitions/{id}` carries `own_request_blocked`, which
  hides the Approve/Reject block for the requester. Still open: a step whose approver has no
  login account (e.g. a direct manager with no user) can never be cleared by anyone but a
  superadmin — not auto-skipped, not warned about when the rule is set up.
- **Job Requisitions list shows "Pending with …" under a Pending Approval status**
  (`list_requisitions` → `annotate_actionability(..., always_describe=True)`,
  `loadRequisitions` in recruitment.js): the same `pending_with` / `approval_progress`
  the leave/claims/etc. screens use, e.g. "Davent Low (Direct Manager), HR Manager (0/2
  approved)" for a flat workflow. `always_describe` is new — by default the label only
  appears when the viewer *isn't* an eligible approver; here HR wants it regardless, to
  follow up. A requisition whose creator has no linked employee record gets no label
  (the requester can't be resolved).
- **Policy acknowledgements** (L&D → Course Catalog → **Policies** filter; `routers/policies.py`,
  `core/policies.py`, `20261013_0001`, Policies section in `static/js/ld.js`, `policyPublishModal` /
  `policyTrackerModal` / `policyReadModal` in index.html) — HR publishes a PDF/Word/PowerPoint
  (handbook, memo, code of conduct); each assigned employee opens it and ticks "I have read and
  understood …" to acknowledge. A policy is an `ld_courses` row with category `policy` (hidden from
  `/api/ld/courses` unless `category=policy` or `include_policies=true`; can't be enrolled in, edited
  as a course, or given lessons — those endpoints 400); each **version** is a `policy_versions` row
  (file in `ld_module_files`, `due_date`, `require_open`, audience) and each person has one
  `policy_acknowledgements` row per version (`first_opened_at`, `acknowledged_at`, the exact
  `statement`). Publishing a new version re-asks the audience; old versions and who acknowledged them
  stay (tracker has a version picker). Audience types: all active employees / a department / a
  manager's whole reporting chain / named people — resolved **once at publish**; decided with the
  owner (2026-10-13) that people who join later are **not** auto-assigned: the tracker shows an
  "N not assigned yet" hint with Add them, plus Add a person, and an onboarding/offboarding template
  item linked to a policy (the existing `linked_ld_course_id`, picker now lists policies) assigns the
  current version when the checklist starts and is auto-completed when it's acknowledged
  (`auto_enroll_ld_course` branches on category; `complete_linked_ob_items` is called on acknowledge).
  Acknowledging needs the box ticked, the **current** version, and — per policy, default on — the
  document opened first (`GET .../versions/{id}/file` stamps `first_opened_at` for the assignee; HR and
  managers can open any policy without that). It is a recorded click with the account and time, not a
  legal e-signature. Visibility: HR (`learning_development.manage_courses_quizzes`) sees everyone and
  publishes; a `manager` sees read-only status for their own reporting chain; others get 403.
  Employees see **My Policies** at the top of My Trainings (superseded unacknowledged versions are
  hidden) and a Home To-Do item (`policy-ack`).
  **Phase 2 — reminders and CSV** (`20261014_0001` adds `institutions.reminder_acknowledgement_hour`,
  default 9): the **automatic** sweep is `sweep_pending_policies` in `scripts/send_reminders.py`, run
  by Celery beat's `reminder_sweep_policies` (`core/tasks.py`, every 30 min like the others, gated by
  the institution's hour and the opt-in `reminder_acknowledgement_enabled` toggle — default off — on
  Settings → Notifications → Reminders). It emails each Active, unacknowledged assignee of the
  **current** version of a policy **that has a due date**, from 3 days before it (`REMIND_BEFORE_DUE_DAYS`)
  and then every 7 days (`AUTO_REMIND_EVERY_DAYS`) until they acknowledge; no due date = manual only.
  The **manual** "Send reminder (N)" on the tracker (`POST /api/policies/versions/{id}/remind`, HR,
  current version, needs email set up, skips anyone reminded in the last day, queued via
  `queue_email`) shares the same email-log dedupe key per person per version
  (`policy:{version_id}:{employee_id}`, category `policy_reminder`), so a manual nudge also holds off
  the next automatic one and the tracker's "Last reminded" column is just the latest log row.
  **CSV**: `GET /api/policies/{course_id}/export.csv?version_id=` (HR everyone, manager their team;
  UTF-8 with BOM, times in the company timezone, cells starting `= + - @` are neutralised by
  `csv_cell`) via the tracker's Export CSV (fetched as a blob because of the auth header).
  **Links and password confirmation** (`20261015_0001`): a policy version's document can be an
  uploaded file, a **link**, or a link **plus** a PDF copy (kept as evidence — a page behind a link can
  change after people acknowledge). `policy_versions.file_id` is now nullable (a CHECK requires a file or
  a link) and `link_url` is validated by `core.policies.clean_link_url` — **http/https only**, no
  whitespace/control characters (a `javascript:`/`data:`/`file:` link would run code or reach local files
  when clicked). Employees open a link via `POST .../versions/{id}/open-link`, which stamps
  `first_opened_at` and returns the URL (a link opened any other way can't be recorded; "must open
  first" works the same as for files). Acknowledging no longer uses a tick box: the body is
  `{"password": ...}` and the server verifies it against the caller's own login password
  (`verify_password`), rate-limited with the **login limiter** (`policy-ack:{user id}`, 5 wrong tries per
  5 minutes → 429) and answering a wrong password with **403, never 401** (the front end signs a user
  out on 401). `policy_acknowledgements.method` is `'password'`; NULL = an earlier tick-box
  acknowledgement (CSV shows "Tick box"). It is a recorded confirmation, not a certified e-signature;
  anything contractual needs a real e-signature service (not built).
- **Quiz screens show numbering and a proper result** (`ld.js`'s `openLdTakeQuizModal` / `ldQuizOutcome` /
  `submitLdQuizAttempt`, `routers/ld.py`'s `submit_quiz_attempt` and `get_course_quiz`): questions are
  numbered "1." "2." … in the order shown (also in the HR preview); the take screen opens with
  "N questions · Pass mark X% · Attempt k of M" (`attempts_used` on `GET .../quiz`); after submitting, the
  employee sees the score, "(c of t correct)", the pass mark, Passed / Not passed, and for a fail why
  (needed at least `required_correct` of `total`), which questions to review (the numbers they saw —
  `incorrect_question_ids` are ids only, **never the correct answers**; each wrong question also gets an
  "Incorrect" tag), and attempts left, with a **Retake quiz** button (reloads the quiz, so randomised
  order reshuffles) or "contact HR" when none are left. `ldQuizOutcome` is pure and unit-tested.
  Also fixed: the HR preview judged pass/fail against a hardcoded 80% instead of the quiz's own pass mark.
- **Past quiz scores are visible** (`routers/ld.py`: `_ENROLLMENT_QUIZ_COLUMNS`, `_can_see_enrollment_scores`,
  `GET /api/ld/enrollments/{id}/quiz-attempts`, `GET /api/employees/{id}/ld-courses`; `ldScoreSummary` /
  `openLdAttemptsModal` / `loadEmployeeLearning` in `static/js/ld.js`, the **Learning** tab in the employee profile
  modal, `ldAttemptsModal`): My Trainings (HR sees everyone, a manager their reporting chain, an employee their own)
  has a **Quiz Score** column — best score + Passed / Not passed + attempts used or left, "Not attempted" before the
  first try, "—" for a course with no quiz — and clicking it lists every attempt (number, date, score, result).
  `GET /api/ld/enrollments` carries `attempts_used` / `best_score` / `passed_any` / `quiz_pass_threshold` /
  `quiz_max_attempts`. The employee profile's Learning tab (HR, the employee themself, a manager for their team;
  the server applies the same rule) lists that person's courses with the same score cell. Attempts are per
  **enrolment** (a re-enrolment starts a new set). **Scores only — the answers given are never returned.** The pass
  mark shown is the quiz's current one (attempts store only score + passed), and editing a quiz leaves old attempts
  in place, scored against the old questions. Gotcha hit here: `z-[70]` isn't in the compiled tailwind.css, so a
  modal using it had no z-index and the page's sticky table header painted over it — use `z-50` (later in the DOM
  wins) or rebuild the CSS.
- **FR / external employee lookup** (`routers/fr_integration.py`, `docs/FR_INTEGRATION.md`): besides the
  roster pull there is `GET /api/integrations/fr/employees/{ems_employee_id}` (device-key auth, the key's company
  only) that returns **only** `{"display_name", "birthday"}` — `display_name` is null unless
  `consent_display_name`, `birthday` is true only when today's month/day (in the **company's timezone**,
  `core/institution_time.institution_today`; 29 Feb = 28 Feb in a non-leap year, `is_birthday`) matches
  `date_of_birth` **and** `consent_dob`. Unknown, other-company and **inactive** employees are 404. The roster rows
  carry the same `birthday` flag, and **`date_of_birth` there is null unless `consent_dob` is true** — before
  2026-10-13 the roster released every employee's date of birth regardless of consent and relied on the kiosk to
  ignore it. Employee IDs are numbered per company, so the same ID can exist in two companies; a test must compare
  the person, not just the status code, when checking tenant isolation.
- **The public (no-login) job page shows the requisition's Requirements** (live report 2026-10-13, institution 4:
  the JD showed the description only): `GET /api/public/careers/apply/{token}` always returned `requirements`, but
  `loadPublicApplyForm` (`static/js/public_careers.js`) rendered only `description`. It now shows a "Requirements"
  block under the description (plain text, `whitespace-pre-wrap`, hidden when empty). Covered by a vitest that runs
  the real function against a stubbed fetch.
- **Interviews table shows each interviewer's score and the average** (`interview_scorecards` /
  `interviewer_score` in `routers/recruitment.py`, `loadInterviews` + `interviewScoreChipsHtml` in
  `static/js/recruitment.js`): `GET /api/recruitment/interviews` now returns, per interview, `scores` (one entry per
  interviewer who scored — their account's full name, score, the four criteria, recommendation), `score_count` and
  `avg_score`. An interviewer's score is their **Overall**, or — if they left Overall blank — the average of the
  criteria they filled in; a scorecard with no numbers doesn't count. `avg_score` is the mean of those (the
  "general score"), shown as "4.2/5 · 3 scorers"; the Candidate Detail interview cards use the same helper so the
  numbers match. A re-score by the same interviewer replaces theirs.
- **Gotcha (fixed 2026-10-13): every `hidden md:table-cell` / `hidden lg:table-cell` / `hidden sm:table-cell` column
  was invisible at every width.** `styles.css`'s unlayered `.hidden{display:none}` (added 2026-09-10 so role-gated
  nav items stay hidden) beats Tailwind 4's layered responsive "show" variants, so ~50 table columns (Interviews'
  Type / Interviewers / Avg Score among them) never appeared even on a desktop. `styles.css` now re-enables the
  combinations the app uses (`.hidden.sm\:table-cell`, `.hidden.md\:table-cell`, `.hidden.lg\:table-cell`,
  `.hidden.sm\:inline`) at Tailwind's breakpoints (sm 40rem / md 48rem / lg 64rem). A new `hidden <bp>:<display>`
  combination needs its own line there.
- **Interviewers are picked from the employee list, get a Home To-Do, and score from "My Interviews"**
  (`interview_interviewers`, migration `20261016_0001`; `InterviewIn.interviewer_ids`, `_resolve_interviewers`/
  `_save_interviewers`/`interview_scorecards` and the `my-interviews` endpoints in `routers/recruitment.py`; the To-Do
  block in `routers/dashboard.py`; `is_interviewer` on `GET /api/auth/me`; `openIntModal`/`loadMyInterviews` in
  `static/js/recruitment.js`): the Schedule Interview dialog's free-text box became a searchable multi-select of **active**
  employees (chips; same dialog now also **edits** an interview — Edit button, `PUT`, candidate locked). `interviewer_ids`
  is the source of truth when sent and rebuilds `interviews.interviewers` (display text) from the names; sending none
  leaves the typed text alone (older interviews, shown as "Previously typed"). The Interviews table's scores column
  shows each picked interviewer's score or a dashed "waiting" chip (+ "(no login)" tooltip when they have no account),
  then scores from anyone not picked. **To-Do** (`interview-{id}`, kind reminder, page `my-interviews`): from the moment
  they're picked "Interview X — date time" (action View); once the interview is Completed or its time has passed and
  they haven't scored "Score X's interview" (action Score); gone once they've scored, or the interview is
  Cancelled/No-Show. **My Interviews** (nav item shown when `is_interviewer`; also revealed when a To-Do points at it) lists
  only the caller's interviews, a read-only **candidate brief** (professional background, skills, documents — never
  contact details, IC number, DOB, address, expected salary or HR notes) and their own score via the existing score
  dialog. Scoring is now gated: `POST .../scores` needs Recruitment manage permission **or** being a picked interviewer
  (it used to accept any logged-in user), and `GET .../scores` returns everything to recruiters but only an
  interviewer's **own** row to them (so colleagues' scores/comments stay unseen), 403 to anyone else. A picked
  employee with no login account still appears on the interview but gets no To-Do.

## Recurring gotchas (hit more than once this project's history)

- **RLS fails closed, not open.** A table gets RLS auto-enabled by an
  `ensure_rls` event trigger the moment it's created, but with **zero**
  policies that means every query returns nothing / every insert is
  denied — not "RLS off". Every new tenant-scoped table needs an
  explicit `tenant_isolation` policy in its migration. A table with no
  `institution_id` of its own (e.g. a child table like
  `approval_workflow_steps`, `ob_item_attachments`) needs an
  EXISTS-based policy scoped through its parent.
- **`db.py`'s `Conn` wrapper translates `?` placeholders to psycopg2's
  `%s`.** Never use a raw `%` wildcard directly in a `LIKE`/`ILIKE`
  pattern string passed through `.execute()` — it breaks the
  translation (`IndexError: tuple index out of range`). Fetch rows and
  filter in Python instead, or pass the wildcard pre-built into the bind
  parameter, not the SQL string.
- **Imports are flat (`from core.deps import ...`), not `ems.`-prefixed.**
  Every router used to carry a `try: from core.X import Y / except
  ImportError: from ems.X import Y` fallback, for a second invocation mode
  (running from the *parent* of this repo, so `ems/` resolves as a
  package) that turned out to be unused by anything real — production
  (`Dockerfile`/`deploy.sh`), local preview (`.claude/launch.json`, via
  `--app-dir`), and `celery_worker.py`'s own documented usage all already
  ran the flat path. Removed in full across 34 files (139 blocks) after
  confirming this; the root `__init__.py` that made the `ems.` package
  mode possible was removed too. Don't reintroduce the dual-import
  pattern in new files — if a second invocation mode is ever genuinely
  needed again, resolve it once at process start (e.g. `sys.path`/
  `sys.modules` aliasing in `main.py`), not per-file.
- **Almost nothing in this stack runs on a schedule.** Anything that looks
  like it needs one (leave carry-forward expiry, attendance absence
  detection, overtime detection) is instead computed **lazily on
  read/use** or triggered by an adjacent action (timesheet submission
  triggers overtime detection, not a nightly job). The one deliberate
  exception is the email reminder sweeps (`core/tasks.py`'s
  `beat_schedule` — overdue checklists, pending timesheets, holiday-eve
  emails), which run on Celery beat as the Fly "reminders" process group
  (`fly.toml`), always-on rather than stop/started. Beat fires each sweep
  inline with no Redis/worker needed, since production runs Celery in
  eager mode (`CELERY_TASK_ALWAYS_EAGER`, see `core/tasks.py` and
  README.md's Async Operations section) — `.apply_async()` never touches
  a real broker. Adding another scheduled task is one more
  `beat_schedule` entry, not new Fly infra. beat itself only ticks every
  30 minutes in UTC — it has no supported way to hot-reload a schedule
  from the DB, so the *real*, per-institution, per-category hour
  (Settings -> Notifications -> Reminders tab, `institutions.
  reminder_<category>_hour`) is checked inside each task against that
  institution's own `timezone` column (`core/tasks.py`'s
  `_reminder_category_due_now`). The timesheet sweep additionally has a
  configurable `reminder_timesheet_day_of_week` (0=Monday..6=Sunday,
  since it's weekly, not daily) — "the week that just ended" is always
  computed as the most recently *completed* Monday-Sunday week relative
  to whichever day it actually fires on, not the week ending on that
  day. Same "compute it, don't schedule it"
  philosophy as everything else in this bullet.
  - **The three beat-scheduled reminder sweeps silently never ran at
    all, for ~10 days** (2026-09-22, when beat replaced the old
    Fly-native schedule, through 2026-10-02, when it was reported and
    fixed) — found after a user noticed no timesheet reminder email
    that week. Each sweep did `from db import get_db, set_rls_context`
    *inside* the function body instead of at module top level; the
    "reminders" process runs `celery -A core.tasks beat` as an
    installed console-script executable, which never puts this file's
    own directory on `sys.path` the way the "app" process's `uvicorn
    main:app` does — Celery's own `-A core.tasks` loader works around
    that, but only for the instant it's actively importing
    `core/tasks.py` itself; any import inside that module's own
    top-level body rides along in that same window and resolves fine,
    but a *deferred* import inside a function body runs later, after
    Celery's loader has already restored `sys.path`, and fails with
    `ModuleNotFoundError: No module named 'db'` — every single time,
    not intermittently. Confirmed and fixed by reproducing the exact
    failure against the live "reminders" machine over SSH (replicating
    console-script sys.path behavior + Celery's `import_from_cwd`),
    then verifying the fix the same way before deploying. Fix: `from
    db import get_db, set_rls_context, IntegrityError` moved to
    `core/tasks.py`'s own top level — once `core.tasks` itself loads
    successfully (which it always did), `db` is cached in
    `sys.modules` and every later reference anywhere in the process,
    deferred or not, resolves from that cache regardless of
    `sys.path`. `generate_payroll_run`/`bulk_upload_employees_task`
    further down still defer their own `from db import` and were
    never affected by this — they only ever run via `.apply_async()`
    from the "app" process (eager mode), which already has `db`
    cached from `main.py`'s own startup import; they'd hit this exact
    same failure mode if this app ever moves off
    `CELERY_TASK_ALWAYS_EAGER` onto a real separate Celery worker
    process, worth applying the same top-level-import fix there too
    if that ever happens. General lesson: a module-local/deferred
    import anywhere that might run as (or be loaded by) a
    console-script entry point — not just `python script.py` — cannot
    assume its own directory is on `sys.path`; only an import that's
    part of the target module's own top-level body, loaded via that
    entry point's own app-loading mechanism, is safe.
- **Tests run against a local Postgres, not prod** —
  `TEST_DATABASE_URL`/`TEST_ADMIN_DATABASE_URL` in `.env`,
  `tests/conftest.py` swaps them in for `DATABASE_URL`/`ADMIN_DATABASE_URL`
  before anything else imports `db.py`/`main.py`. Falls back to running
  against prod if the `TEST_*` vars aren't set. When a new Alembic
  migration is added, apply it to the test DB too (`alembic upgrade head`
  with `ADMIN_DATABASE_URL` env-overridden to `TEST_ADMIN_DATABASE_URL`)
  — it does **not** happen automatically, `deploy.sh` only migrates prod.
  - History: originally a dedicated Supabase test *project* (separate from
    prod's Supabase project). That project's tenant became unreachable
    ("tenant/user ... not found" on both its connection strings) on
    2026-09-30, with no indication of when/whether it'd come back — replaced
    the same day with a local Postgres 17 (Homebrew `postgresql@17`, kept on
    **port 5433**, not 5432, so it doesn't collide with another Postgres
    instance/project already using the default port) — a `TEST_DATABASE_URL`
    pointing at `localhost` also makes `tests/*` eligible for the "Testing
    the user's own application" exception, unlike a remote project ever
    would be. Runs noticeably faster too (no network round trip to Supabase's
    ap-northeast-2) — the full suite (1190 tests) that used to take 1-4+
    hours against Supabase now finishes in well under 30 minutes locally.
  - Provisioning note: the historical Alembic chain assumes the schema
    already exists (it grew out of the pre-Alembic `main.py init_db()`
    era) and is **not** currently replayable from a truly empty database —
    `20260717_0001_full_schema_ddl.py` itself contains ALTER statements
    against tables added by later migrations. So — same recipe as the
    original Supabase test project, adapted for a plain local Postgres:
    1. **Match `pg_dump`'s version to prod's server** (`pg_dump` refuses to
       dump from a *newer* server than itself) — prod is Postgres 17;
       Homebrew's default `postgresql@15` `pg_dump` won't work, use
       `$(brew --prefix postgresql@17)/bin/pg_dump` explicitly (`brew
       install postgresql@17` first if not already present — it doesn't
       need to be the *running* local service, just installed for its
       client binaries).
    2. `pg_dump --schema-only --no-owner --no-privileges -n public
       "$ADMIN_DATABASE_URL" > schema.sql` against **prod** (read-only,
       schema only — never dump prod's data for this).
    3. Create the local `ems_test` database and an `ems_app` role
       (`LOGIN PASSWORD '...'`, no `BYPASSRLS`/`SUPERUSER` — must match
       prod's `ems_app` role shape for RLS to mean anything in tests); the
       admin role can just be your own local Postgres superuser (simpler
       than replicating prod's non-superuser-but-`BYPASSRLS` `postgres`
       role — superuser already implies bypassing RLS).
    4. In the new, still-empty `ems_test`: `DROP SCHEMA public CASCADE;`
       (a fresh database already has an empty `public` schema, which
       collides with the dump's own `CREATE SCHEMA public;`), then restore
       with a **matching-version `psql`** (`$(brew --prefix
       postgresql@17)/bin/psql -f schema.sql` — PG17's dump output starts
       with a `\restrict ...` meta-command an older `psql` won't recognize).
    5. **Recreate the `ensure_rls` event trigger by hand** —
       `rls_auto_enable()` (the function it calls) comes through the dump
       fine (it's a normal `public`-schema function), but `pg_dump -n
       public` does not carry over the event trigger itself (event triggers
       are database-level objects, not schema-scoped). Get its exact
       definition from prod first (`pg_get_functiondef`/`pg_event_trigger`
       system catalogs) rather than assuming it matches this doc verbatim.
       Skip trying to dump/recreate the *other* event triggers prod's
       `pg_event_trigger` catalog lists (`pgrst_ddl_watch`,
       `issue_pg_cron_access`, etc.) — those are Supabase-platform
       internals (PostgREST/pg_cron/pg_graphql hooks), not this app's own,
       and reference handler functions/schemas (`supabase_functions.*`)
       that don't exist on a plain local Postgres.
    6. Grant `ems_app` the same DML privileges as prod (`SELECT, INSERT,
       UPDATE, DELETE` on tables, `USAGE, SELECT, UPDATE` on sequences) —
       **plus `ALTER DEFAULT PRIVILEGES`** for both, so a future migration's
       new tables don't need a manual re-grant every time.
    7. `ADMIN_DATABASE_URL="$TEST_ADMIN_DATABASE_URL" alembic stamp head`
       (schema already matches head structurally; this only writes the
       bookkeeping row — never `alembic upgrade head` from empty, it still
       fails partway through today, same as it always has:
       `eb95a484c74a`'s `depends_on` was fixed to require `20260717_0001`
       first, a real ordering bug, but that alone doesn't make the chain
       fully bootstrap-clean).
    8. **`db.py` hardcodes `sslmode="require"` for every connection** (see
       `_get_pool`/`_get_admin_pool`) — prod's Supabase Postgres always has
       SSL; a fresh local Postgres does not by default, so *every* app
       connection to it would fail otherwise. Generate a self-signed cert
       (`openssl req -new -x509 -days 3650 -nodes -out server.crt -keyout
       server.key -subj "/CN=localhost"` in the data directory, `chmod 600`
       the key), set `ssl = on` in `postgresql.conf`, restart — `require`
       mode doesn't validate the cert against a CA, so self-signed is
       sufficient.
    9. Call `core.seed.init_db_seed()` once (seeds the platform
       `superadmin` account + default OB templates — same seeding that
       runs on every real app boot) — **then fix the superadmin password**:
       the seed's actual default is `Admin@123`, but
       `tests/conftest.py`'s session-scoped `superadmin_token` fixture
       (depended on by nearly every DB-touching test file) logs in with
       `admin123` — a real, pre-existing mismatch between the seed code and
       what the test suite has always assumed, invisible until a genuinely
       fresh database exposed it. Match the test suite's expectation
       (`UPDATE users SET password_hash=..., must_change_password=0 WHERE
       role='superadmin'`, hashing `"admin123"`), not the seed's own
       default — don't "fix" this the other way by changing
       `tests/conftest.py`, since that fixture is what every other test
       file already assumes.
    10. **Guard every one-off script against the wrong database before it
        writes anything.** `tests/conftest.py`'s `TEST_DATABASE_URL` swap
        only happens *inside a pytest run*; a plain `python -c "..."` or
        `set -a && . .env && set +a && python ...` one-off does **not**
        get that swap, and `DATABASE_URL`/`ADMIN_DATABASE_URL` (prod) sit
        right next to `TEST_DATABASE_URL`/`TEST_ADMIN_DATABASE_URL` in the
        same `.env` — a script that imports `db.py`/`core.seed`/`main`
        directly (bypassing conftest.py) silently runs against **prod**
        with no error, since `DATABASE_URL` is simply already set. Any
        one-off script that's meant to touch the test DB should
        explicitly do `os.environ["DATABASE_URL"] =
        os.environ["TEST_DATABASE_URL"]` (and the admin equivalent) itself,
        immediately after `load_dotenv()` and before importing `db`/`main`
        — and assert/print the resolved host before any write, not just
        trust that the right env var was exported. This is exactly how the
        local test DB's own bootstrap went wrong the first time: a bulk
        `UPDATE ... WHERE role='superadmin'` meant for the new local
        database landed on prod's real superadmin account instead, because
        of this exact gap.
  - Re-provisioning a fresh local test DB should follow the same recipe
    (steps 1-9 above; you shouldn't need step 10's incident again if you
    follow the explicit-swap pattern it describes).
  - **Browser-testing a UI change against real data (not just pytest)**:
    the default `.claude/launch.json` "EMS" config runs `main:app` straight
    against `.env`'s plain `DATABASE_URL` (prod) — fine for a real deploy,
    wrong for poking at in-progress work through the browser. Use the
    `"EMS-test-db"` config instead (`scripts/dev_against_test_db.py`, port
    8010): it does step 10's explicit env-swap-and-assert inside the
    process itself before importing `main`, so it always starts against
    `localhost:5433`, never prod. Log in with the shared `test_institution`
    fixture's own seeded account (company code `ZZPYTEST`, username
    `zzpytest_admin`, password `ZzPytest@123` — see `tests/conftest.py`'s
    `test_institution`) rather than creating a fresh one by hand.
- **`tests/conftest.py`'s `test_institution` fixture is
  session-scoped** — created once, shared by every test in one pytest
  invocation, and never cleaned up. Data your test creates (workflows,
  checklists, projects, locations) can silently become "the first/
  default one" for later tests in the same run if you don't tear it down
  explicitly. This has caused real cross-test pollution more than once
  (thousands of leftover rows, measurable query slowdowns) — always add
  teardown (a factory fixture with `yield` + cleanup, matching
  `make_test_project`/`make_test_ob_checklist`/`make_test_location`).
  Now that tests hit an isolated test project rather than prod, a leak is
  much lower-stakes, but still adds noise/slowdown to future test runs —
  keep adding teardown.
- **`get_db()`/`get_admin_db()` (`db.py`) validate a pooled connection
  before handing it out** (`_get_live_raw`, a `SELECT 1`, discarding and
  retrying on a dead one) — Supabase's pooler can silently close an
  idle-in-pool connection, which used to surface as a random
  `psycopg2.OperationalError: server closed the connection unexpectedly`
  at an unrelated call site. Genuinely transient DB flakiness (network
  blips, not stale connections) can still happen occasionally — retry the
  specific failing test in isolation before concluding something broke;
  only real `AssertionError`s indicate an actual regression.
- **`tests/test_rls_enforcement.py::test_rls_blocks_cross_institution_row_even_without_a_where_filter`
  is a known-flaky test under the full suite** (tracked, not root-caused as
  of 2026-08-10) — passes reliably alone or in a small `-n 2` subset, but
  has intermittently failed only during a full 400+ test CI run. See its
  docstring for the leading theory (possible PgBouncer transaction-pooler
  interaction) and why the obvious next diagnostic step (a direct,
  non-pooled connection) isn't practical in CI. A real regression here
  would show up as this test failing *reliably*, not just occasionally
  under full-suite load.
  - Second instance of this same class, found **and fixed** 2026-09-30 (the
    first time the full suite got run to completion in one sitting in a
    long while — local Postgres runs the whole 1190-test suite in ~10
    minutes, where the old Supabase test project took 1-4+ hours, likely
    why a full run had never actually finished cleanly before):
    `tests/test_location_phase2.py::TestPhase2IntegrationWorkflows::test_multi_location_payroll_analysis`
    failed once on `assert body["total_employees"] >= 1` (got 0).
    Root cause: `/api/payroll/institution/{id}/summary`'s employee_count is
    `COUNT(DISTINCT ps.employee_id)` through a join to `payslips`, but the
    test never created a payroll run/payslip for its own employee — it only
    ever passed because `test_institution` is looked up by a fixed code and
    reused *permanently across every pytest run ever* (see its own docstring
    in `tests/conftest.py`), so on the years-old Supabase project some
    earlier `test_payroll.py` run had always already left a payslip behind
    by the time this test ran; on a genuinely fresh database this test's
    file happens to collect alphabetically before `test_payroll.py`, so
    nothing had run yet. Fixed by having the test create its own payroll
    run (a real `POST /api/payroll/runs`, random far-future period to stay
    collision-free) instead of relying on incidental state elsewhere —
    confirmed by re-provisioning the local test DB from scratch and running
    the full suite again: 1188 passed, 2 skipped, 0 failed.
- **Bash tool's cwd resets between calls** — always use absolute paths
  or prefix `cd /path/to/ems &&`.
- **`fly deploy` does not run migrations on its own** — use `./deploy.sh`
  (repo root) instead of calling `fly deploy` directly; it runs `alembic
  upgrade head` against the shared DB first, then deploys, then curl-
  verifies `/` returns 200. This exists so a migration can never ship
  silently un-applied.
- **VACUUM requires the admin DB connection**, not the app's normal
  `DATABASE_URL` role (`permission denied to vacuum ..., skipping it`).
  Use `ADMIN_DATABASE_URL` via a direct `psycopg2.connect(...)` for any
  one-off `VACUUM FULL` after a large `DELETE` (a `DELETE` doesn't
  reclaim disk space on its own — a bulk cleanup can leave a table
  physically huge despite few live rows, which shows up as inflated
  query-planner costs / real slow scans until vacuumed).

## Workflow expectations for this project

- **Never commit, push, or deploy without being explicitly told to.**
  Implement → verify (tests and/or browser) → wait for an explicit
  instruction like "commit and push and deploy".
- Deploys are `./deploy.sh` (runs pending migrations, then
  `fly deploy --app ems-app`, then verifies `https://ems-app.fly.dev/`
  returns `200`).
- For any non-trivial feature request, research the current
  implementation and present a plan (and ask clarifying questions where
  the request is ambiguous) before writing code — this project's owner
  consistently prefers that over guessing.

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentUser = null, meta = {}, employees = [], orgData = [], users = [], institutions = [], rolesCache = [];
let currentInstitution = null;
let currentEmpId = null, viewingId = null, editingUserId = null, personalEditMode = false;
let currentTab = 'personal';
let openGroups = new Set(['empMgmt']);
const TABS = ['personal','employment','statutory','dependents'];
const VIEW_TABS = ['vt-personal','vt-employment','vt-locations','vt-statutory','vt-compensation','vt-notes','vt-documents','vt-consent'];
// Shared role-tier constants for the `.includes(role)` checks that gate nav
// visibility and per-page "can manage" toggles across the app. Extracted
// because the same role sets were previously hand-typed as inline array
// literals independently in many files — 60+ occurrences, most of them
// byte-identical — which meant fixing one code+role wart didn't fix its
// copies anywhere else. Each constant here is named for the role tier it
// represents, not any one caller, since the same tier gets reused for many
// unrelated features. Only sets that were actually duplicated somewhere are
// listed — a role combination used in exactly one place stays as a plain
// inline array there.
const HR_MANAGE_ROLES = ['superadmin','hr_manager','hr_admin'];
const HR_AND_MANAGER_ROLES = ['superadmin','hr_manager','hr_admin','manager'];
const HR_STAFF_ROLES = ['hr_manager','hr_admin'];                  // no superadmin
const HR_MANAGER_ONLY_ROLES = ['superadmin','hr_manager'];         // no hr_admin
const COMPENSATION_STAFF_ROLES = ['hr_manager','payroll_manager','compensation_manager'];
const BENEFITS_DASHBOARD_ROLES = ['hr_manager','compensation_manager','manager'];
const ALL_PAGES = ['dashboard','institutions','employees','orgchart','audit','users','requisitions','candidates','interviews','offers','onboarding','offboarding','ld-catalog','ld-trainings','leave-my','leave-approvals','leave-holidays','resignation-approvals','projects','timesheet-my','timesheet-approvals','overtime-my','settings-notifications','settings-system-notifications','settings-bulk-upload','settings-locations','comp-paygrades','comp-joblevels','comp-jobroles','comp-meritcycles','comp-bonusplans','comp-commissions','comp-equity','comp-totalrewards','comp-payequity','ben-plans','ben-periods','ben-lifeevents','ben-claims','ben-compliance','payroll-runs','payroll-my','payroll-myrewards','payroll-mybenefits','perf-my','perf-team','perf-cycles','perf-calibration','attendance-clock','attendance-review','settings-attendance','settings-approval-workflow','settings-roles','settings-document-types','settings-offer-letter-templates','settings-performance','settings-ai-assistant','coming-soon'];

// ---------------------------------------------------------------------------
// Lazy module loading (Speed Audit item 7)
// ---------------------------------------------------------------------------
// scripts/lazy-modules.js's 11 files (HR/superadmin-only screens with no
// employee-facing self-service half — Recruitment, Onboarding/Offboarding,
// Audit Log, Users, Institutions, and several Settings pages) are built as
// separate minified files under static/js/modules/ instead of being
// concatenated into app.bundle.js, so a plain employee or manager never
// downloads or parses them at all. Each is fetched only the first time it's
// actually needed, then cached (module-scoped promise, not just a boolean,
// so two near-simultaneous callers share the one in-flight request).
//
// Versioned with the same content-hash query string as app.bundle.js
// itself: read directly off that <script> tag's own src, since the
// server's cache-busting ?v= substitution (routers/frontend.py) only
// rewrites index.html's own text — a tag created here at runtime has to
// carry the hash itself.
const _assetVersion = (document.currentScript && document.currentScript.src.split('?v=')[1]) || '';
const _loadedModules = {};
function ensureModuleLoaded(name) {
  if (_loadedModules[name]) return _loadedModules[name];
  _loadedModules[name] = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `/static/js/modules/${name}.js${_assetVersion ? '?v=' + _assetVersion : ''}`;
    s.onload = () => resolve();
    s.onerror = () => { delete _loadedModules[name]; reject(new Error(`Failed to load module: ${name}`)); };
    document.body.appendChild(s);
  });
  return _loadedModules[name];
}

// page -> lazy module name, for showPage()'s dispatch below. A page not
// listed here needs no lazy module (either it's core, or it's one of the
// mixed employee/HR files that stays eager — see lazy-modules.js's own
// comment on why those aren't split).
const LAZY_PAGE_MODULES = {
  audit: 'audit', users: 'users', institutions: 'institutions',
  requisitions: 'recruitment', candidates: 'recruitment', interviews: 'recruitment', offers: 'recruitment',
  'settings-offer-letter-templates': 'recruitment',
  onboarding: 'onboarding', offboarding: 'onboarding',
  'settings-bulk-upload': 'bulk-upload',
  'settings-locations': 'locations',
  'settings-approval-workflow': 'approval-workflow',
  'settings-roles': 'roles',
  'settings-document-types': 'employee-documents',
  'settings-ai-assistant': 'ai-assistant-settings',
  // 'email-notification-settings' is no longer a page-level lazy module —
  // it's now the SMTP Settings tab inside 'settings-notifications', loaded
  // on demand by switchNotifTab() (static/js/notifications.js) the first
  // time that tab is opened, not by this page-routing dispatch.
};

// Lives here rather than in approval-workflow.js (where the rest of this
// domain's logic sits) because Leave's and Benefits' own Apply/Submit
// forms call it directly, off the critical path of ever opening the
// (HR-only, lazy-loaded) Approval Workflow settings page — moving
// approval-workflow.js to lazy-load-only would otherwise have left this
// permanently undefined for a plain employee filing routine leave/claims.
// Decides whether to show those forms' Project picker: the applicable
// (default) workflow for the module has to actually have a
// project_manager step configured, primary or alt.
async function moduleHasProjectManagerStep(module) {
  const res = await api(`/api/approval-workflows?module=${module}`);
  if (!res?.ok) return false;
  const workflows = await res.json();
  const wf = workflows.find(w => w.is_default) || workflows[0];
  if (!wf) return false;
  return wf.steps.some(s => s.approver_type === 'project_manager' || s.alt_approver_type === 'project_manager');
}

// ---------------------------------------------------------------------------
// Global loading indicator
// ---------------------------------------------------------------------------
// A counter, not a boolean, because pages routinely fire several api() calls
// at once (Promise.all) — the bar must stay visible until the LAST of them
// settles, not disappear when the first one happens to finish.
let pendingRequestCount = 0;
function showGlobalLoading() {
  pendingRequestCount++;
  document.getElementById('globalLoadingBar')?.classList.remove('hidden');
}
function hideGlobalLoading() {
  pendingRequestCount = Math.max(0, pendingRequestCount - 1);
  if (pendingRequestCount === 0) {
    document.getElementById('globalLoadingBar')?.classList.add('hidden');
  }
}

// ---------------------------------------------------------------------------
// Timestamp helper
// ---------------------------------------------------------------------------
// Every *_at timestamp from the API is a naive UTC string (no "Z"/offset —
// see db.py's use of datetime.utcnow().isoformat()). Passed straight to
// `new Date(...)`, the JS Date Time String Format spec treats a date-time
// string with no zone as LOCAL time, not UTC — silently mislabeling the
// value by the browser's UTC offset (e.g. an actual 7:28pm MYT clock-in,
// stored as "11:28:27" UTC, would display as "11:28 AM" instead of "7:28
// PM"). Append "Z" first so it's parsed as the UTC instant it actually is,
// then formatting methods correctly convert to the browser's local time.
function parseUTC(value) {
  if (!value) return null;
  return new Date(value.endsWith('Z') ? value : value + 'Z');
}

// ---------------------------------------------------------------------------
// Date display: dd-mmm-yy everywhere (e.g. "15-Aug-26")
// ---------------------------------------------------------------------------
const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function fmtDate(value) {
  // Accepts a "YYYY-MM-DD..." string (parsed via regex, not `new Date()` —
  // same UTC-midnight/local-timezone trap parseUTC exists to avoid) or a
  // Date object (uses local getters, for datetime values already resolved
  // by parseUTC).
  if (!value) return '—';
  let y, mo, d;
  if (value instanceof Date) {
    if (isNaN(value)) return '—';
    y = value.getFullYear(); mo = value.getMonth() + 1; d = value.getDate();
  } else {
    const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(value); // not a recognizable date — pass through, don't mangle
    [y, mo, d] = m.slice(1).map(Number);
  }
  return `${String(d).padStart(2,'0')}-${MONTH_ABBR[mo-1]}-${String(y).slice(-2)}`;
}

function fmtDateTime(value, withSeconds) {
  // For naive-UTC *_at/timestamp fields — reuses parseUTC for correct
  // local-time conversion.
  const d = parseUTC(value);
  if (!d) return '—';
  const timeOpts = withSeconds
    ? {hour:'2-digit',minute:'2-digit',second:'2-digit'}
    : {hour:'2-digit',minute:'2-digit'};
  return `${fmtDate(d)}, ${d.toLocaleTimeString([], timeOpts)}`;
}

function fmtDuration(seconds) {
  if(seconds==null) return '—';
  if(seconds<3600) return '< 1h';
  const days=Math.floor(seconds/86400);
  const hours=Math.floor((seconds%86400)/3600);
  if(days>0) return hours>0?`${days}d ${hours}h`:`${days}d`;
  return `${hours}h`;
}

// ---------------------------------------------------------------------------
// Employee display name — used everywhere an employee is referenced outside
// the Employees List/Detail screens and official documents (payslips, bank
// export, audit records, which stay on full_name only, untouched by this).
// Shows the preferred name alone when set, otherwise falls back to the
// full (government-ID) name — never both at once.
// ---------------------------------------------------------------------------
function displayName(fullName, preferredName) {
  const full = (fullName || '').trim();
  const pref = (preferredName || '').trim();
  return pref || full;
}

// Employees List table row only — shows both names together, since that
// screen is where full_name/preferred_name are captured and cross-checked.
// Everywhere else uses displayName() (preferred name alone, or full name).
function combinedName(fullName, preferredName) {
  const full = (fullName || '').trim();
  const pref = (preferredName || '').trim();
  if (pref && pref.toLowerCase() !== full.toLowerCase()) return `${full} (${pref})`;
  return full;
}

// A row's "who's still holding this up" label, for any module wired into
// core/approval_workflow.py's annotate_actionability. Sequential rows
// (approval_progress null) show just the plain label, exactly as before
// this existed; a flat-mode row (see approval_workflows.mode) also shows
// how many of its steps have already cleared, e.g. "Direct Manager, HR
// Manager (1/2 approved)" — every step in pending_with's list is still
// open, so the label always lists what's outstanding, not what's done.
function pendingWithLabel(row) {
  const label = row.pending_with || '—';
  if (!row.approval_progress) return esc(label);
  const {decided, total} = row.approval_progress;
  return `${esc(label)} (${decided}/${total} approved)`;
}

// ---------------------------------------------------------------------------
// Currency display: "RM 1,234.56" everywhere (was 3 implementations —
// fmtRM in benefits.js, fmtMoney in payroll.js, ~40 inline
// Number(x).toLocaleString('en-MY', {...}) calls — each with slightly
// different null handling, locale, and decimal-count behavior).
// ---------------------------------------------------------------------------
function fmtCurrency(v, decimals = 2) {
  if (v == null || v === '') return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  return `RM ${n.toLocaleString('en-MY', {minimumFractionDigits: decimals, maximumFractionDigits: decimals})}`;
}

// ---------------------------------------------------------------------------
// Double-submit guard
// ---------------------------------------------------------------------------
// Central "busy button" mechanism: while a request that WRITES to the backend
// (any non-GET api() call) is in flight, the button the user just clicked is
// disabled and greyed out (.is-busy, see styles.css), so a second click or a
// double-Enter can't fire a second request — which for most creates would
// silently insert a duplicate row (reported for Add Candidate / Add
// Dependent; the same shape applies almost everywhere a button posts).
//
// How it finds the button without touching ~180 inline onclick handlers:
// a capture-phase click/submit listener (below) remembers the last clicked
// button; api() acquires it for the duration of any non-GET request, and
// guardAsync() acquires it for a wrapped handler's whole run (covering
// handlers that await something — geolocation, a confirm follow-up — before
// their first api() call). Acquisition is ref-counted per button, and release
// waits a short grace period, so a handler that makes several sequential
// requests keeps its button disabled throughout instead of flickering.
//
// Opt-outs: `data-no-busy` on a button, buttons inside the nav sidebar, and
// `api(path, {noBusy:true})` for get-or-create style POSTs that fire on page
// load rather than from a click.
const _BUSY_RELEASE_GRACE_MS = 150;
const _busyState = new Map();
let _lastClickBtn = null, _lastClickAt = 0;

function _isGuardableButton(el) {
  return !!el && el.isConnected && !el.hasAttribute('data-no-busy') && !el.closest('nav, .app-sidebar');
}
function _rememberClick(btn) { _lastClickBtn = btn || null; _lastClickAt = Date.now(); }
function _recentClickButton(maxAgeMs) {
  return (_lastClickBtn && Date.now() - _lastClickAt <= maxAgeMs && _isGuardableButton(_lastClickBtn))
    ? _lastClickBtn : null;
}

// Disables `btn` (ref-counted) and returns an idempotent release function.
function busyAcquire(btn) {
  if (!btn) return () => {};
  let st = _busyState.get(btn);
  if (!st) { st = { n: 0, wasDisabled: btn.disabled, timer: null }; _busyState.set(btn, st); }
  clearTimeout(st.timer); st.timer = null;
  st.n++;
  btn.disabled = true;
  btn.classList.add('is-busy');
  btn.setAttribute('aria-busy', 'true');
  let released = false;
  return () => {
    if (released) return;
    released = true;
    st.n--;
    if (st.n > 0) return;
    st.timer = setTimeout(() => {
      if (st.n > 0) return;
      _busyState.delete(btn);
      btn.classList.remove('is-busy');
      btn.removeAttribute('aria-busy');
      if (!st.wasDisabled) btn.disabled = false;
    }, _BUSY_RELEASE_GRACE_MS);
  };
}

document.addEventListener('click', (e) => {
  const btn = e.target?.closest?.('button, input[type="submit"], input[type="button"]');
  if (!btn) return;
  if (btn.classList.contains('is-busy')) { e.preventDefault(); e.stopImmediatePropagation(); return; }
  _rememberClick(btn);
}, true);

// Delegated (not per-form) so it also covers forms whose handler lives in a
// lazily-loaded module — the old boot-time installSubmitGuards() looked handlers
// up by name on window at startup, found nothing for those, and silently
// skipped them (including Add Candidate, the form it was written for).
document.addEventListener('submit', (e) => {
  const form = e.target;
  const btn = e.submitter || form?.querySelector?.('button[type="submit"]');
  if (btn?.classList?.contains('is-busy')) { e.preventDefault(); e.stopImmediatePropagation(); return; }
  if (btn) _rememberClick(btn);
}, true);

// Wraps a Save/Add/Create handler: a call while one is already in flight is a
// silent no-op (keyed per wrapped function, not per argument — e.g.
// saveObTemplateSet('onboarding') and ('offboarding') share one guard), and
// the clicked button stays disabled for the handler's whole run.
function _guardAsyncButton(evt) {
  if (!evt || typeof evt.preventDefault !== 'function' || !evt.target) return null;
  if (evt.target.tagName === 'BUTTON') return evt.target;
  if (evt.target.tagName === 'FORM') return evt.target.querySelector('button[type="submit"]');
  return null;
}
function guardAsync(fn) {
  let inFlight = false;
  return async function guarded(...args) {
    if (inFlight) return;
    inFlight = true;
    const release = busyAcquire(_guardAsyncButton(args[0]) || _recentClickButton(1000));
    try {
      return await fn.apply(this, args);
    } finally {
      inFlight = false;
      release();
    }
  };
}

// Replaces 31 hand-written `function closeXModal() { document.getElementById
// ('xModal').classList.add('hidden'); [someTrackingVar = null;] }` copies —
// unlike the matching openXModal() functions (which genuinely vary per
// modal: populating dropdowns, formatting detail views — see
// docs/adr/0001-no-generic-table-row-renderer.md for why that variation
// isn't worth abstracting), the close side is always just "hide the
// element" plus an optional single reset. resetFn covers that reset case.
function closeModal(id, resetFn) {
  document.getElementById(id)?.classList.add('hidden');
  resetFn?.();
}

// Replaces the `X_STATUS_COLORS[value] || fallback` idiom hand-copied at 23
// call sites across 10 files (16 separate *_COLORS map objects — kept
// decentralized per-module since each domain's statuses are genuinely
// different data, not duplicated logic; see
// docs/adr/0001-no-generic-table-row-renderer.md for the same reasoning
// applied to row markup). This closes the actual bug the duplication
// caused: 6 of those 23 sites had a dropped or hollowed-out fallback —
// notifications.js had 2 with no `||fallback` at all, so an unrecognized
// status rendered the literal string "undefined" as a CSS class;
// performance.js/payroll.js had 4 more using `||''`, silently rendering an
// unstyled badge — because re-typing the same fallback string by hand at
// every call site is exactly the kind of thing that's easy to skip once
// and never notice.
function statusColor(map, value, fallback = 'status-neutral') {
  return map[value] || fallback;
}

// Unlike the *_COLORS maps above (kept one-per-module on purpose — each
// domain's statuses are genuinely different data), a role name maps to
// exactly one color regardless of which page is asking: onboarding.js's
// assigned-role badge and users.js's user-role badge were each hand-
// rolling their own near-identical map (independently drifted on
// employee/compensation_manager's color) instead of sharing this. users.js
// additionally had a hollowed-out `||''` fallback instead of statusColor()'s
// safe default — any per-institution custom role (core/roles.py) not in
// the hardcoded list rendered with no badge styling at all. Built-in roles
// only; a custom role falls through to statusColor()'s neutral default.
const ROLE_BADGE_COLORS = {
  superadmin: 'bg-purple-100 text-purple-700',
  hr_manager: 'bg-blue-100 text-blue-700',
  hr_admin: 'bg-cyan-100 text-cyan-700',
  manager: 'bg-amber-100 text-amber-700',
  payroll_manager: 'bg-emerald-100 text-emerald-700',
  compensation_manager: 'bg-pink-100 text-pink-700',
  employee: 'bg-slate-100 text-slate-600',
};

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
async function api(path, opts = {}) {
  const token = localStorage.getItem('token');
  const headers = {
    ...(token ? {Authorization: `Bearer ${token}`} : {}),
    ...(currentInstitution && currentUser?.role === 'superadmin'
        ? {'X-Institution-Id': String(currentInstitution.id)} : {}),
    ...(opts.headers || {}),
  };
  if (opts.body && typeof opts.body === 'string' && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const { noBusy, ...fetchOpts } = opts;
  const isWrite = !!fetchOpts.method && fetchOpts.method.toUpperCase() !== 'GET';
  const releaseBusy = (isWrite && !noBusy) ? busyAcquire(_recentClickButton(2000)) : () => {};
  showGlobalLoading();
  try {
    const res = await fetch(path, {...fetchOpts, headers});
    if (res.status === 401) { doLogout(); return null; }
    return res;
  } finally {
    hideGlobalLoading();
    releaseBusy();
  }
}

// FastAPI's `detail` is a plain string for a manually-raised HTTPException,
// but a Pydantic field_validator failure (422) instead sends an array of
// {loc, msg, type} objects — rendering that directly (e.g. `err.textContent
// = d.detail`) shows "[object Object]" rather than the actual message.
function apiErrorText(detail, fallback = 'Failed') {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // Pydantic prefixes a field_validator's plain `raise ValueError(msg)`
    // with "Value error, " — redundant in a form's inline error text.
    return detail.map(e => (e.msg || JSON.stringify(e)).replace(/^Value error,\s*/, '')).join('; ');
  }
  return fallback;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
async function doLogin(e) {
  e.preventDefault();
  const err = document.getElementById('loginErr');
  err.classList.add('hidden');
  showGlobalLoading();
  try {
    const res = await fetch('/api/auth/login', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        username: document.getElementById('loginUser').value.trim(),
        password: document.getElementById('loginPass').value,
        institution_code: document.getElementById('loginCode').value.trim() || null,
      })
    });
    const data = await res.json();
    if (!res.ok) { err.textContent = data.detail || 'Login failed'; err.classList.remove('hidden'); return; }
    localStorage.setItem('token', data.access_token);
    currentUser = data.user;
    bootApp();
  } finally {
    hideGlobalLoading();
  }
}

function doLogout() {
  localStorage.removeItem('token');
  currentUser = null; currentInstitution = null;
  document.getElementById('loginScreen').classList.remove('hidden');
  document.getElementById('appShell').classList.add('hidden');
  document.getElementById('loginPass').value = '';
  // AI assistant chat history (static/js/assistant.js) is in-memory-only and
  // was never cleared on logout — a same-tab logout/login as a different
  // employee could still see the previous employee's chat content (data
  // privacy). initAssistant() also resets this on the next login as a
  // second line of defense, but clear it here too so it's gone immediately.
  resetAssistant();
}

function toggleRoleSwitcher() {
  document.getElementById('roleSwitcherMenu').classList.toggle('hidden');
}
document.addEventListener('click', e=>{
  if(!document.getElementById('roleSwitcherWrap')?.contains(e.target))
    document.getElementById('roleSwitcherMenu')?.classList.add('hidden');
});
async function switchRole(role) {
  document.getElementById('roleSwitcherMenu').classList.add('hidden');
  const res=await api('/api/auth/switch-role',{method:'POST',body:JSON.stringify({role})});
  if(!res||!res.ok) return;
  const data=await res.json();
  localStorage.setItem('token',data.access_token);
  currentUser=data.user;
  // employees[] is role-scoped server-side (list_employees()'s manager
  // recursive-reporting-chain vs. full-institution rows) and was only
  // fetched once at bootApp() time — without refetching here it stays
  // stuck at the old role's rows after switching (e.g. switching
  // manager->hr_manager wouldn't reveal the rows the manager view had
  // filtered out until a full page reload).
  await loadEmployees();
  applyRoleUI();
  updateSidebarUser();
  showPage('dashboard');
}

// Built-in + this institution's custom roles (see routers/roles.py) — the
// single source of truth for role dropdowns (User form, onboarding/
// offboarding assigned-role selects), replacing what used to be
// meta.institution_roles' static list.
async function loadRolesCache() {
  const res = await api('/api/roles');
  rolesCache = res?.ok ? await res.json() : [];
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function bootApp() {
  document.getElementById('loginScreen').classList.add('hidden');
  document.getElementById('appShell').classList.remove('hidden');
  // meta, roles, and (for a regular login) the employee roster are three
  // independent fetches with no dependency on each other — firing them
  // together instead of one after another removes up to two round-trip
  // latencies from the critical path before the user sees their own
  // screen, while keeping the exact same guarantee downstream code relies
  // on (employees[] fully populated before showPage('dashboard') runs).
  // The superadmin/no-institution landing skips the roster fetch — it
  // goes to the institution list instead, via loadInstitutions() below,
  // which itself stays sequential since it only makes sense once we know
  // there's no institution context yet.
  const isSuperadminLanding = currentUser.role === 'superadmin' && !currentInstitution;
  const [mr] = await Promise.all([
    api('/api/meta'),
    loadRolesCache(),
    isSuperadminLanding ? Promise.resolve() : loadEmployees(),
  ]);
  if (mr) meta = await mr.json();
  populateMetaSelects();
  applyRoleUI();
  updateSidebarUser();
  initAssistant();
  document.getElementById('headerDate').textContent =
    `${new Date().toLocaleDateString('en-MY',{weekday:'short'})}, ${fmtDate(new Date())}`;
  if (isSuperadminLanding) {
    await ensureModuleLoaded('institutions'); // institutions.js is lazy-loaded (Speed Audit item 7); loadInstitutions() below needs it, and runs before showPage('institutions') would otherwise trigger the same load
    await loadInstitutions();
    showPage('institutions');
  } else {
    showPage('dashboard');
  }
  if (currentUser.must_change_password) openChangePasswordModal(true);
}

// ---------------------------------------------------------------------------
// Change Password
// ---------------------------------------------------------------------------
function openChangePasswordModal(forced) {
  document.getElementById('cpCurrent').value = '';
  document.getElementById('cpNew').value = '';
  document.getElementById('cpConfirm').value = '';
  document.getElementById('changePasswordErr').classList.add('hidden');
  document.getElementById('changePasswordForcedNote').classList.toggle('hidden', !forced);
  document.getElementById('changePasswordCloseBtn').classList.toggle('hidden', !!forced);
  document.getElementById('changePasswordCancelBtn').classList.toggle('hidden', !!forced);
  document.getElementById('changePasswordModal').classList.remove('hidden');
}
function closeChangePasswordModal() {
  if (currentUser?.must_change_password) return; // forced — cannot be dismissed
  document.getElementById('changePasswordModal').classList.add('hidden');
}
async function submitChangePassword(e) {
  e.preventDefault();
  const err = document.getElementById('changePasswordErr');
  err.classList.add('hidden');
  const current = document.getElementById('cpCurrent').value;
  const next = document.getElementById('cpNew').value;
  const confirm = document.getElementById('cpConfirm').value;
  if (next !== confirm) {
    err.textContent = 'New password and confirmation do not match.';
    err.classList.remove('hidden');
    return;
  }
  const res = await api('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({current_password: current, new_password: next}),
  });
  if (!res || !res.ok) {
    const d = await res?.json();
    err.textContent = d?.detail || 'Failed to change password';
    err.classList.remove('hidden');
    return;
  }
  // A password change now invalidates every previously-issued token
  // server-side (see routers/auth.py's change_password) — including this
  // page's own, mid-request — so the response carries a fresh one to swap
  // in. Without this, the very next api() call would 401 and force an
  // unexpected logout right after a successful change.
  const data = await res.json();
  localStorage.setItem('token', data.access_token);
  currentUser = data.user;
  document.getElementById('changePasswordModal').classList.add('hidden');
}

function updateBrandHeader() {
  const inst = currentUser?.role === 'superadmin' ? currentInstitution : currentUser?.institution;
  const logoImg = document.getElementById('brandLogoImg');
  const logoDefault = document.getElementById('brandLogoDefault');
  const nameEl = document.getElementById('brandName');
  const name = inst ? inst.name : 'EMS Platform';
  nameEl.textContent = name;
  // Rail is icon-only — surface the institution name as a tooltip on the logo instead of visible text.
  logoImg.title = name; logoDefault.title = name;
  logoImg.parentElement.title = name;
  if (inst && inst.logo_url) {
    logoImg.src = inst.logo_url;
    logoImg.classList.remove('hidden');
    logoDefault.classList.add('hidden');
  } else {
    logoImg.classList.add('hidden');
    logoDefault.classList.remove('hidden');
  }
}

function applyRoleUI() {
  const role = currentUser?.role;
  const isSA = role === 'superadmin';
  const canManage = HR_MANAGE_ROLES.includes(role);
  const canAudit  = HR_MANAGER_ONLY_ROLES.includes(role);
  const canUsers  = HR_MANAGER_ONLY_ROLES.includes(role);
  const hideEmp = isSA && !currentInstitution;

  updateBrandHeader();
  // Non-superadmin logins land on a personal landing page (their own
  // to-dos, shortcuts), not an org-wide dashboard — "Home" reads more
  // accurately for them than "Dashboard" (which stays as-is for
  // superadmin, whose view is a genuine institution/platform overview).
  const dashLabel = isSA ? 'Dashboard' : 'Home';
  document.getElementById('navDashboardBtn')?.setAttribute('title', dashLabel);
  const navDashboardLabelEl = document.getElementById('navDashboardLabel');
  if (navDashboardLabelEl) navDashboardLabelEl.textContent = dashLabel;
  document.getElementById('nav-institutions-wrap').classList.toggle('hidden', !isSA);
  document.getElementById('nav-sysnotif-wrap')?.classList.toggle('hidden', !isSA);
  document.getElementById('nav-emp-group').classList.toggle('hidden', hideEmp);
  // Workforce's own rail button is visible to anyone who can see at least
  // one of its three sub-items (HR sees all three; a plain manager sees
  // only Resignation, for their own reports' requests) — each sub-item
  // then has its own narrower toggle below, same nested pattern as Leave's
  // "Approvals" sub-item. Deliberately excludes superadmin from both: a
  // platform-level account has no employee record or direct reports of
  // its own, so Workforce (onboarding/offboarding/resignation, all
  // in-tenant employee-lifecycle actions) isn't something it manages.
  const canWorkforceOb = HR_STAFF_ROLES.includes(role);
  const canWorkforceResign = ['hr_manager', 'hr_admin', 'manager'].includes(role);
  document.getElementById('nav-workforce-group')?.classList.toggle('hidden', !canWorkforceOb && !canWorkforceResign);
  document.getElementById('nav-onboarding')?.classList.toggle('hidden', !canWorkforceOb);
  document.getElementById('nav-offboarding')?.classList.toggle('hidden', !canWorkforceOb);
  document.getElementById('nav-resignation-approvals')?.classList.toggle('hidden', !canWorkforceResign);
  document.getElementById('nav-dashboard-wrap').classList.toggle('hidden', hideEmp);
  document.getElementById('nav-audit').classList.toggle('hidden', !canAudit);
  document.getElementById('nav-users').classList.toggle('hidden', !canUsers);
  document.getElementById('addEmpBtn').classList.toggle('hidden', !canManage);
  document.getElementById('nav-recruit-group').classList.toggle('hidden', hideEmp || role === 'employee');
  document.getElementById('nav-ld-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-leave-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-leave-approvals')?.classList.toggle('hidden', !HR_AND_MANAGER_ROLES.includes(role));
  document.getElementById('nav-timesheet-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-timesheet-approvals')?.classList.toggle('hidden', !HR_AND_MANAGER_ROLES.includes(role));
  document.getElementById('nav-projects')?.classList.toggle('hidden', !HR_MANAGER_ONLY_ROLES.includes(role));
  // Clock In/Out is self-service for anyone with an employee record; the
  // employee_id-linked check happens on load (see attendance.js), the nav
  // toggle here just hides it from superadmin (no employee record at all).
  document.getElementById('nav-attendance-clock')?.classList.toggle('hidden', hideEmp || isSA);
  const canAttendanceManage = HR_MANAGE_ROLES.includes(role);
  // Attendance Review is HR_AND_MANAGER_ROLES (adds manager on top of the
  // Attendance Settings tier below) — matches the backend's
  // attendance.review_queue_resolve_attendance_record permission-matrix
  // entry, which is deliberately its own role set, not a reuse of
  // _ATTENDANCE_MANAGE (a manager reviewing their team's late/absent days
  // shouldn't also gain shift/device configuration access).
  document.getElementById('nav-attendance-review')?.classList.toggle('hidden', !HR_AND_MANAGER_ROLES.includes(role));
  const canNotify = HR_STAFF_ROLES.includes(role);
  const canBulkUpload = role === 'hr_manager';
  // Matches the backend's LOCATIONS_MANAGE_ROLES (routers/locations.py) —
  // previously excluded superadmin, which meant a superadmin couldn't even
  // see the nav entry for something the backend already let them manage.
  const canLocations = HR_MANAGE_ROLES.includes(role);
  const canApprovalWorkflow = HR_MANAGE_ROLES.includes(role);
  const canRoles = HR_MANAGE_ROLES.includes(role);
  const canDocTypes = HR_STAFF_ROLES.includes(role);
  // Narrower than the usual HR tiers above — an institution's own Anthropic
  // key is a real billing-relevant credential, hr_manager only, matching
  // routers/assistant.py's ASSISTANT_SETTINGS_ROLES exactly.
  const canAiSettings = role === 'hr_manager';
  // Same risk category/tier as canAiSettings above — matches
  // routers/notifications.py's EMAIL_SETTINGS_ROLES exactly. Gates the SMTP
  // Settings tab inside the Notifications page (below), not a separate nav
  // item anymore — an hr_admin sees the Notifications nav entry (canNotify)
  // but not that one tab.
  const canEmailSettings = role === 'hr_manager';
  document.getElementById('nav-settings-wrap')?.classList.toggle('hidden', hideEmp || !(canAudit || canUsers || canNotify || canBulkUpload || canLocations || canManage || canAttendanceManage || canApprovalWorkflow || canRoles || canDocTypes || canAiSettings));
  document.getElementById('nav-settings-notifications')?.classList.toggle('hidden', !canNotify);
  document.getElementById('notif-tab-smtp-btn')?.classList.toggle('hidden', !canEmailSettings);
  document.getElementById('nav-bulk-upload')?.classList.toggle('hidden', !canBulkUpload);
  document.getElementById('nav-locations')?.classList.toggle('hidden', !canLocations);
  // Holiday Manager is HR Manager/HR Admin-only (canManage, same tier as
  // Locations/Approval Workflows/Roles above) — moved here from the Leave
  // nav group since it's institution-wide configuration, not a personal
  // or team leave-management task like the rest of that group.
  document.getElementById('nav-leave-holidays')?.classList.toggle('hidden', !canManage);
  document.getElementById('nav-attendance-settings')?.classList.toggle('hidden', !canAttendanceManage);
  document.getElementById('nav-approval-workflow')?.classList.toggle('hidden', !canApprovalWorkflow);
  document.getElementById('nav-roles')?.classList.toggle('hidden', !canRoles);
  document.getElementById('nav-document-types')?.classList.toggle('hidden', !canDocTypes);
  document.getElementById('nav-offer-letter-templates')?.classList.toggle('hidden', !canManage);
  // hr_manager only, matching routers/performance.py's PERFORMANCE_MANAGE_ROLES
  // (every other Performance admin action in this app is gated the same way).
  document.getElementById('nav-settings-performance')?.classList.toggle('hidden', role !== 'hr_manager');
  document.getElementById('nav-ai-assistant-settings')?.classList.toggle('hidden', !canAiSettings);

  // Compensation: its own top-level menu, visible to HR Manager, Payroll
  // Manager, and the dedicated Compensation Manager role — explicitly
  // excludes HR Admin (previously included, now revoked) and superadmin
  // (unlike most other groups, which superadmin can see whenever an
  // institution is selected).
  const canCompensation = COMPENSATION_STAFF_ROLES.includes(role);
  document.getElementById('nav-compensation-group')?.classList.toggle('hidden', !canCompensation);

  // Benefits: its own top-level menu, same access gate as Compensation
  // (deliberate choice — reuse the existing role set rather than add a
  // dedicated Benefits Manager role).
  const canBenefits = COMPENSATION_STAFF_ROLES.includes(role);
  document.getElementById('nav-benefits-group')?.classList.toggle('hidden', !canBenefits);

  const canPayrollView = ['payroll_manager','hr_manager'].includes(role);
  document.getElementById('nav-payroll-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-payroll-runs')?.classList.toggle('hidden', !canPayrollView);
  document.getElementById('nav-payroll-my')?.classList.toggle('hidden', isSA);
  document.getElementById('nav-payroll-myrewards')?.classList.toggle('hidden', isSA);
  document.getElementById('nav-payroll-mybenefits')?.classList.toggle('hidden', isSA);

  document.getElementById('nav-performance-group')?.classList.toggle('hidden', hideEmp || isSA);
  document.getElementById('nav-perf-team')?.classList.toggle('hidden', !['manager','hr_manager'].includes(role));
  document.getElementById('nav-perf-cycles')?.classList.toggle('hidden', role !== 'hr_manager');
  document.getElementById('nav-perf-calibration')?.classList.toggle('hidden', role !== 'hr_manager');

  // OB buttons
  const canManageOb=HR_MANAGE_ROLES.includes(role);
  document.getElementById('startOnboardingBtn')?.classList.toggle('hidden',!canManageOb);
  document.getElementById('startOffboardingBtn')?.classList.toggle('hidden',!canManageOb);
  document.getElementById('obSubTab_onboarding_templates')?.classList.toggle('hidden',!canManageOb);
  document.getElementById('obSubTab_offboarding_templates')?.classList.toggle('hidden',!canManageOb);
  // LD buttons
  document.getElementById('ldAddCourseBtn')?.classList.toggle('hidden',!canManageOb);
  // Role switcher — show if user has more than one assigned role
  const userRoles = Array.isArray(currentUser?.roles) ? currentUser.roles : [];
  const switcher = document.getElementById('roleSwitcherWrap');
  if(userRoles.length > 1) {
    switcher.classList.remove('hidden');
    document.getElementById('roleSwitcherLabel').textContent = meta.role_labels?.[role] || role;
    document.getElementById('roleSwitcherOptions').innerHTML = userRoles.map(r=>`
      <button onclick="switchRole('${r}')" class="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex items-center justify-between gap-2 ${r===role?'font-semibold text-blue-700':'text-slate-700'}">
        ${meta.role_labels?.[r]||r}
        ${r===role?'<svg class="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg>':''}
      </button>`).join('');
  } else {
    switcher.classList.add('hidden');
  }

  const pill = document.getElementById('instContextPill');
  if (isSA && currentInstitution) {
    pill.classList.remove('hidden'); pill.classList.add('flex');
    document.getElementById('instContextName').textContent = currentInstitution.name;
  } else {
    pill.classList.add('hidden'); pill.classList.remove('flex');
  }
}

function updateSidebarUser() {
  const name = currentUser?.full_name || currentUser?.username || '?';
  const roleLabel = meta.role_labels?.[currentUser?.role] || currentUser?.role || '';
  const roleLine = currentInstitution ? `${roleLabel} · ${currentInstitution.name}` : roleLabel;
  document.getElementById('sidebarName').textContent = name;
  document.getElementById('sidebarRole').textContent = roleLine;
  const avatar = document.getElementById('avatarInitials');
  avatar.textContent = name.split(' ').slice(0,2).map(w=>w[0]||'').join('').toUpperCase() || '?';
  avatar.title = `${name} — ${roleLine}`;
}

// ---------------------------------------------------------------------------
// Institution context (superadmin switching)
// ---------------------------------------------------------------------------
async function enterInstitutionContext(inst) {
  currentInstitution = typeof inst === 'string' ? JSON.parse(inst) : inst;
  applyRoleUI();
  updateSidebarUser();
  await loadRolesCache();
  await loadEmployees();
  showPage('dashboard');
}

function clearInstitutionContext() {
  currentInstitution = null;
  employees = []; users = []; orgData = [];
  applyRoleUI();
  updateSidebarUser();
  ensureModuleLoaded('institutions').then(loadInstitutions).then(() => showPage('institutions'));
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------
async function showPage(page) {
  ALL_PAGES.forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.toggle('hidden', p !== page);
  });
  document.querySelectorAll('[data-page]').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page);
  });
  const titles = {
    dashboard: currentUser?.role === 'superadmin' ? 'Dashboard' : 'Home',
    institutions:'Institutions', employees:'Employee List',
    orgchart:'Org Chart', audit:'Audit Log', users:'User Management', 'coming-soon':'Coming Soon',
    requisitions:'Job Requisitions', candidates:'Candidate Bank', interviews:'Interviews', offers:'Stationery',
    onboarding:'Onboarding', offboarding:'Offboarding',
    'ld-catalog':'Course Catalog', 'ld-trainings':'My Trainings',
    'leave-my':'My Leave', 'leave-approvals':'Leave Approvals', 'leave-holidays':'Holiday Manager',
    'resignation-approvals':'Resignation Approvals',
    'projects':'Projects', 'timesheet-my':'My Timesheet', 'timesheet-approvals':'Timesheet Approvals', 'overtime-my':'My Overtime',
    'settings-notifications':'Settings — Notifications',
    'settings-system-notifications':'System-Wide Notifications',
    'settings-bulk-upload':'Bulk Upload Employees',
    'settings-locations':'Locations',
    'comp-paygrades':'Compensation — Pay Grades',
    'comp-joblevels':'Compensation — Job Levels',
    'comp-jobroles':'Compensation — Job Roles',
    'comp-meritcycles':'Compensation — Merit Cycles',
    'comp-bonusplans':'Compensation — Bonus Plans',
    'comp-commissions':'Compensation — Commissions',
    'comp-equity':'Compensation — Equity Grants',
    'comp-totalrewards':'Compensation — Total Rewards',
    'comp-payequity':'Compensation — Pay Equity',
    'ben-plans':'Benefits — Plan Types',
    'ben-periods':'Benefits — Enrollment Periods',
    'ben-lifeevents':'Benefits — Life Events',
    'ben-claims':'Benefits — Claims',
    'ben-compliance':'Benefits — Compliance & Reporting',
    'payroll-mybenefits':'My Benefits',
    'payroll-runs':'Payroll Runs', 'payroll-my':'My Payslips', 'payroll-myrewards':'My Total Rewards',
    'perf-my':'My Goals & Appraisal', 'perf-team':'Team Review',
    'perf-cycles':'Performance Cycles', 'perf-calibration':'Calibration',
    'attendance-clock':'Clock In / Out', 'attendance-review':'Attendance Review',
    'settings-attendance':'Settings — Attendance',
    'settings-approval-workflow':'Settings — Approval Workflows',
    'settings-roles':'Settings — Roles',
    'settings-document-types':'Settings — Document Types',
    'settings-offer-letter-templates':'Settings — Letter Templates',
    'settings-performance':'Settings — Performance',
    'settings-ai-assistant':'Settings — AI Assistant'
  };
  document.getElementById('pageTitle').textContent = titles[page] || page;
  const lazyModule = LAZY_PAGE_MODULES[page];
  if (lazyModule) {
    try { await ensureModuleLoaded(lazyModule); }
    catch (e) { console.error(e); alert('Failed to load this page — check your connection and try again.'); return; }
  }
  if (page === 'dashboard')    renderDashboard();
  if (page === 'employees')    filterEmployees();
  if (page === 'orgchart')     loadOrgChart();
  if (page === 'audit')        loadAuditLog();
  if (page === 'users')        loadUsers();
  if (page === 'institutions') renderInstTable();
  if (page === 'requisitions') loadRequisitions();
  if (page === 'candidates')   loadCandidates();
  if (page === 'interviews')   loadInterviews();
  if (page === 'offers')       loadOffers();
  if (page === 'onboarding')   loadObChecklists('onboarding');
  if (page === 'offboarding')  loadObChecklists('offboarding');
  if (page === 'ld-catalog')   loadLdCourses();
  if (page === 'ld-trainings') loadLdEnrollments();
  if (page === 'leave-my')          loadLeavePage();
  if (page === 'leave-approvals')   loadLeaveApprovals();
  if (page === 'leave-holidays')    loadLeaveHolidaysPage();
  if (page === 'resignation-approvals') loadResignationApprovals();
  if (page === 'projects')            loadProjects();
  if (page === 'timesheet-my')        loadTimesheetPage();
  if (page === 'timesheet-approvals') loadTimesheetApprovals();
  if (page === 'overtime-my')         loadMyOvertimePage();
  if (page === 'settings-notifications') { resetNotifTabs(); loadNotificationSettings(); loadNotificationGeneralSettings(); }
  if (page === 'settings-system-notifications') loadSystemNotificationSettings();
  if (page === 'payroll-runs') loadPayrollRuns();
  if (page === 'payroll-my')   loadMyPayslips();
  if (page === 'settings-bulk-upload') resetBulkUploadUI();
  if (page === 'settings-locations') loadLocations();
  if (page === 'comp-paygrades')  loadPayGrades();
  if (page === 'comp-joblevels')  loadJobLevels();
  if (page === 'comp-jobroles')   loadJobRolesPage();
  if (page === 'comp-meritcycles') loadMeritCycles();
  if (page === 'comp-bonusplans') loadBonusPlans();
  if (page === 'comp-commissions') loadCommissionPlans();
  if (page === 'comp-equity') loadEquityGrants();
  if (page === 'comp-totalrewards') loadHrTotalRewards();
  if (page === 'comp-payequity') loadPayEquityReport();
  if (page === 'ben-plans') loadBenefitPlans();
  if (page === 'ben-periods') loadEnrollmentPeriods();
  if (page === 'ben-lifeevents') loadLifeEvents();
  if (page === 'ben-claims') loadClaims();
  if (page === 'ben-compliance') loadComplianceReport();
  if (page === 'payroll-mybenefits') loadMyBenefitsPage();
  if (page === 'payroll-myrewards') loadMyTotalRewards();
  if (page === 'perf-my')          loadMyPerformancePage();
  if (page === 'perf-team')        { resetPerfTeamTabs(); loadTeamAppraisalsPage(); loadPipList(); }
  if (page === 'perf-cycles')      loadPerformanceCycles();
  if (page === 'perf-calibration') loadCalibrationPage();
  if (page === 'attendance-clock')     loadAttendanceClockPage();
  if (page === 'attendance-review')    loadAttendanceReview();
  if (page === 'settings-attendance')  loadAttendanceSettingsPage();
  if (page === 'settings-approval-workflow') loadApprovalWorkflowPage();
  if (page === 'settings-roles') loadRolesPage();
  if (page === 'settings-document-types') loadEmployeeDocTypesPage();
  if (page === 'settings-offer-letter-templates') loadOfferTemplates();
  if (page === 'settings-performance') loadProbationGoalTemplatePage();
  if (page === 'settings-ai-assistant') loadAiAssistantSettingsPage();
}

// ---------------------------------------------------------------------------

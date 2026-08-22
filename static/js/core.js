// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentUser = null, meta = {}, employees = [], orgData = [], users = [], institutions = [], rolesCache = [];
let currentInstitution = null;
let currentEmpId = null, viewingId = null, editingUserId = null;
let currentTab = 'personal';
let openGroups = new Set(['empMgmt']);
const TABS = ['personal','employment','statutory','dependents'];
const VIEW_TABS = ['vt-personal','vt-employment','vt-locations','vt-statutory','vt-compensation','vt-notes'];
const HR_NOTE_ROLES = ['superadmin','hr_manager','hr_admin'];
const ALL_PAGES = ['dashboard','institutions','employees','orgchart','audit','users','requisitions','candidates','interviews','offers','onboarding','offboarding','ld-catalog','ld-trainings','leave-my','leave-approvals','leave-holidays','resignation-approvals','projects','timesheet-my','timesheet-approvals','overtime-my','settings-notifications','settings-system-notifications','settings-bulk-upload','settings-locations','comp-paygrades','comp-joblevels','comp-jobroles','comp-meritcycles','comp-bonusplans','comp-commissions','comp-equity','comp-totalrewards','comp-payequity','ben-plans','ben-periods','ben-lifeevents','ben-claims','ben-compliance','payroll-runs','payroll-my','payroll-myrewards','payroll-mybenefits','perf-my','perf-team','perf-cycles','perf-calibration','attendance-clock','attendance-review','settings-attendance','settings-approval-workflow','settings-roles','coming-soon'];

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
// Every `<form onsubmit="submitXForm(event)">` in this app calls a bespoke
// per-form async handler with no protection against a rapid double-click or
// double-Enter re-invoking it before the first request finishes — each
// re-invocation is a real second POST, not a no-op, so it silently creates
// a duplicate row (reported for Add Candidate / Add Dependent, but the same
// shape everywhere a form posts to the API). Runs once at boot: rewrites
// every `onsubmit="fn(event)"` form to disable its own submit button for
// the duration of the async call, so a second click while one is in flight
// is a no-op instead of a second network request. New forms get this for
// free, matching the existing `onsubmit="fn(event)"` convention — no
// per-form wiring needed.
function installSubmitGuards() {
  document.querySelectorAll('form[onsubmit]').forEach(form => {
    const attr = form.getAttribute('onsubmit');
    const m = attr && attr.match(/^(\w+)\(event\)$/);
    if (!m) return;
    const fn = window[m[1]];
    if (typeof fn !== 'function') return;
    form.removeAttribute('onsubmit');
    form.addEventListener('submit', async (e) => {
      const btn = form.querySelector('button[type="submit"]');
      if (btn?.disabled) return;
      if (btn) btn.disabled = true;
      try {
        await fn(e);
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  });
}

// The onclick-wired counterpart to installSubmitGuards above: a Save/Add/
// Create button wired via onclick="fn()" instead of a form submit doesn't
// go through a <form>, so the boot-time DOM rewrite above can't reach it.
// Wrap the handler at its definition instead — replaces 31 hand-written
// `let _savingX = false; if (_savingX) return; ... try {...} finally {
// _savingX = false; }` copies (one per such button) with one shared
// wrapper. Same re-entrancy semantics as those copies: a call while one is
// already in flight is a silent no-op, keyed per wrapped function (not per
// argument), matching how e.g. saveObTemplateSet('onboarding') and
// saveObTemplateSet('offboarding') already shared one guard.
function guardAsync(fn) {
  let inFlight = false;
  return async function guarded(...args) {
    if (inFlight) return;
    inFlight = true;
    try {
      return await fn.apply(this, args);
    } finally {
      inFlight = false;
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
function statusColor(map, value, fallback = 'bg-slate-100 text-slate-600') {
  return map[value] || fallback;
}

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
  showGlobalLoading();
  try {
    const res = await fetch(path, {...opts, headers});
    if (res.status === 401) { doLogout(); return null; }
    return res;
  } finally {
    hideGlobalLoading();
  }
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
  const mr = await api('/api/meta');
  if (mr) meta = await mr.json();
  await loadRolesCache();
  populateMetaSelects();
  applyRoleUI();
  updateSidebarUser();
  initAssistant();
  document.getElementById('headerDate').textContent =
    `${new Date().toLocaleDateString('en-MY',{weekday:'short'})}, ${fmtDate(new Date())}`;
  if (currentUser.role === 'superadmin' && !currentInstitution) {
    await loadInstitutions();
    showPage('institutions');
  } else {
    await loadEmployees();
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
  if (currentUser) currentUser.must_change_password = false;
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
  const canManage = ['superadmin','hr_manager','hr_admin'].includes(role);
  const canAudit  = ['superadmin','hr_manager'].includes(role);
  const canUsers  = ['superadmin','hr_manager'].includes(role);
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
  document.getElementById('nav-workforce-group')?.classList.toggle('hidden', !['hr_manager','hr_admin'].includes(role));
  document.getElementById('nav-resignation-wrap')?.classList.toggle('hidden', !['superadmin','hr_manager','hr_admin','manager'].includes(role));
  document.getElementById('nav-dashboard-wrap').classList.toggle('hidden', hideEmp);
  document.getElementById('nav-audit').classList.toggle('hidden', !canAudit);
  document.getElementById('nav-users').classList.toggle('hidden', !canUsers);
  document.getElementById('addEmpBtn').classList.toggle('hidden', !canManage);
  document.getElementById('nav-recruit-group').classList.toggle('hidden', hideEmp);
  document.getElementById('nav-ld-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-leave-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-leave-approvals')?.classList.toggle('hidden', !['superadmin','hr_manager','hr_admin','manager'].includes(role));
  document.getElementById('nav-leave-holidays')?.classList.toggle('hidden', !canManage);
  document.getElementById('nav-timesheet-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-timesheet-approvals')?.classList.toggle('hidden', !['superadmin','hr_manager','hr_admin','manager'].includes(role));
  document.getElementById('nav-projects')?.classList.toggle('hidden', !['superadmin','hr_manager'].includes(role));
  // Clock In/Out is self-service for anyone with an employee record; the
  // employee_id-linked check happens on load (see attendance.js), the nav
  // toggle here just hides it from superadmin (no employee record at all).
  document.getElementById('nav-attendance-clock')?.classList.toggle('hidden', hideEmp || isSA);
  const canAttendanceManage = ['superadmin','hr_manager','hr_admin'].includes(role);
  document.getElementById('nav-attendance-review')?.classList.toggle('hidden', !canAttendanceManage);
  const canNotify = ['hr_manager','hr_admin'].includes(role);
  const canBulkUpload = role === 'hr_manager';
  const canLocations = ['hr_manager','hr_admin'].includes(role);
  const canApprovalWorkflow = ['superadmin','hr_manager','hr_admin'].includes(role);
  const canRoles = ['superadmin','hr_manager','hr_admin'].includes(role);
  document.getElementById('nav-settings-wrap')?.classList.toggle('hidden', hideEmp || !(canAudit || canUsers || canNotify || canBulkUpload || canLocations || canAttendanceManage || canApprovalWorkflow || canRoles));
  document.getElementById('nav-settings-notifications')?.classList.toggle('hidden', !canNotify);
  document.getElementById('nav-bulk-upload')?.classList.toggle('hidden', !canBulkUpload);
  document.getElementById('nav-locations')?.classList.toggle('hidden', !canLocations);
  document.getElementById('nav-attendance-settings')?.classList.toggle('hidden', !canAttendanceManage);
  document.getElementById('nav-approval-workflow')?.classList.toggle('hidden', !canApprovalWorkflow);
  document.getElementById('nav-roles')?.classList.toggle('hidden', !canRoles);

  // Compensation: its own top-level menu, visible to HR Manager, Payroll
  // Manager, and the dedicated Compensation Manager role — explicitly
  // excludes HR Admin (previously included, now revoked) and superadmin
  // (unlike most other groups, which superadmin can see whenever an
  // institution is selected).
  const canCompensation = ['hr_manager','payroll_manager','compensation_manager'].includes(role);
  document.getElementById('nav-compensation-group')?.classList.toggle('hidden', !canCompensation);

  // Benefits: its own top-level menu, same access gate as Compensation
  // (deliberate choice — reuse the existing role set rather than add a
  // dedicated Benefits Manager role).
  const canBenefits = ['hr_manager','payroll_manager','compensation_manager'].includes(role);
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
  const canManageOb=['superadmin','hr_manager','hr_admin'].includes(role);
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
  loadInstitutions().then(() => showPage('institutions'));
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------
function showPage(page) {
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
    requisitions:'Job Requisitions', candidates:'Candidate Bank', interviews:'Interviews', offers:'Offers & Letters',
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
    'perf-my':'My Goals & Appraisal', 'perf-team':'Team Appraisals',
    'perf-cycles':'Performance Cycles', 'perf-calibration':'Calibration',
    'attendance-clock':'Clock In / Out', 'attendance-review':'Attendance Review',
    'settings-attendance':'Settings — Attendance',
    'settings-approval-workflow':'Settings — Approval Workflows',
    'settings-roles':'Settings — Roles'
  };
  document.getElementById('pageTitle').textContent = titles[page] || page;
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
  if (page === 'settings-notifications') loadNotificationSettings();
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
  if (page === 'perf-team')        loadTeamAppraisalsPage();
  if (page === 'perf-cycles')      loadPerformanceCycles();
  if (page === 'perf-calibration') loadCalibrationPage();
  if (page === 'attendance-clock')     loadAttendanceClockPage();
  if (page === 'attendance-review')    loadAttendanceReview();
  if (page === 'settings-attendance')  loadAttendanceSettingsPage();
  if (page === 'settings-approval-workflow') loadApprovalWorkflowPage();
  if (page === 'settings-roles') loadRolesPage();
}

// ---------------------------------------------------------------------------

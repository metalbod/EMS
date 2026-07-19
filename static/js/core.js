// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentUser = null, meta = {}, employees = [], orgData = [], users = [], institutions = [];
let currentInstitution = null;
let currentEmpId = null, viewingId = null, editingUserId = null;
let currentTab = 'personal';
let openGroups = new Set(['empMgmt']);
const TABS = ['personal','employment','statutory'];
const VIEW_TABS = ['vt-personal','vt-employment','vt-statutory','vt-notes'];
const HR_NOTE_ROLES = ['superadmin','hr_manager','hr_admin'];
const ALL_PAGES = ['dashboard','institutions','employees','orgchart','audit','users','requisitions','candidates','interviews','offers','onboarding','offboarding','ld-catalog','ld-trainings','leave-my','leave-approvals','leave-holidays','projects','timesheet-my','timesheet-approvals','settings-notifications','settings-system-notifications','settings-bulk-upload','settings-locations','payroll-runs','payroll-my','perf-my','perf-team','perf-cycles','perf-calibration','coming-soon'];

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
  const res = await fetch(path, {...opts, headers});
  if (res.status === 401) { doLogout(); return null; }
  return res;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
async function doLogin(e) {
  e.preventDefault();
  const err = document.getElementById('loginErr');
  err.classList.add('hidden');
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

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function bootApp() {
  document.getElementById('loginScreen').classList.add('hidden');
  document.getElementById('appShell').classList.remove('hidden');
  const mr = await api('/api/meta');
  if (mr) meta = await mr.json();
  populateMetaSelects();
  applyRoleUI();
  updateSidebarUser();
  document.getElementById('headerDate').textContent =
    new Date().toLocaleDateString('en-MY',{weekday:'short',year:'numeric',month:'short',day:'numeric'});
  if (currentUser.role === 'superadmin' && !currentInstitution) {
    await loadInstitutions();
    showPage('institutions');
  } else {
    await loadEmployees();
    showPage('dashboard');
  }
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
  document.getElementById('nav-institutions-wrap').classList.toggle('hidden', !isSA);
  document.getElementById('nav-sysnotif-wrap')?.classList.toggle('hidden', !isSA);
  document.getElementById('nav-emp-group').classList.toggle('hidden', hideEmp);
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
  const canNotify = ['hr_manager','hr_admin'].includes(role);
  const canBulkUpload = role === 'hr_manager';
  const canLocations = ['hr_manager','hr_admin'].includes(role);
  document.getElementById('nav-settings-wrap')?.classList.toggle('hidden', hideEmp || !(canAudit || canUsers || canNotify || canBulkUpload || canLocations));
  document.getElementById('nav-settings-notifications')?.classList.toggle('hidden', !canNotify);
  document.getElementById('nav-bulk-upload')?.classList.toggle('hidden', !canBulkUpload);
  document.getElementById('nav-locations')?.classList.toggle('hidden', !canLocations);

  const canPayrollView = ['payroll_manager','hr_manager'].includes(role);
  document.getElementById('nav-payroll-group')?.classList.toggle('hidden', hideEmp);
  document.getElementById('nav-payroll-runs')?.classList.toggle('hidden', !canPayrollView);
  document.getElementById('nav-payroll-my')?.classList.toggle('hidden', isSA);

  document.getElementById('nav-performance-group')?.classList.toggle('hidden', hideEmp || isSA);
  document.getElementById('nav-perf-team')?.classList.toggle('hidden', !['manager','hr_manager'].includes(role));
  document.getElementById('nav-perf-cycles')?.classList.toggle('hidden', role !== 'hr_manager');
  document.getElementById('nav-perf-calibration')?.classList.toggle('hidden', role !== 'hr_manager');

  // OB buttons
  const canManageOb=['superadmin','hr_manager','hr_admin'].includes(role);
  document.getElementById('startOnboardingBtn')?.classList.toggle('hidden',!canManageOb);
  document.getElementById('startOffboardingBtn')?.classList.toggle('hidden',!canManageOb);
  document.getElementById('obTemplatesBtnOn')?.classList.toggle('hidden',!canManageOb);
  document.getElementById('obTemplatesBtnOff')?.classList.toggle('hidden',!canManageOb);
  // LD buttons
  document.getElementById('ldAddCourseBtn')?.classList.toggle('hidden',!canManageOb);
  // Role switcher — show if user has more than one assigned role
  const userRoles = currentUser?.roles || [];
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
    dashboard:'Dashboard', institutions:'Institutions', employees:'Employee List',
    orgchart:'Org Chart', audit:'Audit Log', users:'User Management', 'coming-soon':'Coming Soon',
    requisitions:'Job Requisitions', candidates:'Candidate Bank', interviews:'Interviews', offers:'Offers & Letters',
    onboarding:'Onboarding', offboarding:'Offboarding',
    'ld-catalog':'Course Catalog', 'ld-trainings':'My Trainings',
    'leave-my':'My Leave', 'leave-approvals':'Leave Approvals', 'leave-holidays':'Holiday Manager',
    'projects':'Projects', 'timesheet-my':'My Timesheet', 'timesheet-approvals':'Timesheet Approvals',
    'settings-notifications':'Settings — Notifications',
    'settings-system-notifications':'System-Wide Notifications',
    'settings-bulk-upload':'Bulk Upload Employees',
    'settings-locations':'Locations',
    'payroll-runs':'Payroll Runs', 'payroll-my':'My Payslips',
    'perf-my':'My Goals & Appraisal', 'perf-team':'Team Appraisals',
    'perf-cycles':'Performance Cycles', 'perf-calibration':'Calibration'
  };
  document.getElementById('pageTitle').textContent = titles[page] || page;
  if (page === 'dashboard')    renderDashboard();
  if (page === 'employees')    renderEmpTable(employees);
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
  if (page === 'projects')            loadProjects();
  if (page === 'timesheet-my')        loadTimesheetPage();
  if (page === 'timesheet-approvals') loadTimesheetApprovals();
  if (page === 'settings-notifications') loadNotificationSettings();
  if (page === 'settings-system-notifications') loadSystemNotificationSettings();
  if (page === 'payroll-runs') loadPayrollRuns();
  if (page === 'payroll-my')   loadMyPayslips();
  if (page === 'settings-bulk-upload') resetBulkUploadUI();
  if (page === 'settings-locations') loadLocations();
  if (page === 'perf-my')          loadMyPerformancePage();
  if (page === 'perf-team')        loadTeamAppraisalsPage();
  if (page === 'perf-cycles')      loadPerformanceCycles();
  if (page === 'perf-calibration') loadCalibrationPage();
}

// ---------------------------------------------------------------------------

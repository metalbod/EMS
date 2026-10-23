// ---------------------------------------------------------------------------
// Navigation — areas, section/page tabs, phone bottom bar
// ---------------------------------------------------------------------------
// A page's id is still its address (#leave-approvals, showPage('leave-approvals'),
// every deep link and emailed link) — this file only decides WHERE the sidebar and
// tab bars show it and WHO sees it. NAV_PAGES is the single source for: the rail
// (areas), the tab bar under the title (sections, then pages), the phone bottom
// bar, isPageReachableFromNav() (boot hash, Home tiles, command bar) and the
// command bar's page list. Each entry's `show` carries exactly the rule the old
// per-item toggles in applyRoleUI() applied (kept equal by
// static/js/__tests__/nav-model.test.js against a snapshot of the old sidebar);
// the backend still enforces every action, this only keeps people from being
// offered pages they cannot use.
//
// Order in NAV_PAGES is tab order. `area` may be a function of the rights (the
// course catalog is HR's "Learning" area but sits under Me > Growth for everyone
// else). `section` groups pages into a first tab row; a section with one page
// shows that page's own label; a section with two or more shows a second row.
//
// Depends on core.js (currentUser, currentInstitution, HR_*_ROLES,
// COMPENSATION_STAFF_ROLES, currentPage, showPage, closeBurgerMenu). Plain
// global-scope script.

const NAV_AREAS = [
  { id: 'platform', label: 'Platform', icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4' },
  { id: 'home', label: 'Home', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { id: 'me', label: 'Me', icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' },
  { id: 'team', label: 'Team', icon: 'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z' },
  { id: 'people', label: 'People', icon: 'M10 6H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V8a2 2 0 00-2-2h-5m-4 0V5a2 2 0 114 0v1m-4 0a2 2 0 104 0m-5 8a2 2 0 100-4 2 2 0 000 4zm0 0c1.306 0 2.417.835 2.83 2M9 14a3.001 3.001 0 00-2.83 2M15 11h3m-3 4h2' },
  { id: 'hiring', label: 'Hiring', icon: 'M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
  { id: 'pay', label: 'Pay', icon: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z' },
  { id: 'learning', label: 'Learning', icon: 'M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253' },
  { id: 'admin', label: 'Admin', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065zM15 12a3 3 0 11-6 0 3 3 0 016 0z' },
];

// Rights, computed fresh from the signed-in person (never cached: role switches change them).
function navRights() {
  const role = currentUser?.role;
  const isSA = role === 'superadmin';
  return {
    role, isSA,
    hideEmp: isSA && !currentInstitution,           // platform admin not inside a company
    hasEmp: !!currentUser?.employee_id,
    hrAndMgr: HR_AND_MANAGER_ROLES.includes(role),
    hrManage: HR_MANAGE_ROLES.includes(role),
    hrStaff: HR_STAFF_ROLES.includes(role),
    hrMgrOnly: HR_MANAGER_ONLY_ROLES.includes(role),
    hrMgr: role === 'hr_manager',
    comp: COMPENSATION_STAFF_ROLES.includes(role),
    recruit: !!currentUser?.can_view_recruitment,
    interviewer: !!currentUser?.is_interviewer || navRevealed.has('my-interviews'),
    managesProjects: !!currentUser?.manages_projects,
    approvals: (typeof window !== 'undefined' && window._approvalsPending) || 0,
    routeId: typeof currentRouteId === 'undefined' ? null : currentRouteId,   // the record an id-carrying page is showing
    ownEmpId: currentUser?.employee_id || null,
  };
}

// Pages that appear only because something just pointed at them (a To-Do link to My Interviews right after being picked).
const navRevealed = new Set();
function navReveal(page) { if (!navRevealed.has(page)) { navRevealed.add(page); renderNav(); } }

const _inCompany = r => !r.hideEmp;
const _recruiting = r => !r.hideEmp && r.role !== 'employee' && r.recruit;

// [page, area, section, label, show(r), aliases]
const NAV_PAGES = [
  // Platform (superadmin)
  { page: 'institutions', area: 'platform', label: 'Companies', show: r => r.isSA, aliases: 'institutions tenants' },
  { page: 'settings-system-notifications', area: 'platform', label: 'System alerts', show: r => r.isSA, aliases: 'system-wide notifications banner' },
  // Home
  { page: 'dashboard', area: 'home', label: 'Home', show: r => !r.hideEmp, aliases: 'dashboard' },
  // Me
  { page: 'me-overview', area: 'me', label: 'Overview', show: r => r.hasEmp && !r.hideEmp, aliases: 'my overview summary' },
  { page: 'my-profile', area: 'me', section: 'Profile', label: 'Profile', show: r => r.hasEmp && !r.hideEmp, aliases: 'my profile personal details contact bank' },
  { page: 'leave-my', area: 'me', label: 'Leave', show: _inCompany, aliases: 'my leave time off balance apply' },
  { page: 'timesheet-my', area: 'me', section: 'Time', label: 'Timesheet', show: _inCompany, aliases: 'my timesheet hours' },
  { page: 'overtime-my', area: 'me', section: 'Time', label: 'Overtime', show: _inCompany, aliases: 'my overtime' },
  { page: 'attendance-clock', area: 'me', section: 'Time', label: 'Clock in / out', show: r => !r.hideEmp && !r.isSA, aliases: 'attendance punch check in' },
  { page: 'payroll-my', area: 'me', section: 'Pay', label: 'Payslips', show: r => !r.hideEmp && !r.isSA, aliases: 'my payslips salary' },
  { page: 'payroll-myrewards', area: 'me', section: 'Pay', label: 'Total rewards', show: r => !r.hideEmp && !r.isSA, aliases: 'my total rewards compensation' },
  { page: 'payroll-mybenefits', area: 'me', section: 'Pay', label: 'Benefits & claims', show: r => !r.hideEmp && !r.isSA, aliases: 'my benefits claims enrollment' },
  { page: 'ld-trainings', area: 'me', section: 'Growth', label: 'Trainings', show: _inCompany, aliases: 'my trainings courses enrolments' },
  { page: 'perf-my', area: 'me', section: 'Growth', label: 'Goals & appraisal', show: r => !r.hideEmp && !r.isSA, aliases: 'my goals appraisal performance review' },
  { page: 'my-interviews', area: 'me', section: 'Growth', label: 'Interviews', show: r => !r.hideEmp && r.interviewer, aliases: 'my interviews scoring' },
  { page: 'ld-catalog', area: r => (r.hrManage ? 'learning' : 'me'), section: 'Growth', label: 'Course catalog', show: _inCompany, aliases: 'courses learning development policies' },
  // Team
  { page: 'approvals', area: 'team', label: 'Approvals', show: r => !r.hideEmp && (r.role !== 'employee' || r.approvals > 0), aliases: 'inbox decisions pending' },
  { page: 'leave-approvals', area: 'team', section: 'Requests', label: 'Leave requests', show: r => !r.hideEmp && r.hrAndMgr, aliases: 'leave approvals' },
  { page: 'timesheet-approvals', area: 'team', section: 'Requests', label: 'Timesheets', show: r => !r.hideEmp && r.hrAndMgr, aliases: 'timesheet approvals overtime' },
  { page: 'resignation-approvals', area: 'team', section: 'Requests', label: 'Resignations', show: r => r.role === 'hr_manager' || r.role === 'hr_admin' || r.role === 'manager', aliases: 'resignation approvals' },
  { page: 'attendance-review', area: 'team', section: 'Work', label: 'Attendance', show: r => !r.hideEmp && r.hrAndMgr, aliases: 'attendance review late absent' },
  { page: 'projects', area: 'team', section: 'Work', label: 'Projects', show: r => !r.hideEmp && (r.hrMgrOnly || r.managesProjects), aliases: 'projects tasks' },
  { page: 'perf-team', area: 'team', section: 'Performance', label: 'Team reviews', show: r => !r.hideEmp && !r.isSA && (r.role === 'manager' || r.role === 'hr_manager'), aliases: 'team review appraisal' },
  { page: 'perf-cycles', area: 'team', section: 'Performance', label: 'Cycles', show: r => !r.hideEmp && !r.isSA && r.hrMgr, aliases: 'performance cycles' },
  { page: 'perf-calibration', area: 'team', section: 'Performance', label: 'Calibration', show: r => !r.hideEmp && !r.isSA && r.hrMgr, aliases: 'performance calibration' },
  // People
  // The record page: not a tab of its own — it shows under People > Directory, or Me > Profile when it is your own record.
  { page: 'employee', record: true, area: r => (r.routeId && r.routeId === r.ownEmpId ? 'me' : 'people'), label: 'Employee', show: _inCompany, aliases: '' },
  { page: 'employees', area: 'people', label: 'Directory', show: _inCompany, aliases: 'employee list employees staff profile' },
  { page: 'orgchart', area: 'people', label: 'Org chart', show: _inCompany, aliases: 'organisation chart reporting' },
  { page: 'onboarding', area: 'people', label: 'Onboarding', show: r => r.hrStaff, aliases: 'new hire checklist' },
  { page: 'offboarding', area: 'people', label: 'Offboarding', show: r => r.hrStaff, aliases: 'leaver exit checklist' },
  { page: 'settings-bulk-upload', area: 'people', label: 'Import', show: r => !r.hideEmp && r.hrMgr, aliases: 'bulk upload employees csv' },
  // Hiring
  { page: 'requisitions', area: 'hiring', label: 'Requisitions', show: _recruiting, aliases: 'job requisitions openings vacancies' },
  { page: 'candidates', area: 'hiring', label: 'Candidates', show: _recruiting, aliases: 'candidate bank applicants resumes' },
  { page: 'interviews', area: 'hiring', label: 'Interviews', show: _recruiting, aliases: 'interviews scorecards' },
  { page: 'offers', area: 'hiring', label: 'Offers & letters', show: _recruiting, aliases: 'stationery offer letters' },
  // Pay
  { page: 'payroll-runs', area: 'pay', section: 'Payroll', label: 'Payroll runs', show: r => !r.hideEmp && (r.role === 'payroll_manager' || r.role === 'hr_manager'), aliases: 'payroll payslips epf socso eis pcb' },
  { page: 'comp-paygrades', area: 'pay', section: 'Compensation', label: 'Pay grades', show: r => r.comp, aliases: 'compensation salary bands' },
  { page: 'comp-joblevels', area: 'pay', section: 'Compensation', label: 'Job levels', show: r => r.comp, aliases: 'compensation' },
  { page: 'comp-jobroles', area: 'pay', section: 'Compensation', label: 'Job roles', show: r => r.comp, aliases: 'compensation' },
  { page: 'comp-meritcycles', area: 'pay', section: 'Compensation', label: 'Merit cycles', show: r => r.comp, aliases: 'compensation increments' },
  { page: 'comp-bonusplans', area: 'pay', section: 'Compensation', label: 'Bonus plans', show: r => r.comp, aliases: 'compensation' },
  { page: 'comp-commissions', area: 'pay', section: 'Compensation', label: 'Commissions', show: r => r.comp, aliases: 'compensation' },
  { page: 'comp-equity', area: 'pay', section: 'Compensation', label: 'Equity grants', show: r => r.comp, aliases: 'compensation shares options' },
  { page: 'comp-totalrewards', area: 'pay', section: 'Compensation', label: 'Total rewards', show: r => r.comp, aliases: 'compensation statements' },
  { page: 'comp-payequity', area: 'pay', section: 'Compensation', label: 'Pay equity', show: r => r.comp, aliases: 'compensation gap' },
  { page: 'ben-plans', area: 'pay', section: 'Benefits', label: 'Plan types', show: r => r.comp, aliases: 'benefits plans' },
  { page: 'ben-periods', area: 'pay', section: 'Benefits', label: 'Enrollment periods', show: r => r.comp, aliases: 'benefits open enrolment' },
  { page: 'ben-lifeevents', area: 'pay', section: 'Benefits', label: 'Life events', show: r => r.comp, aliases: 'benefits' },
  { page: 'ben-claims', area: 'pay', section: 'Benefits', label: 'Claims', show: r => r.comp, aliases: 'benefits claims reimbursement' },
  { page: 'ben-compliance', area: 'pay', section: 'Benefits', label: 'Compliance & reporting', show: r => r.comp, aliases: 'benefits reports' },
  // Admin
  { page: 'settings-locations', area: 'admin', section: 'Company', label: 'Locations', show: r => !r.hideEmp && r.hrManage, aliases: 'settings offices sites' },
  { page: 'leave-holidays', area: 'admin', section: 'Company', label: 'Leave types & holidays', show: r => !r.hideEmp && r.hrManage, aliases: 'holiday manager public holidays leave types' },
  { page: 'settings-document-types', area: 'admin', section: 'Company', label: 'Document types', show: r => !r.hideEmp && r.hrStaff, aliases: 'settings employee documents' },
  { page: 'settings-offer-letter-templates', area: 'admin', section: 'Company', label: 'Letter templates', show: r => !r.hideEmp && r.hrManage, aliases: 'settings offer letter templates' },
  { page: 'settings-performance', area: 'admin', section: 'Company', label: 'Performance settings', show: r => !r.hideEmp && r.hrMgr, aliases: 'settings probation goals' },
  { page: 'users', area: 'admin', section: 'People & access', label: 'Users', show: r => !r.hideEmp && r.hrMgrOnly, aliases: 'user management accounts passwords' },
  { page: 'settings-roles', area: 'admin', section: 'People & access', label: 'Roles & permissions', show: r => !r.hideEmp && r.hrManage, aliases: 'settings roles permission matrix' },
  { page: 'settings-approval-workflow', area: 'admin', section: 'People & access', label: 'Approval workflows', show: r => !r.hideEmp && r.hrManage, aliases: 'settings approvers chain' },
  { page: 'settings-attendance', area: 'admin', section: 'Time', label: 'Attendance rules', show: r => !r.hideEmp && r.hrManage, aliases: 'settings shifts devices geofence' },
  { page: 'settings-notifications', area: 'admin', section: 'Communication', label: 'Announcements & email', show: r => !r.hideEmp && r.hrStaff, aliases: 'settings notifications announcements smtp reminders' },
  { page: 'settings-sso', area: 'admin', section: 'Integrations & AI', label: 'Single sign-on', show: r => !r.hideEmp && r.hrMgr, aliases: 'settings microsoft entra sso' },
  { page: 'settings-mcp', area: 'admin', section: 'Integrations & AI', label: 'Claude access', show: r => !r.hideEmp && r.hrMgr, aliases: 'settings mcp connector' },
  { page: 'settings-ai-assistant', area: 'admin', section: 'Integrations & AI', label: 'AI assistant', show: r => !r.hideEmp && r.hrMgr, aliases: 'settings api key usage' },
  { page: 'audit', area: 'admin', section: 'Audit', label: 'Audit log', show: r => !r.hideEmp && r.hrMgrOnly, aliases: 'activity history system activity' },
];

const _NAV_BY_PAGE = new Map(NAV_PAGES.map(e => [e.page, e]));
const navAreaMeta = id => NAV_AREAS.find(a => a.id === id);

// The tab that is lit for a page. A record page lights the tab it belongs to.
function navActivePage(page, r = navRights()) {
  if (page === 'employee') return r.routeId && r.routeId === r.ownEmpId ? 'my-profile' : 'employees';
  return page;
}
// Opens an entry: "Profile" is your own record page; everything else is just its page.
function navOpen(page) {
  if (page === 'my-profile') return showPage('employee', { id: currentUser?.employee_id });
  return showPage(page);
}

function navEntryArea(e, r) { return typeof e.area === 'function' ? e.area(r) : e.area; }
function navSectionOf(e) { return e.section || e.label; }

// Whether this person's navigation offers a page.
function navPageVisible(page, r = navRights()) {
  const e = _NAV_BY_PAGE.get(page);
  return !!e && !!currentUser && !!e.show(r);
}
// Same name the rest of the app already uses for this question.
function isPageReachableFromNav(page) { return navPageVisible(page); }

function navAreaOf(page, r = navRights()) {
  const e = _NAV_BY_PAGE.get(page);
  return e ? navEntryArea(e, r) : null;
}

// The pages an area shows this person, in tab order.
function navAreaEntries(areaId, r = navRights()) {
  return NAV_PAGES.filter(e => !e.record && navEntryArea(e, r) === areaId && e.show(r));
}

function navVisibleAreas(r = navRights()) {
  if (!currentUser) return [];
  return NAV_AREAS.filter(a => navAreaEntries(a.id, r).length);
}

// What a page is called in the navigation (command bar, titles).
function navLabelOf(page) { return _NAV_BY_PAGE.get(page)?.label || page; }

// Pages for the command bar: [{page, label, group, aliases}].
function navSearchPages(r = navRights()) {
  return NAV_PAGES.filter(e => !e.record && e.show(r)).map(e => ({
    page: e.page, label: e.label, aliases: e.aliases || '',
    group: e.page === 'dashboard' ? '' : navAreaMeta(navEntryArea(e, r)).label + (e.section && e.section !== e.label ? ` › ${e.section}` : ''),
  }));
}

// Tab rows for an area: first row = sections (a one-page section is just that page), second row = the active
// section's pages when it has two or more.
function navTabModel(areaId, page, r = navRights()) {
  page = navActivePage(page, r);
  const entries = navAreaEntries(areaId, r);
  const sections = [];
  for (const e of entries) {
    const key = navSectionOf(e);
    let s = sections.find(x => x.key === key);
    if (!s) { s = { key, pages: [] }; sections.push(s); }
    s.pages.push(e);
  }
  const active = sections.find(s => s.pages.some(e => e.page === page)) || null;
  return {
    sections: sections.map(s => ({
      key: s.key, label: s.pages.length === 1 ? s.pages[0].label : s.key, page: s.pages[0].page,
      active: s === active, pages: s.pages.map(e => e.page),
    })),
    pages: active && active.pages.length > 1 ? active.pages.map(e => ({ page: e.page, label: e.label, active: e.page === page })) : [],
  };
}

// ---- rendering ---------------------------------------------------------------
function _navIcon(path) {
  return `<svg class="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${path}"/></svg>`;
}

function _navAreaLabel(a, r) {
  if (a.id === 'home') return r.isSA ? 'Dashboard' : 'Home';
  return a.label;
}

function _navBadgeFor(areaId) {
  return areaId === 'team' && window._approvalsPending ? window._approvalsPending : 0;
}

let _navLastArea = null;

function renderNav() {
  const rail = document.getElementById('navRail');
  if (!rail) return;
  const r = navRights();
  const areas = navVisibleAreas(r);
  const current = navAreaOf(currentPage, r);
  rail.innerHTML = areas.map(a => {
    const n = _navBadgeFor(a.id);
    const on = a.id === current;
    return `<button type="button" class="nav-rail-btn${on ? ' active' : ''}" data-area="${a.id}" onclick="navGoArea('${a.id}')" ${on ? 'aria-current="page"' : ''} title="${esc(_navAreaLabel(a, r))}">
      ${_navIcon(a.icon)}<span class="nav-rail-label">${esc(_navAreaLabel(a, r))}</span>
      ${n ? `<span class="nav-badge" aria-label="${n} waiting">${n > 99 ? '99+' : n}</span>` : ''}</button>`;
  }).join('');
  renderBottomBar(areas, current, r);
  renderAreaNav(currentPage);
}

function renderAreaNav(page) {
  const el = document.getElementById('areaNav');
  if (!el) return;
  const r = navRights();
  const areaId = navAreaOf(page, r);
  const model = areaId && areaId !== 'home' ? navTabModel(areaId, page, r) : null;
  if (!model || !model.sections.length || (model.sections.length === 1 && !model.pages.length)) { el.innerHTML = ''; el.classList.add('hidden'); return; }
  const badge = p => (p === 'approvals' && window._approvalsPending ? `<span class="appr-chip-n">${window._approvalsPending}</span>` : '');
  const row1 = model.sections.map(s =>
    `<button type="button" class="area-tab${s.active ? ' area-tab-active' : ''}" ${s.active ? 'aria-current="page"' : ''} onclick="navOpen('${s.active ? navActivePage(page, r) : s.page}')">${esc(s.label)}${s.pages.length === 1 ? badge(s.page) : ''}</button>`).join('');
  const row2 = model.pages.length
    ? `<div class="area-tabs-sub" role="group" aria-label="${esc(model.sections.find(s => s.active).key)}">${model.pages.map(p =>
      `<button type="button" class="area-subtab${p.active ? ' area-subtab-active' : ''}" ${p.active ? 'aria-current="page"' : ''} onclick="navOpen('${p.page}')">${esc(p.label)}</button>`).join('')}</div>` : '';
  el.classList.remove('hidden');
  el.innerHTML = `<div class="area-tabs" role="group" aria-label="${esc(navAreaMeta(areaId).label)} sections">${row1}</div>${row2}`;
}

// Keeps the rail, tab bars and bottom bar in step with the page that is showing. Called by showPage().
function navSync(page) {
  const area = navAreaOf(page);
  if (area !== _navLastArea || !document.querySelector('#navRail .nav-rail-btn')) { _navLastArea = area; renderNav(); }
  else {
    document.querySelectorAll('#navRail .nav-rail-btn, #bottomBar .bb-item[data-area]').forEach(b => {
      const on = b.dataset.area === area;
      b.classList.toggle('active', on);
      if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
    renderAreaNav(page);
  }
}

// An area's rail button goes to the first page it offers (the page you are on, if it is already in the area).
function navGoArea(areaId) {
  const r = navRights();
  if (navAreaOf(currentPage, r) === areaId) { closeBurgerMenu(); return; }
  const first = navAreaEntries(areaId, r)[0];
  if (first) navOpen(first.page);
  closeBurgerMenu();
}

// ---- phone bottom bar --------------------------------------------------------
const BOTTOM_BAR_PRIORITY = ['home', 'me', 'team', 'people', 'platform', 'hiring', 'pay', 'learning', 'admin'];

function renderBottomBar(areas, current, r) {
  const bar = document.getElementById('bottomBar');
  if (!bar) return;
  const ordered = BOTTOM_BAR_PRIORITY.map(id => areas.find(a => a.id === id)).filter(Boolean);
  const main = ordered.slice(0, ordered.length > 5 ? 4 : 5);
  const more = ordered.length > 5;
  bar.classList.toggle('hidden', !areas.length);
  bar.innerHTML = main.map(a => {
    const n = _navBadgeFor(a.id);
    return `<button type="button" class="bb-item${a.id === current ? ' active' : ''}" data-area="${a.id}" onclick="navGoArea('${a.id}')" ${a.id === current ? 'aria-current="page"' : ''}>
      <span class="bb-icon">${_navIcon(a.icon)}${n ? `<span class="bb-badge">${n > 99 ? '99+' : n}</span>` : ''}</span><span>${esc(_navAreaLabel(a, r))}</span></button>`;
  }).join('') + (more ? `<button type="button" class="bb-item" onclick="openBurgerMenu()" aria-haspopup="dialog"><span class="bb-icon">${_navIcon('M4 6h16M4 12h16M4 18h16')}</span><span>More</span></button>` : '');
}

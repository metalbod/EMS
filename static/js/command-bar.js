// ---------------------------------------------------------------------------
// Command bar (Ctrl/Cmd+K), "+ New" menu and the top-bar clock chip
// ---------------------------------------------------------------------------
// One registry of things a person can DO (CMD_ACTIONS) drives three places: the
// "+ New" menu (entries flagged `create`), the command bar's Actions group, and
// Home's quick-action row (via quickActionRights). Pages come from the sidebar
// itself — every [data-page] the nav actually offers this role, so a page the
// sidebar hides (applyRoleUI) can never be reached from here either. People are
// the `employees` roster the server already scoped to this caller (an employee
// gets only themself, a manager their reporting chain, HR everyone), so
// searching adds no new exposure; only name/id/department/designation are read.
//
// Depends on core.js (currentUser, employees, showPage, isPageReachableFromNav,
// ensureModuleLoaded, parseUTC, notify, HR_*_ROLES), dashboard.js (the
// dashShortcut* openers) and recruitment.js's lazy module (loaded on demand).
// Plain global-scope script.

// Which "+ Add …" / personal shortcuts this person gets. Pure: reads currentUser.
function quickActionRights() {
  const role = currentUser?.role;
  return {
    hasEmp: !!currentUser?.employee_id,
    isEmployee: role === 'employee',
    canAddEmployee: HR_STAFF_ROLES.includes(role),
    // recruitment.js is a lazy module, so its canManageRecruitment() isn't loaded yet: same rule, inline.
    canNewReq: role !== 'superadmin' && !!(currentUser?.can_manage_recruitment ?? HR_MANAGE_ROLES.includes(role)),
    canPayroll: role === 'payroll_manager',
    canAnnounce: typeof isPageReachableFromNav === 'function' && isPageReachableFromNav('settings-notifications'),
  };
}

const CMD_ACTIONS = [
  { id: 'apply-leave', label: 'Apply for leave', hint: 'Leave', kw: 'time off vacation holiday mc sick', create: true,
    visible: r => r.hasEmp, run: () => dashShortcutApplyLeave() },
  { id: 'submit-claim', label: 'Submit a claim', hint: 'Benefits', kw: 'expense reimbursement medical receipt', create: true,
    visible: r => r.hasEmp, run: () => dashShortcutSubmitClaim() },
  { id: 'log-hours', label: 'Log hours', hint: 'Timesheet', kw: 'time timesheet project task', create: true,
    visible: r => r.hasEmp, run: () => showPage('timesheet-my') },
  { id: 'clock', label: 'Clock in or out', hint: 'Attendance', kw: 'attendance check in out punch', create: false,
    visible: r => r.hasEmp && isPageReachableFromNav('attendance-clock'), run: () => topClockToggle() },
  { id: 'add-employee', label: 'Add employee', hint: 'People', kw: 'new hire staff', create: true,
    visible: r => r.canAddEmployee, run: () => dashShortcutAddEmployee() },
  { id: 'new-requisition', label: 'New job requisition', hint: 'Hiring', kw: 'job opening vacancy headcount', create: true,
    visible: r => r.canNewReq, run: () => dashShortcutNewRequisition() },
  { id: 'add-candidate', label: 'Add candidate', hint: 'Hiring', kw: 'resume cv applicant', create: true,
    visible: r => r.canNewReq, run: async () => { showPage('candidates'); await ensureModuleLoaded('recruitment'); openCandModal(); } },
  { id: 'post-announcement', label: 'Post an announcement', hint: 'Settings', kw: 'notice notification banner message', create: true,
    visible: r => r.canAnnounce, run: () => { showPage('settings-notifications'); openNotificationModal(); } },
  { id: 'new-payroll-run', label: 'New payroll run', hint: 'Payroll', kw: 'salary payslip', create: true,
    visible: r => r.canPayroll, run: () => dashShortcutNewPayrollRun() },
];

function cmdVisibleActions(createOnly) {
  const rights = quickActionRights();
  return CMD_ACTIONS.filter(a => (!createOnly || a.create) && a.visible(rights));
}

// ---- pages, read from the sidebar -----------------------------------------
function cmdPages() {
  const seen = new Map();
  document.querySelectorAll('#burgerDrawer [data-page]').forEach(el => {
    const page = el.dataset.page;
    if (seen.has(page) || !isPageReachableFromNav(page)) return;
    const label = (el.querySelector('.nav-rail-label')?.textContent || el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!label) return;
    const group = el.closest('.nav-submenu')?.previousElementSibling?.querySelector('.nav-rail-label')?.textContent.trim() || '';
    seen.set(page, { page, label, group });
  });
  return [...seen.values()];
}

// ---- matching (pure) ------------------------------------------------------
// Every typed word must appear somewhere in the haystack; a label that starts
// with the query ranks first, then a word-start match, then anything else.
function cmdMatch(query, label, extra) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return 1;
  const hay = `${label} ${extra || ''}`.toLowerCase();
  const words = q.split(/\s+/);
  if (!words.every(w => hay.includes(w))) return 0;
  const l = label.toLowerCase();
  if (l.startsWith(q)) return 4;
  if (words.every(w => l.split(/[\s—–-]+/).some(t => t.startsWith(w)))) return 3;
  return words.every(w => l.includes(w)) ? 2 : 1;
}

function cmdPeople(query) {
  const q = (query || '').trim();
  if (q.length < 2 || typeof employees === 'undefined') return [];
  return employees
    .map(e => ({ e, s: cmdMatch(q, displayName(e.full_name, e.preferred_name), `${e.full_name || ''} ${e.employee_id || ''} ${e.department || ''} ${e.designation || ''}`) }))
    .filter(x => x.s > 0)
    .sort((a, b) => b.s - a.s || (a.e.status === 'Active' ? 0 : 1) - (b.e.status === 'Active' ? 0 : 1))
    .slice(0, 5)
    .map(x => x.e);
}

// The flat, ordered list the palette shows: [{group, id, label, sub, run}]
function cmdResults(query) {
  const q = (query || '').trim();
  const out = [];
  const actions = cmdVisibleActions(false)
    .map(a => ({ a, s: cmdMatch(q, a.label, `${a.kw} ${a.hint}`) })).filter(x => x.s > 0)
    .sort((x, y) => y.s - x.s);
  (q ? actions : actions.slice(0, 6)).slice(0, 6).forEach(({ a }) => out.push({ group: 'Actions', id: `act-${a.id}`, label: a.label, sub: a.hint, run: a.run }));
  const pages = cmdPages()
    .map(p => ({ p, s: cmdMatch(q, p.label, p.group) })).filter(x => x.s > 0)
    .sort((x, y) => y.s - x.s);
  (q ? pages : pages.slice(0, 5)).slice(0, 7).forEach(({ p }) => out.push({ group: 'Pages', id: `page-${p.page}`, label: p.label, sub: p.group ? `${p.group} › ${p.label}` : 'Home', run: () => showPage(p.page) }));
  cmdPeople(q).forEach(e => out.push({ group: 'People', id: `emp-${e.employee_id}`, label: displayName(e.full_name, e.preferred_name) || e.employee_id,
    sub: [e.designation, e.department].filter(Boolean).join(' · ') || e.employee_id, run: () => viewEmployee(e.employee_id) }));
  return out;
}

// ---- the palette ------------------------------------------------------------
let _cmdOpener = null, _cmdItems = [], _cmdActive = 0;

function _cmdEl() {
  let el = document.getElementById('cmdPalette');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'cmdPalette';
  el.className = 'cmd-overlay hidden';
  el.innerHTML = `<div class="cmd-panel" role="dialog" aria-modal="true" aria-label="Search and commands">
      <div class="cmd-input-row">
        <svg class="cmd-icon" width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z"/></svg>
        <input id="cmdInput" type="text" autocomplete="off" spellcheck="false" placeholder="Search pages, people and actions…" role="combobox" aria-expanded="true" aria-controls="cmdList" aria-autocomplete="list"/>
        <kbd class="cmd-kbd">Esc</kbd>
      </div>
      <div id="cmdList" class="cmd-list" role="listbox" aria-label="Results"></div>
      <div class="cmd-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div>
    </div>`;
  el.addEventListener('mousedown', e => { if (e.target === el) closeCommandBar(); });
  el.querySelector('#cmdInput').addEventListener('input', e => _cmdRender(e.target.value));
  el.querySelector('#cmdInput').addEventListener('keydown', _cmdKeydown);
  el.querySelector('#cmdList').addEventListener('click', e => {
    const li = e.target.closest('[data-cmd-index]');
    if (li) _cmdRun(Number(li.dataset.cmdIndex));
  });
  el.querySelector('#cmdList').addEventListener('mousemove', e => {
    const li = e.target.closest('[data-cmd-index]');
    if (li && Number(li.dataset.cmdIndex) !== _cmdActive) _cmdSetActive(Number(li.dataset.cmdIndex), false);
  });
  document.body.appendChild(el);
  return el;
}

function _cmdRender(query) {
  _cmdItems = cmdResults(query);
  _cmdActive = 0;
  const list = document.getElementById('cmdList');
  if (!_cmdItems.length) {
    list.innerHTML = `<p class="cmd-empty">Nothing matches “${esc(query.trim())}”. Try a page name, a person or an action like “apply leave”.</p>`;
    document.getElementById('cmdInput').removeAttribute('aria-activedescendant');
    return;
  }
  let html = '', group = '';
  _cmdItems.forEach((it, i) => {
    if (it.group !== group) { group = it.group; html += `<div class="cmd-group" role="presentation">${esc(group)}</div>`; }
    html += `<div class="cmd-item${i === 0 ? ' cmd-item-active' : ''}" id="cmd-opt-${i}" role="option" aria-selected="${i === 0}" data-cmd-index="${i}">
        <span class="cmd-item-label">${esc(it.label)}</span><span class="cmd-item-sub">${esc(it.sub || '')}</span></div>`;
  });
  list.innerHTML = html;
  document.getElementById('cmdInput').setAttribute('aria-activedescendant', 'cmd-opt-0');
}

function _cmdSetActive(i, scroll = true) {
  if (!_cmdItems.length) return;
  _cmdActive = (i + _cmdItems.length) % _cmdItems.length;
  document.querySelectorAll('#cmdList .cmd-item').forEach((el, idx) => {
    const on = idx === _cmdActive;
    el.classList.toggle('cmd-item-active', on);
    el.setAttribute('aria-selected', on ? 'true' : 'false');
    if (on && scroll) el.scrollIntoView({ block: 'nearest' });
  });
  document.getElementById('cmdInput').setAttribute('aria-activedescendant', `cmd-opt-${_cmdActive}`);
}

function _cmdKeydown(e) {
  if (e.key === 'ArrowDown') { e.preventDefault(); _cmdSetActive(_cmdActive + 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); _cmdSetActive(_cmdActive - 1); }
  else if (e.key === 'Enter') { e.preventDefault(); _cmdRun(_cmdActive); }
  else if (e.key === 'Escape') { e.preventDefault(); closeCommandBar(); }
  else if (e.key === 'Tab') e.preventDefault(); // the box is the only stop while open
}

function _cmdRun(i) {
  const it = _cmdItems[i];
  if (!it) return;
  closeCommandBar(false);
  closeBurgerMenu();
  Promise.resolve().then(it.run).catch(err => { console.error(err); notify("Couldn't open that. Please try again."); });
}

function openCommandBar() {
  if (document.getElementById('appShell')?.classList.contains('hidden') || !currentUser) return;
  _cmdOpener = document.activeElement;
  const el = _cmdEl();
  el.classList.remove('hidden');
  const input = document.getElementById('cmdInput');
  input.value = '';
  _cmdRender('');
  input.focus();
}

function closeCommandBar(restoreFocus = true) {
  const el = document.getElementById('cmdPalette');
  if (!el || el.classList.contains('hidden')) return;
  el.classList.add('hidden');
  if (restoreFocus && _cmdOpener && document.contains(_cmdOpener)) _cmdOpener.focus();
  _cmdOpener = null;
}

document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
    e.preventDefault(); // the browser's own Ctrl/Cmd+K focuses its search box
    const open = document.getElementById('cmdPalette') && !document.getElementById('cmdPalette').classList.contains('hidden');
    if (open) closeCommandBar(); else openCommandBar();
  }
});

// ---- "+ New" menu -----------------------------------------------------------
function renderNewMenu() {
  const wrap = document.getElementById('topNewWrap');
  if (!wrap) return;
  const items = currentUser ? cmdVisibleActions(true) : [];
  wrap.classList.toggle('hidden', !items.length);
  document.getElementById('topNewMenu').innerHTML = items.map(a =>
    `<button type="button" role="menuitem" class="tb-menu-item" onclick="runNewAction('${a.id}')"><span>${esc(a.label)}</span><span class="tb-menu-hint">${esc(a.hint)}</span></button>`).join('');
}

function toggleNewMenu(force) {
  const menu = document.getElementById('topNewMenu');
  const btn = document.getElementById('topNewBtn');
  if (!menu) return;
  const open = force ?? menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !open);
  btn.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('[role="menuitem"]')?.focus();
}

function runNewAction(id) {
  toggleNewMenu(false);
  closeBurgerMenu();
  const a = CMD_ACTIONS.find(x => x.id === id);
  if (a) Promise.resolve().then(a.run).catch(err => { console.error(err); notify("Couldn't open that. Please try again."); });
}

document.addEventListener('click', e => {
  if (!document.getElementById('topNewWrap')?.contains(e.target)) toggleNewMenu(false);
});
document.addEventListener('keydown', e => {
  const menu = document.getElementById('topNewMenu');
  if (!menu || menu.classList.contains('hidden')) return;
  if (e.key === 'Escape') { toggleNewMenu(false); document.getElementById('topNewBtn').focus(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const items = [...menu.querySelectorAll('[role="menuitem"]')];
    const i = items.indexOf(document.activeElement);
    items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
  }
});

// ---- top-bar clock chip -----------------------------------------------------
// Same state and calls as Home's Clock In button (dashboard.js) — one open
// attendance row means "clocked in". refreshDashClockState() feeds both.
let _topClockOpenRow = null, _topClockBusy = false;

function renderTopClock(openRow) {
  _topClockOpenRow = openRow || null;
  const chip = document.getElementById('topClockChip');
  if (!chip) return;
  const allowed = !!currentUser?.employee_id && isPageReachableFromNav('attendance-clock');
  chip.classList.toggle('hidden', !allowed);
  if (!allowed) return;
  const since = openRow ? parseUTC(openRow.clock_in_at) : null;
  const time = since && !isNaN(since) ? since.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  chip.classList.toggle('tb-chip-on', !!openRow);
  chip.querySelector('.tb-chip-text').textContent = openRow ? `Clocked in${time ? ' · ' + time : ''}` : 'Clock in';
  chip.setAttribute('aria-label', openRow ? `Clocked in since ${time}. Activate to clock out.` : 'Clock in');
  chip.title = openRow ? 'Click to clock out' : 'Clock in now';
}

async function topClockToggle() {
  if (_topClockBusy) return;
  const out = !!_topClockOpenRow;
  if (out && !confirm('Clock out now?')) return;
  _topClockBusy = true;
  try { await (out ? dashShortcutClockOut() : dashShortcutClockIn()); } finally { _topClockBusy = false; }
}

// Called at the end of applyRoleUI(): runs on login and on every role switch.
function renderTopBarActions() {
  const kbd = document.querySelector('#topSearchBtn .tb-kbd');
  if (kbd) kbd.textContent = /Mac|iPhone|iPad/.test(navigator.platform || '') ? '⌘K' : 'Ctrl K';
  document.getElementById('topSearchBtn')?.classList.toggle('hidden', !currentUser);
  renderNewMenu();
  if (currentUser?.employee_id && isPageReachableFromNav('attendance-clock')) refreshDashClockState();
  else renderTopClock(null);
}

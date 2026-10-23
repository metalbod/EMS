// ---------------------------------------------------------------------------
// Employee profile page (#employee/<id>)
// ---------------------------------------------------------------------------
// The employee record used to be a pop-up; it is a page now, so Back, refresh, bookmarks and "Me > Profile" work.
// employees.js still renders every tab (renderEmployeeProfile) and owns the Edit / Deactivate / Resign flows; this
// file owns the page around it: opening and leaving it, the More menu, and the Overview tab (key facts, what needs
// attention, leave). Who may open a record is unchanged — the `employees` roster the server already scoped to the
// caller (an employee: themself, a manager: their chain, HR: everyone) — and the attention endpoint repeats that check.
//
// Depends on core.js (api, esc, fmtDate, showPage, navLabelOf, currentUser, currentRouteId, _profileReturn,
// HR_MANAGE_ROLES), employees.js (renderEmployeeProfile, viewingId, employees). Plain global-scope script.

function loadEmployeeProfilePage() {
  const id = currentRouteId;
  if (!id || !renderEmployeeProfile(id)) {
    notify("That employee isn't available to you.");
    showPage('employees');
    return;
  }
  const back = _profileReturn && _profileReturn !== 'employee' ? _profileReturn : 'employees';
  const label = back === 'dashboard' ? 'Home' : back === 'me-overview' ? 'Me' : navLabelOf(back);
  const el = document.getElementById('profileBackLabel');
  if (el) el.textContent = label;
  const title = document.getElementById('pageTitle');
  if (title) title.textContent = id === currentUser?.employee_id ? 'My profile' : 'Employee profile';
}

function leaveEmployeeProfile() {
  const back = _profileReturn && _profileReturn !== 'employee' && isPageReachableFromNav(_profileReturn) ? _profileReturn : 'employees';
  viewingId = null;
  showPage(back);
}

// ---- More menu ---------------------------------------------------------------
function toggleViewMore(force) {
  const menu = document.getElementById('viewMoreMenu');
  const btn = document.getElementById('viewMoreBtn');
  if (!menu) return;
  const open = force ?? menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !open);
  btn.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('[role="menuitem"]:not(.hidden)')?.focus();
}

// The More button is only there when at least one of its actions applies to this person and record.
function syncViewMore() {
  const items = [...document.querySelectorAll('#viewMoreMenu [role="menuitem"]')];
  document.getElementById('viewMoreWrap')?.classList.toggle('hidden', !items.some(b => !b.classList.contains('hidden')));
  toggleViewMore(false);
}

document.addEventListener('click', e => {
  if (!document.getElementById('viewMoreWrap')?.contains(e.target)) toggleViewMore(false);
});
document.addEventListener('keydown', e => {
  const menu = document.getElementById('viewMoreMenu');
  if (!menu || menu.classList.contains('hidden')) return;
  if (e.key === 'Escape') { toggleViewMore(false); document.getElementById('viewMoreBtn')?.focus(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const items = [...menu.querySelectorAll('[role="menuitem"]:not(.hidden)')];
    const i = items.indexOf(document.activeElement);
    items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
  }
});

// ---- Overview tab ------------------------------------------------------------
function profileYearsLabel(startDate, today = new Date()) {
  if (!startDate) return '';
  const [y, m, d] = String(startDate).slice(0, 10).split('-').map(Number);
  if (!y) return '';
  let months = (today.getFullYear() - y) * 12 + (today.getMonth() + 1 - m) - (today.getDate() < d ? 1 : 0);
  if (months < 0) return 'starts soon';
  if (months < 12) return `${months} month${months === 1 ? '' : 's'}`;
  const yrs = Math.floor(months / 12), rem = months % 12;
  return `${yrs} year${yrs === 1 ? '' : 's'}${rem ? ` ${rem} mo` : ''}`;
}

// Pure: what the Overview shows. `reportsTo` = display text already resolved by the caller.
function profileOverviewModel({ emp, reportsTo, attention, balances, canConfirm }) {
  const facts = [
    ['Job title', emp.designation], ['Department', emp.department], ['Reports to', reportsTo],
    ['Employment', emp.employment_type],
    ['Started', emp.start_date ? `${fmtDate(emp.start_date)} · ${profileYearsLabel(emp.start_date)}` : ''],
    ['Work email', emp.work_email],
  ].filter(f => f[1]);
  const items = (Array.isArray(attention) ? attention : []).map(a => ({
    text: a.text, tab: a.tab || null,
    action: a.kind === 'probation' && canConfirm ? { label: 'Confirm probation', fn: 'confirmProbationFromView()' } : (a.tab ? { label: 'Open', fn: `switchViewTab('${a.tab}')` } : null),
  }));
  const bal = (Array.isArray(balances) ? balances : []).filter(b => (b.entitled_days || 0) + (b.carried_forward_days || 0) > 0);
  const left = b => (b.accrued_days ?? b.entitled_days) + (b.carried_forward_days || 0) - (b.used_days || 0);
  bal.sort((a, b) => (b.entitled_days || 0) - (a.entitled_days || 0));
  return {
    facts, items,
    // undefined = still loading, null = the call failed, anything else = loaded
    attentionState: attention === undefined ? 'loading' : attention === null ? 'failed' : 'ok',
    leave: bal.slice(0, 4).map(b => ({ name: b.leave_type_name, left: `${+left(b).toFixed(1)}`, of: `${+((b.accrued_days ?? b.entitled_days) + (b.carried_forward_days || 0)).toFixed(1)}` })),
    leaveState: balances === undefined ? 'loading' : balances === null ? 'failed' : 'ok',
  };
}

function profileOverviewHtml(m) {
  const facts = m.facts.map(([k, v]) => `<div class="appr-fact"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
  const attn = m.attentionState === 'loading' ? '<p class="home-muted">Checking…</p>'
    : m.attentionState === 'failed' ? '<p class="home-muted">Couldn’t check right now.</p>'
    : m.items.length ? `<ul class="home-list">${m.items.map(i => `<li class="profile-attn"><span>${esc(i.text)}</span>${i.action ? `<button type="button" class="pill-btn pill-btn-outline" onclick="${i.action.fn}">${esc(i.action.label)}</button>` : ''}</li>`).join('')}</ul>`
    : '<p class="home-muted">Nothing needs attention.</p>';
  const leave = m.leaveState === 'loading' ? '<p class="home-muted">Loading…</p>'
    : m.leaveState === 'failed' ? '<p class="home-muted">Not available.</p>'
    : m.leave.length ? m.leave.map(l => `<p class="home-row"><span>${esc(l.name)}</span><strong>${esc(l.left)} <span class="home-of">of ${esc(l.of)}</span></strong></p>`).join('') : '<p class="home-muted">No leave balance yet.</p>';
  return `<div class="profile-overview">
      <div class="home-card"><span class="home-card-h">Needs attention</span>${attn}</div>
      <div class="home-card"><span class="home-card-h">Key facts</span><dl class="appr-facts">${facts}</dl></div>
      <div class="home-card"><span class="home-card-h">Leave this year</span>${leave}</div>
    </div>`;
}

let _overviewSeq = 0;
async function loadProfileOverview(empId) {
  const el = document.getElementById('vt-overview');
  if (!el || !empId) return;
  const emp = employees.find(e => e.employee_id === empId);
  if (!emp) return;
  const seq = ++_overviewSeq;
  const role = currentUser?.role;
  const reportsToEmp = emp.reports_to && emp.reports_to !== emp.employee_id ? employees.find(x => x.employee_id === emp.reports_to) : null;
  const reportsTo = emp.reports_to === emp.employee_id ? 'Top of the organisation' : reportsToEmp ? displayName(reportsToEmp.full_name, reportsToEmp.preferred_name) : (emp.manager_name || '');
  const get = async url => { try { const r = await api(url); return r && r.ok ? await r.json() : null; } catch (e) { return null; } };
  const year = new Date().getFullYear();
  const render = (attention, balances) => {
    if (seq !== _overviewSeq || viewingId !== empId) return;
    el.innerHTML = profileOverviewHtml(profileOverviewModel({ emp, reportsTo, attention, balances, canConfirm: HR_MANAGE_ROLES.includes(role) && emp.status === 'Active' && !!emp.probation_end_date }));
  };
  render(undefined, undefined);                      // facts show at once; the two cards below fill in
  const [attn, bal] = await Promise.all([get(`/api/employees/${encodeURIComponent(empId)}/attention`), get(`/api/leave/balances?employee_id=${encodeURIComponent(empId)}&year=${year}`)]);
  render(attn ? attn.items : null, bal);
}

// ---------------------------------------------------------------------------
// Home > Today — the part of Home that is shaped by who you are
// ---------------------------------------------------------------------------
// Employee: a clock-in hero, four task tiles that each carry one live detail, and
// glance cards (leave, this week, next pay day). Manager / HR: "your team today"
// (clocked in, on leave, late or missing), who is away this week and what is coming
// up. The decisions list below them is the existing to-do (dashboard.js), unchanged.
//
// Every figure comes from an endpoint that already answers it for the caller's own
// scope (leave balances and payslips default to self; /api/me/week-hours; and the
// small /api/home/* pair for the team view and next pay day). A card whose data
// fails to load keeps its action and just shows no number.
//
// Depends on core.js (api, esc, fmtDate, currentUser, showPage), dashboard.js
// (dashShortcut*, refreshDashClockState). Plain global-scope script.

const HOME_DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function homeNum(n) { return `${+Number(n).toFixed(1)}`; }

function homeDateShort(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return `${HOME_DAY_NAMES[dt.getDay()]} ${d} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1]}`;
}

// ---- employee ---------------------------------------------------------------
// Pure: the numbers and words for the employee's Today. `data` = whatever each fetch returned (or null).
function homeEmployeeModel(data) {
  const bal = (data.balances || []).filter(b => (b.entitled_days || 0) + (b.carried_forward_days || 0) > 0);
  const left = b => (b.accrued_days ?? b.entitled_days) + (b.carried_forward_days || 0) - (b.used_days || 0);
  bal.sort((a, b) => (b.entitled_days || 0) - (a.entitled_days || 0));
  const w = data.week;
  const slip = (data.payslips || [])[0];
  const pay = data.glance && data.glance.next_pay_date ? data.glance : null;
  return {
    tiles: [
      { id: 'leave', label: 'Apply for leave', detail: bal.length ? `${homeNum(left(bal[0]))} days left · ${bal[0].leave_type_name}` : 'Request time off', onclick: 'dashShortcutApplyLeave()' },
      { id: 'hours', label: 'Log hours', detail: w ? (w.missing_hours > 0 ? `${homeNum(w.missing_hours)} h still to log this week` : 'Nothing missing this week') : 'Open your timesheet', onclick: "showPage('timesheet-my')" },
      { id: 'claim', label: 'Submit a claim', detail: 'Medical and other benefit claims', onclick: 'dashShortcutSubmitClaim()' },
      { id: 'payslip', label: 'Payslips', detail: slip ? `Latest: ${fmtDate(slip.period_start)} to ${fmtDate(slip.period_end)}` : 'No payslip yet', onclick: "showPage('payroll-my')" },
    ],
    leave: bal.slice(0, 3).map(b => ({ name: b.leave_type_name, left: homeNum(left(b)), of: homeNum((b.accrued_days ?? b.entitled_days) + (b.carried_forward_days || 0)) })),
    week: w ? {
      logged: homeNum(w.logged_hours || 0), expected: homeNum(w.expected_hours || 0), missing: homeNum(w.missing_hours || 0),
      pct: w.expected_hours > 0 ? Math.min(100, Math.round(((w.logged_hours || 0) / w.expected_hours) * 100)) : 0,
      clockedIn: !!w.clocked_in_now,
    } : null,
    pay: pay ? { date: homeDateShort(pay.next_pay_date), days: pay.pay_days_until } : null,
  };
}

function homeHeroHtml(openRow) {
  const since = openRow && typeof parseUTC === 'function' ? parseUTC(openRow.clock_in_at) : null;
  const time = since && !isNaN(since) ? since.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  const inNow = !!openRow;
  return `<div class="home-hero${inNow ? ' home-hero-in' : ''}">
      <div><p class="home-hero-title">${inNow ? `You're clocked in${time ? ` since ${esc(time)}` : ''}` : "You haven't clocked in yet"}</p>
      <p class="home-hero-sub">${inNow ? 'Clock out when you finish for the day.' : 'Clock in to start your day.'}</p></div>
      <button type="button" id="homeHeroClockBtn" class="pill-btn ${inNow ? 'pill-btn-outline' : 'pill-btn-primary'} home-hero-btn" onclick="${inNow ? 'dashShortcutClockOut()' : 'dashShortcutClockIn()'}">${inNow ? 'Clock out' : 'Clock in'}</button>
    </div>`;
}

function homeEmployeeHtml(m, openRow) {
  const tiles = m.tiles.map(t => `<button type="button" class="home-tile" onclick="${t.onclick}"><span class="home-tile-label">${esc(t.label)}</span><span class="home-tile-detail">${esc(t.detail)}</span><span class="home-tile-go" aria-hidden="true">›</span></button>`).join('');
  const leave = m.leave.length ? m.leave.map(l => `<p class="home-row"><span>${esc(l.name)}</span><strong>${esc(l.left)} <span class="home-of">of ${esc(l.of)}</span></strong></p>`).join('') : '<p class="home-muted">No leave balance yet</p>';
  const week = m.week ? `<p class="home-big">${esc(m.week.logged)} <span class="home-of">of ${esc(m.week.expected)} h logged</span></p>
      <div class="home-bar" role="img" aria-label="${m.week.pct}% of expected hours logged"><span style="width:${m.week.pct}%"></span></div>
      <p class="home-muted">${m.week.missing > 0 ? `${esc(m.week.missing)} h still to log` : 'Nothing missing'}${m.week.clockedIn ? ' · clocked in now' : ''}</p>` : '<p class="home-muted">Hours unavailable right now</p>';
  const pay = m.pay ? `<p class="home-big">${esc(m.pay.date)}</p><p class="home-muted">${m.pay.days === 0 ? 'Today' : `In ${m.pay.days} day${m.pay.days === 1 ? '' : 's'}`}</p>` : '<p class="home-muted">Not set</p>';
  return `${homeHeroHtml(openRow)}
    <div class="home-tiles">${tiles}</div>
    <div class="home-glance">
      <button type="button" class="home-card" onclick="showPage('leave-my')"><span class="home-card-h">Leave balance</span>${leave}</button>
      <button type="button" class="home-card" onclick="showPage('timesheet-my')"><span class="home-card-h">This week</span>${week}</button>
      <div class="home-card"><span class="home-card-h">Next pay day</span>${pay}</div>
    </div>`;
}

let _homeEmpData = null, _homeEmpOpenRow = null;

async function loadHomeEmployee() {
  const el = document.getElementById('homeEmployeeBlock');
  if (!el) return;
  const show = currentUser?.role === 'employee' && !!currentUser?.employee_id;
  el.classList.toggle('hidden', !show);
  if (!show) return;
  const get = async url => { try { const r = await api(url); return r && r.ok ? await r.json() : null; } catch (e) { return null; } };
  const year = new Date().getFullYear();
  const [balances, week, payslips, glance] = await Promise.all([
    get(`/api/leave/balances?year=${year}`), get('/api/me/week-hours'), get('/api/payroll/payslips/mine'), get('/api/home/glance'),
  ]);
  _homeEmpData = { balances, week, payslips, glance };
  renderHomeEmployee();
}

function renderHomeEmployee() {
  const el = document.getElementById('homeEmployeeBlock');
  if (!el || !_homeEmpData) return;
  el.innerHTML = homeEmployeeHtml(homeEmployeeModel(_homeEmpData), _homeEmpOpenRow);
}

// refreshDashClockState() (dashboard.js) hands the open attendance row here so the hero stays in step with the top-bar chip.
function renderHomeHero(openRow) {
  _homeEmpOpenRow = openRow || null;
  const hero = document.querySelector('#homeEmployeeBlock .home-hero');
  if (hero) hero.outerHTML = homeHeroHtml(_homeEmpOpenRow);
}

// ---- manager / HR team view ---------------------------------------------------
function homePeopleLine(block) {
  if (!block || !block.count) return '';
  const names = block.people.map(p => p.name);
  const more = block.count - names.length;
  return names.join(', ') + (more > 0 ? ` +${more}` : '');
}

// Pure: tiles and lists for the team view from GET /api/home/team-today.
function homeTeamModel(t) {
  const lateKnown = t.attendance_configured;
  return {
    title: t.scope === 'team' ? 'Your team today' : 'Everyone today',
    note: t.non_working_day ? (t.holiday ? `Today is a public holiday (${t.holiday}).` : 'Today is a weekend.') : '',
    empty: t.total_people === 0,
    tiles: [
      { id: 'in', label: 'Clocked in', value: String(t.clocked_in.count), line: homePeopleLine(t.clocked_in), tone: '' },
      { id: 'leave', label: 'On leave', value: String(t.on_leave.count), line: homePeopleLine(t.on_leave), tone: '' },
      lateKnown
        ? { id: 'late', label: 'Late or missing', value: String(t.late_or_missing.count), line: homePeopleLine(t.late_or_missing), tone: t.late_or_missing.count ? 'warn' : '', go: 'attendance-review' }
        : { id: 'late', label: 'Late or missing', value: '—', line: 'Attendance rules are not set up', tone: '' },
    ],
    away: t.away_this_week.map(a => ({ id: a.employee_id, name: a.name, when: a.start === a.end ? homeDateShort(a.start) : `${homeDateShort(a.start)} – ${homeDateShort(a.end)}` })),
    comingUp: t.coming_up.map(c => ({ id: c.employee_id, name: c.name, what: c.kind, when: homeDateShort(c.date), days: c.days })),
    comingUpDays: t.coming_up_days,
  };
}

function homeTeamHtml(m) {
  if (m.empty) return `<h2 class="section-heading mb-3">${esc(m.title)}</h2><p class="home-muted">Nobody is in this view yet.</p>`;
  const tiles = m.tiles.map(t => {
    const body = `<span class="home-tile-label">${esc(t.label)}</span><span class="home-num${t.tone ? ' home-num-' + t.tone : ''}">${esc(t.value)}</span>${t.line ? `<span class="home-tile-detail">${esc(t.line)}</span>` : ''}`;
    return t.go ? `<button type="button" class="home-stat home-stat-link" onclick="showPage('${t.go}')">${body}<span class="home-tile-go" aria-hidden="true">›</span></button>` : `<div class="home-stat">${body}</div>`;
  }).join('');
  const who = (id, name) => `<button type="button" class="home-link" onclick="viewEmployee('${esc(id)}')">${esc(name)}</button>`;
  const away = m.away.length ? m.away.map(a => `<li class="home-li">${who(a.id, a.name)}<span class="home-muted">${esc(a.when)}</span></li>`).join('') : '<li class="home-muted">Nobody is away this week.</li>';
  const up = m.comingUp.length ? m.comingUp.map(c => `<li class="home-li">${who(c.id, c.name)}<span class="home-muted">${esc(c.what)} ${c.days === 0 ? 'today' : `in ${c.days} day${c.days === 1 ? '' : 's'}`} · ${esc(c.when)}</span></li>`).join('') : `<li class="home-muted">Nothing in the next ${m.comingUpDays} days.</li>`;
  return `<h2 class="section-heading mb-3">${esc(m.title)}</h2>
    ${m.note ? `<p class="home-note" role="note">${esc(m.note)}</p>` : ''}
    <div class="home-stats">${tiles}</div>
    <div class="home-two">
      <div class="home-card"><span class="home-card-h">Away this week</span><ul class="home-list">${away}</ul></div>
      <div class="home-card"><span class="home-card-h">Coming up</span><ul class="home-list">${up}</ul></div>
    </div>`;
}

let _homeTeamSeq = 0;
async function loadHomeTeam() {
  const el = document.getElementById('homeTeamBlock');
  if (!el) return;
  const role = currentUser?.role;
  const show = HR_AND_MANAGER_ROLES.includes(role) && !(role === 'superadmin' && !currentInstitution);
  el.classList.toggle('hidden', !show);
  if (!show) return;
  const seq = ++_homeTeamSeq;
  let data = null;
  try { const r = await api('/api/home/team-today'); data = r && r.ok ? await r.json() : null; } catch (e) { /* shown as unavailable */ }
  if (seq !== _homeTeamSeq) return; // a role switch or reload started a newer request
  if (!data) { el.innerHTML = '<h2 class="section-heading mb-3">Today</h2><p class="home-muted" role="alert">The team view couldn’t load. Reload to try again.</p>'; return; }
  el.innerHTML = homeTeamHtml(homeTeamModel(data));
}

// Called by renderDashboard(): shows the block that fits this role and loads it.
function renderHomeToday() {
  loadHomeEmployee();
  loadHomeTeam();
}

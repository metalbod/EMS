// ---------------------------------------------------------------------------
// Me > Overview — your leave, time, pay and learning at a glance
// ---------------------------------------------------------------------------
// Built only from endpoints each person already uses for their OWN data
// (leave balances default to self, /api/me/week-hours, payslips/mine, the
// caller's own enrolments), one card per Me page, each a link into that page.
// A card whose data fails to load still opens its page: it just shows no number.
//
// Depends on core.js (api, esc, fmtDate, fmtCurrency, showPage, currentUser). Plain global-scope script.

// One card per source; `data` holds whatever each fetch returned (or null). Pure: no DOM, no fetch.
function meOverviewCards(data) {
  const cards = [];
  const bal = (data.balances || []).filter(b => (b.entitled_days || 0) + (b.carried_forward_days || 0) > 0);
  const left = b => (b.accrued_days ?? b.entitled_days) + (b.carried_forward_days || 0) - (b.used_days || 0);
  bal.sort((a, b) => (b.entitled_days || 0) - (a.entitled_days || 0));
  cards.push({
    page: 'leave-my', title: 'Leave', go: 'Apply or view requests',
    big: bal.length ? `${+left(bal[0]).toFixed(1)} days` : '—',
    sub: bal.length ? [`left of ${bal[0].leave_type_name}`, ...bal.slice(1, 3).map(b => `${b.leave_type_name} ${+left(b).toFixed(1)}`)].join(' · ') : 'No leave balance yet',
  });
  const w = data.week;
  cards.push({
    page: 'timesheet-my', title: 'Time this week', go: 'Open timesheet',
    big: w ? `${+(w.logged_hours || 0).toFixed(1)} h logged` : '—',
    sub: w ? [w.clocked_in_now ? 'Clocked in now' : null, w.missing_hours > 0 ? `${+w.missing_hours.toFixed(1)} h still to log` : 'Nothing missing', w.timesheet_status ? `Timesheet ${String(w.timesheet_status).toLowerCase()}` : null].filter(Boolean).join(' · ') : 'Hours logged and clocked',
  });
  const slip = (data.payslips || [])[0];
  cards.push({
    page: 'payroll-my', title: 'Latest payslip', go: 'View payslips',
    big: slip ? fmtCurrency(slip.net_pay) : '—',
    sub: slip ? `Net pay · ${fmtDate(slip.period_start)} to ${fmtDate(slip.period_end)}` : 'No payslip yet',
  });
  const own = (data.enrolments || []).filter(e => e.employee_id === currentUser?.employee_id);
  const todo = own.filter(e => e.status === 'In Progress').length;
  cards.push({
    page: 'ld-trainings', title: 'Learning', go: 'Open trainings',
    big: todo ? `${todo} in progress` : 'All done',
    sub: todo ? 'Trainings you have started or been assigned' : 'No trainings waiting on you',
  });
  return cards;
}

function meCardHtml(c) {
  return `<button type="button" class="me-card" onclick="showPage('${esc(c.page)}')">
    <span class="me-card-h">${esc(c.title)}</span>
    <span class="me-card-big">${esc(c.big)}</span>
    <span class="me-card-sub">${esc(c.sub)}</span>
    <span class="me-card-go">${esc(c.go)} ›</span></button>`;
}

async function loadMeOverview() {
  const grid = document.getElementById('meOverviewGrid');
  if (!grid) return;
  const get = async url => { try { const r = await api(url); return r && r.ok ? await r.json() : null; } catch (e) { return null; } };
  const year = new Date().getFullYear();
  const [balances, week, payslips, enrolments] = await Promise.all([
    get(`/api/leave/balances?year=${year}`), get('/api/me/week-hours'), get('/api/payroll/payslips/mine'), get('/api/ld/enrollments'),
  ]);
  grid.innerHTML = meOverviewCards({ balances, week, payslips, enrolments }).map(meCardHtml).join('');
}

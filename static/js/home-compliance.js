// Home: "Payroll and compliance"
// ---------------------------------------------------------------------------
// The Statutory-due tile and the "Payroll and compliance" card under the
// to-do, fed by GET /api/dashboard/statutory (routers/dashboard.py). The server
// returns each section only for roles that may see it — `payroll` for
// payroll_manager/hr_manager, `documents` for hr_manager/hr_admin — so a role
// with neither simply gets no tile and no card.
//
// The remittance date is a REMINDER from a per-institution day-of-month
// setting (Payroll page -> Payroll dates); payroll models no statutory due
// dates, and the wording here never claims more than that.
//
// Depends on dashboard.js (_plural, _OVERDUE_ICON, _canOpenPage), core.js
// (api, esc, fmtDate, displayName, currentUser). Plain global-scope script.

let _complianceSeq = 0;

// "in 17 days" / "today" / "tomorrow" / "yesterday" / "3 days ago"
function _daysPhrase(n) {
  if (n === 0) return 'today';
  if (n === 1) return 'tomorrow';
  if (n === -1) return 'yesterday';
  return n > 1 ? `in ${n} days` : `${-n} days ago`;
}

function _ymd(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}
function _shortDate(iso) { return _ymd(iso).toLocaleDateString('en-MY', { day: 'numeric', month: 'short' }); }
function _wagesMonthName(ym) {
  const [y, m] = String(ym).split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-MY', { month: 'long', year: 'numeric' });
}

// The big-number tile. `payroll` is null for a role that can't see payroll.
function renderStatutoryTile(payroll) {
  const tile = document.getElementById('kpiStatutoryTile');
  if (!tile) return;
  tile.classList.toggle('hidden', !payroll);
  if (!payroll) return;
  document.getElementById('kpiPayrollCutoff').textContent = _shortDate(payroll.next_remittance_date);
  document.getElementById('kpiPayrollCutoffDelta').textContent = _daysPhrase(payroll.remittance_days_until);
}

function _complianceRow(title, metaHtml, actionHtml) {
  return `<li>
      <span class="compliance-main"><span class="compliance-title">${title}</span><span class="compliance-meta">${metaHtml}</span></span>
      ${actionHtml || ''}
    </li>`;
}

function _complianceButton(label, nav, ariaLabel) {
  return `<button type="button" class="pill-btn todo-action pill-btn-outline" onclick="${nav}" aria-label="${esc(ariaLabel)}">${label}</button>`;
}

function _compliancePayrollHtml(p) {
  const month = _wagesMonthName(p.remittance_wages_month);
  const run = p.run;
  // Payroll that isn't finalized close to the remittance date is the one thing
  // here worth a warning — said in words with the icon, not colour alone.
  const atRisk = p.remittance_days_until <= 7 && (!run || run.status !== 'Finalized');
  const runText = run ? `${esc(month)} payroll: ${esc(run.status)}` : `no ${esc(month)} payroll run yet`;
  const runHtml = atRisk ? `<span class="todo-overdue">${_OVERDUE_ICON}${runText}</span>` : runText;
  const canOpen = _canOpenPage('payroll-runs');
  const open = canOpen ? _complianceButton('Open payroll', "showPage('payroll-runs')", 'Open payroll runs') : '';
  return `<section class="todo-section">
    <h3 class="todo-subheading">Payroll</h3>
    <div class="todo-block"><ul class="todo-reminders">
      ${_complianceRow('EPF · SOCSO · EIS · PCB remittance',
        `Due ${esc(_shortDate(p.next_remittance_date))} · ${_daysPhrase(p.remittance_days_until)} · for ${esc(month)} wages · ${runHtml}`, open)}
      ${_complianceRow('Pay day', `${esc(_shortDate(p.next_pay_date))} · ${_daysPhrase(p.pay_days_until)}`)}
    </ul></div>
  </section>`;
}

function _complianceDocWhen(doc) {
  const n = doc.days_until;
  if (n == null) return `Expires ${esc(fmtDate(doc.expiry_date))}`;
  const text = n < 0 ? `Expired ${_daysPhrase(n)}` : n === 0 ? 'Expires today' : `Expires ${_daysPhrase(n)}`;
  const exact = `<span class="sr-only-text">, ${esc(fmtDate(doc.expiry_date))}</span>`;
  return n < 0
    ? `<span class="todo-timing todo-overdue" title="${esc(fmtDate(doc.expiry_date))}">${_OVERDUE_ICON}${text}${exact}</span>`
    : `<span class="todo-timing" title="${esc(fmtDate(doc.expiry_date))}">${text}${exact}</span>`;
}

function _complianceDocumentsHtml(d) {
  const rows = d.items.map(doc => _complianceRow(
    esc(displayName(doc.employee_name, doc.preferred_name)),
    `${esc(doc.document_type)} · ${_complianceDocWhen(doc)}`)).join('');
  const more = d.total - d.items.length;
  const footer = `<li>
      <span class="compliance-meta">${more > 0 ? `${more} more not shown` : ''}</span>
      ${_complianceButton('View calendar', "showPage('dashboard');switchDashTab('dash-leave')", 'View all expiring documents on the calendar')}
    </li>`;
  return `<section class="todo-section">
    <h3 class="todo-subheading">Documents expiring or expired</h3>
    <div class="todo-block"><ul class="todo-reminders">${rows}${footer}</ul></div>
  </section>`;
}

// Returns '' when there is nothing worth a card.
function _complianceCardBody(data) {
  return [
    data.payroll ? _compliancePayrollHtml(data.payroll) : '',
    data.documents && data.documents.total > 0 ? _complianceDocumentsHtml(data.documents) : '',
  ].join('');
}

async function loadStatutoryStrip() {
  const card = document.getElementById('dashboardComplianceCard');
  const body = document.getElementById('dashboardComplianceBody');
  const seq = ++_complianceSeq;
  // Superadmins and plain employees never have either section.
  if (!currentUser || ['superadmin', 'employee'].includes(currentUser.role)) {
    renderStatutoryTile(null);
    card?.classList.add('hidden');
    return;
  }
  let data = null;
  try {
    const res = await api('/api/dashboard/statutory');
    if (seq !== _complianceSeq) return; // a newer call (role switch) owns the screen now
    if (!res) return; // 401: api() has already started the logout flow
    if (res.ok) data = await res.json();
  } catch (e) { /* fall through: an optional strip fails quietly */ }
  if (seq !== _complianceSeq) return;
  // Optional context, not a task list: if it can't load, show neither the tile
  // nor the card rather than a wrong or placeholder date.
  const html = data ? _complianceCardBody(data) : '';
  renderStatutoryTile(data?.payroll || null);
  if (body) body.innerHTML = html;
  card?.classList.toggle('hidden', !html);
}

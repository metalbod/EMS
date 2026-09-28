import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL dashboard.js + home-compliance.js + payroll.js in a function
// scope with only the globals they read stubbed.
const read = f => readFileSync(resolve(__dirname, '..', f), 'utf8');
const SRC = ['dashboard.js', 'home-compliance.js', 'payroll.js'].map(read).join('\n');
const escStub = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmtDateStub = v => { if (!v) return '—'; const [y, m, d] = String(v).slice(0, 10).split('-'); return `${d}-${MONTHS[+m - 1]}-${y.slice(2)}`; };
const displayNameStub = (full, pref) => pref || full;

function load(apiImpl, user = { role: 'hr_manager' }) {
  const factory = new Function('api', 'esc', 'fmtDate', 'displayName', 'currentUser', 'guardAsync', 'showPage', 'apiErrorText',
    `${SRC}\nreturn { loadStatutoryStrip, renderStatutoryTile, _daysPhrase, loadPayrollSettings, savePayrollSettings };`);
  const shown = [];
  const mod = factory(apiImpl, escStub, fmtDateStub, displayNameStub, user, fn => fn, p => shown.push(p),
    d => (typeof d === 'string' ? d : Array.isArray(d) ? d.map(e => e.msg).join('; ') : ''));
  return { ...mod, shown };
}

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const payroll = (over = {}) => ({
  pay_day: 25, next_pay_date: '2026-10-25', pay_days_until: 27,
  remittance_day: 15, next_remittance_date: '2026-10-15', remittance_days_until: 17,
  remittance_wages_month: '2026-09', run: { id: 1, period_start: '2026-09-01', period_end: '2026-09-30', status: 'Finalized' }, ...over,
});
const docs = (items, total) => ({ total: total ?? items.length, items });
const doc = (over = {}) => ({ employee_id: 'E1', employee_name: 'Aiman Rahman', preferred_name: null, document_type: 'Work Permit',
  expiry_date: '2026-10-03', status: 'expiring_soon', days_until: 5, ...over });

const $ = id => document.getElementById(id);
const body = () => $('dashboardComplianceBody');
const flush = () => new Promise(r => setTimeout(r, 0));

beforeEach(() => {
  document.body.innerHTML = `
    <div id="submenu-x" class="hidden"><div data-page="payroll-runs"></div></div>
    <div id="kpiStatutoryTile" class="kpi-tile hidden"><p class="kpi-tile-label">Statutory due</p>
      <p id="kpiPayrollCutoff">—</p><p id="kpiPayrollCutoffDelta"></p></div>
    <section id="dashboardComplianceCard" class="hidden"><h2>Payroll and compliance</h2><div id="dashboardComplianceBody"></div></section>
    <section id="payrollSettingsCard" class="hidden">
      <input id="payrollPayDay"/><input id="payrollRemitDay"/>
      <button id="savePayrollSettingsBtn" class="hidden"></button><p id="payrollSettingsStatus"></p></section>`;
});
afterEach(() => { vi.useRealTimers(); });

describe('days phrases', () => {
  it('reads naturally in both directions', () => {
    const { _daysPhrase } = load(async () => null);
    expect([_daysPhrase(0), _daysPhrase(1), _daysPhrase(17), _daysPhrase(-1), _daysPhrase(-3)])
      .toEqual(['today', 'tomorrow', 'in 17 days', 'yesterday', '3 days ago']);
  });
});

describe('Statutory-due tile', () => {
  it('shows the next remittance date and how far away it is, only when the role can see payroll', async () => {
    const api = async () => json(200, { payroll: payroll(), documents: null });
    await load(api).loadStatutoryStrip();
    expect($('kpiStatutoryTile').classList.contains('hidden')).toBe(false);
    expect($('kpiPayrollCutoff').textContent).toMatch(/15/);
    expect($('kpiPayrollCutoffDelta').textContent).toBe('in 17 days');

    await load(async () => json(200, { payroll: null, documents: docs([doc()]) })).loadStatutoryStrip();
    expect($('kpiStatutoryTile').classList.contains('hidden')).toBe(true); // hr_admin: documents but no payroll
  });

  it('never shows a placeholder date: a failed load hides the tile and the card', async () => {
    for (const api of [async () => json(500, {}), async () => { throw new TypeError('offline'); }, async () => json(200, null)]) {
      $('kpiStatutoryTile').classList.remove('hidden');
      await load(api).loadStatutoryStrip();
      expect($('kpiStatutoryTile').classList.contains('hidden')).toBe(true);
      expect($('dashboardComplianceCard').classList.contains('hidden')).toBe(true);
    }
  });

  it('is skipped entirely for superadmin and plain employees (no request made)', async () => {
    const api = vi.fn(async () => json(200, { payroll: payroll(), documents: null }));
    for (const role of ['superadmin', 'employee']) {
      await load(api, { role }).loadStatutoryStrip();
      expect($('kpiStatutoryTile').classList.contains('hidden')).toBe(true);
    }
    expect(api).not.toHaveBeenCalled();
  });
});

describe('Payroll and compliance card', () => {
  it('states the remittance as a dated reminder with the payroll run for the wages month it covers', async () => {
    await load(async () => json(200, { payroll: payroll(), documents: null })).loadStatutoryStrip();
    const text = body().textContent.replace(/\s+/g, ' ');
    expect(text).toContain('EPF · SOCSO · EIS · PCB remittance');
    expect(text).toMatch(/Due 15 Oct · in 17 days · for September 2026 wages · September 2026 payroll: Finalized/);
    expect(text).toMatch(/Pay day\s*25 Oct · in 27 days/); // title and detail are separate stacked lines
    expect($('dashboardComplianceCard').classList.contains('hidden')).toBe(false);
    expect(body().querySelectorAll('.todo-overdue')).toHaveLength(0); // finalized: nothing to warn about
  });

  it('warns — in words with an icon — when payroll is not finalized within a week of the due date', async () => {
    const soon = payroll({ remittance_days_until: 5, run: { id: 2, period_start: '2026-09-01', period_end: '2026-09-30', status: 'Draft' } });
    await load(async () => json(200, { payroll: soon, documents: null })).loadStatutoryStrip();
    const warn = body().querySelector('.todo-overdue');
    expect(warn.textContent).toContain('September 2026 payroll: Draft');
    expect(warn.querySelector('svg').getAttribute('aria-hidden')).toBe('true');

    await load(async () => json(200, { payroll: payroll({ remittance_days_until: 3, run: null }), documents: null })).loadStatutoryStrip();
    expect(body().querySelector('.todo-overdue').textContent).toContain('no September 2026 payroll run yet');

    await load(async () => json(200, { payroll: payroll({ remittance_days_until: 12, run: null }), documents: null })).loadStatutoryStrip();
    expect(body().querySelector('.todo-overdue')).toBeNull(); // far off: plain text, no alarm
    expect(body().textContent).toContain('no September 2026 payroll run yet');
  });

  it('offers "Open payroll" only when this role can open the Payroll page', async () => {
    await load(async () => json(200, { payroll: payroll(), documents: null })).loadStatutoryStrip();
    expect([...body().querySelectorAll('button')].map(b => b.textContent)).toEqual(['Open payroll']);
    document.getElementById('submenu-x').innerHTML = ''; // no Payroll nav item for this role
    await load(async () => json(200, { payroll: payroll(), documents: null })).loadStatutoryStrip();
    expect(body().querySelectorAll('button')).toHaveLength(0);
  });

  it('lists expiring and expired documents in words, with the exact date for screen readers', async () => {
    const items = [doc({ employee_name: 'Siti Aminah', document_type: 'Passport', expiry_date: '2026-09-25', status: 'overdue', days_until: -3 }),
                   doc({ days_until: 5 }), doc({ employee_name: 'Ng Say Li', days_until: 0, status: 'expiring_soon' })];
    await load(async () => json(200, { payroll: null, documents: docs(items) })).loadStatutoryStrip();
    const rows = [...body().querySelectorAll('.todo-reminders li')];
    expect(rows[0].textContent).toContain('Siti Aminah');
    expect(rows[0].textContent).toContain('Passport');
    expect(rows[0].querySelector('.todo-overdue').textContent).toContain('Expired 3 days ago');
    expect(rows[0].querySelector('.sr-only-text').textContent).toBe(', 25-Sep-26');
    expect(rows[1].textContent).toContain('Expires in 5 days');
    expect(rows[1].querySelector('.todo-overdue')).toBeNull(); // expiring soon is not an alarm
    expect(rows[2].textContent).toContain('Expires today');
  });

  it('uses the preferred name, says how many are not shown, and links to the calendar', async () => {
    const items = [doc({ preferred_name: 'Sam' })];
    await load(async () => json(200, { payroll: null, documents: docs(items, 12) })).loadStatutoryStrip();
    expect(body().textContent).toContain('Sam');
    expect(body().textContent).not.toContain('Aiman Rahman');
    expect(body().textContent).toContain('11 more not shown');
    const btn = body().querySelector('button');
    expect(btn.textContent).toBe('View calendar');
    expect(btn.getAttribute('onclick')).toBe("showPage('dashboard');switchDashTab('dash-leave')");
  });

  it('shows no card at all when there is nothing to say (no payroll, no expiring documents)', async () => {
    await load(async () => json(200, { payroll: null, documents: docs([], 0) })).loadStatutoryStrip();
    expect($('dashboardComplianceCard').classList.contains('hidden')).toBe(true);
    expect(body().innerHTML.trim()).toBe('');
  });

  it('escapes hostile text from names and document types', async () => {
    const evil = '<img src=x onerror=alert(1)>';
    await load(async () => json(200, { payroll: null, documents: docs([doc({ employee_name: evil, document_type: evil })]) })).loadStatutoryStrip();
    expect(body().querySelector('img')).toBeNull();
    expect(body().textContent).toContain(evil);
  });

  it('a slow stale response cannot overwrite a newer one (e.g. after a role switch)', async () => {
    let releaseFirst;
    const first = new Promise(r => { releaseFirst = r; });
    let n = 0;
    const api = () => (++n === 1 ? first : Promise.resolve(json(200, { payroll: payroll({ remittance_days_until: 2 }), documents: null })));
    const mod = load(api);
    const p1 = mod.loadStatutoryStrip();
    await mod.loadStatutoryStrip();
    releaseFirst(json(200, { payroll: payroll({ remittance_days_until: 99 }), documents: null }));
    await p1;
    expect($('kpiPayrollCutoffDelta').textContent).toBe('in 2 days');
  });
});

describe('Payroll dates form', () => {
  it('fills the fields for a payroll manager and lets them save', async () => {
    const api = vi.fn(async (url, opts) => (opts?.method === 'PUT'
      ? json(200, { pay_day: 28, statutory_remittance_day: 12, can_edit: true })
      : json(200, { pay_day: 25, pay_cycle: 'Monthly', statutory_remittance_day: 15, can_edit: true })));
    const mod = load(api, { role: 'payroll_manager' });
    await mod.loadPayrollSettings();
    expect($('payrollPayDay').value).toBe('25');
    expect($('payrollRemitDay').value).toBe('15');
    expect($('payrollPayDay').disabled).toBe(false);
    expect($('savePayrollSettingsBtn').classList.contains('hidden')).toBe(false);
    $('payrollPayDay').value = '28'; $('payrollRemitDay').value = '12';
    await mod.savePayrollSettings();
    const put = api.mock.calls.find(c => c[1]?.method === 'PUT');
    expect(JSON.parse(put[1].body)).toEqual({ pay_day: 28, statutory_remittance_day: 12 });
    expect($('payrollSettingsStatus').textContent).toMatch(/^Saved\./);
  });

  it('is read-only, with the reason, for hr_manager', async () => {
    await load(async () => json(200, { pay_day: 25, pay_cycle: 'Monthly', statutory_remittance_day: 15, can_edit: false }), { role: 'hr_manager' }).loadPayrollSettings();
    expect($('payrollPayDay').disabled).toBe(true);
    expect($('payrollRemitDay').disabled).toBe(true);
    expect($('savePayrollSettingsBtn').classList.contains('hidden')).toBe(true);
    expect($('payrollSettingsStatus').textContent).toBe('Only a payroll manager can change these.');
  });

  it('hides the card for a role without payroll access (403)', async () => {
    $('payrollSettingsCard').classList.remove('hidden');
    await load(async () => json(403, { detail: 'Forbidden' })).loadPayrollSettings();
    expect($('payrollSettingsCard').classList.contains('hidden')).toBe(true);
  });

  it('checks the ranges before sending, with a specific message, and sends nothing', async () => {
    const api = vi.fn(async () => json(200, { pay_day: 25, pay_cycle: 'Monthly', statutory_remittance_day: 15, can_edit: true }));
    const mod = load(api, { role: 'payroll_manager' });
    await mod.loadPayrollSettings();
    api.mockClear();
    for (const [pay, remit, msg] of [['0', '15', /Pay day must be/], ['32', '15', /Pay day must be/], ['25', '29', /Remittance reminder day must be/],
                                      ['25', '0', /Remittance reminder day must be/], ['25.5', '15', /Pay day must be/], ['', '15', /Pay day must be/]]) {
      $('payrollPayDay').value = pay; $('payrollRemitDay').value = remit;
      await mod.savePayrollSettings();
      expect($('payrollSettingsStatus').textContent).toMatch(msg);
    }
    expect(api).not.toHaveBeenCalled();
  });

  it('shows the server message on a failed save and keeps what was typed', async () => {
    const api = async (url, opts) => (opts?.method === 'PUT' ? json(422, { detail: 'Value error, bad day' })
      : json(200, { pay_day: 25, pay_cycle: 'Monthly', statutory_remittance_day: 15, can_edit: true }));
    const mod = load(api, { role: 'payroll_manager' });
    await mod.loadPayrollSettings();
    $('payrollPayDay').value = '30';
    await mod.savePayrollSettings();
    expect($('payrollSettingsStatus').textContent).toMatch(/^Couldn't save: /);
    expect($('payrollPayDay').value).toBe('30');
  });
});

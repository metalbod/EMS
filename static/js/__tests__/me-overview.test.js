import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL pure card builder from me-overview.js.
const src = readFileSync(resolve(__dirname, '..', 'me-overview.js'), 'utf8');
const pure = src.slice(src.indexOf('function meOverviewCards('), src.indexOf('function meCardHtml('));
const build = (data, user = { employee_id: 'E1' }) =>
  new Function('fmtCurrency', 'fmtDate', 'currentUser', `${pure}\nreturn meOverviewCards;`)(v => `RM ${Number(v).toFixed(2)}`, v => String(v), user)(data);
const byPage = cards => Object.fromEntries(cards.map(c => [c.page, c]));

describe('Me overview cards', () => {
  it('always gives one card per Me page, even when nothing loaded', () => {
    const cards = build({ balances: null, week: null, payslips: null, enrolments: null });
    expect(cards.map(c => c.page)).toEqual(['leave-my', 'timesheet-my', 'payroll-my', 'ld-trainings']);
    expect(cards.every(c => c.big && c.sub && c.go)).toBe(true);
    expect(byPage(cards)['leave-my'].big).toBe('—');
  });

  it('leave: the biggest entitlement first, then two more types, in days left', () => {
    const cards = byPage(build({ balances: [
      { leave_type_name: 'Medical', entitled_days: 14, carried_forward_days: 0, used_days: 4 },
      { leave_type_name: 'Annual', entitled_days: 16, carried_forward_days: 2, used_days: 7.5 },
      { leave_type_name: 'Unused', entitled_days: 0, carried_forward_days: 0, used_days: 0 },
    ] }));
    expect(cards['leave-my'].big).toBe('10.5 days');
    expect(cards['leave-my'].sub).toBe('left of Annual · Medical 10');
  });

  it('time: logged hours, what is missing, and whether you are clocked in', () => {
    const c = byPage(build({ week: { logged_hours: 12.5, missing_hours: 27.5, clocked_in_now: { since_utc: 'x' }, timesheet_status: 'Draft' } }))['timesheet-my'];
    expect(c.big).toBe('12.5 h logged');
    expect(c.sub).toBe('Clocked in now · 27.5 h still to log · Timesheet draft');
    expect(byPage(build({ week: { logged_hours: 40, missing_hours: 0 } }))['timesheet-my'].sub).toBe('Nothing missing');
  });

  it('pay: the newest payslip only', () => {
    const c = byPage(build({ payslips: [{ net_pay: 4200, period_start: '2026-09-01', period_end: '2026-09-30' }, { net_pay: 1, period_start: 'a', period_end: 'b' }] }))['payroll-my'];
    expect(c.big).toBe('RM 4200.00');
    expect(c.sub).toContain('2026-09-01 to 2026-09-30');
  });

  it('learning counts only your own enrolments that are in progress', () => {
    const cards = byPage(build({ enrolments: [
      { employee_id: 'E1', status: 'In Progress' }, { employee_id: 'E1', status: 'Completed' }, { employee_id: 'E2', status: 'In Progress' },
    ] }));
    expect(cards['ld-trainings'].big).toBe('1 in progress');
    expect(byPage(build({ enrolments: [{ employee_id: 'E2', status: 'In Progress' }] }))['ld-trainings'].big).toBe('All done');
  });
});

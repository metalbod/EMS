import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL pure builders from home-today.js.
const src = readFileSync(resolve(__dirname, '..', 'home-today.js'), 'utf8');
const pure = src.slice(src.indexOf('const HOME_DAY_NAMES'), src.indexOf('let _homeEmpData'));
const team = src.slice(src.indexOf('function homePeopleLine'), src.indexOf('let _homeTeamSeq'));
const H = new Function('esc', 'fmtDate', 'parseUTC', `${pure}\n${team}\nreturn { homeEmployeeModel, homeEmployeeHtml, homeHeroHtml, homeTeamModel, homeTeamHtml, homeDateShort };`)(
  s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  v => String(v), v => new Date(v + 'Z'));

describe('employee Today', () => {
  const balances = [
    { leave_type_name: 'Medical', entitled_days: 14, carried_forward_days: 0, used_days: 4 },
    { leave_type_name: 'Annual', entitled_days: 16, carried_forward_days: 2, used_days: 7.5 },
  ];

  it('each task tile carries one live detail and an action', () => {
    const m = H.homeEmployeeModel({ balances, week: { logged_hours: 12, expected_hours: 40, missing_hours: 28 }, payslips: [{ period_start: '2026-09-01', period_end: '2026-09-30' }], glance: { next_pay_date: '2026-10-25', pay_days_until: 1 } });
    const by = Object.fromEntries(m.tiles.map(t => [t.id, t]));
    expect(by.leave.detail).toBe('10.5 days left · Annual');
    expect(by.hours.detail).toBe('28 h still to log this week');
    expect(by.payslip.detail).toContain('2026-09-01 to 2026-09-30');
    expect(m.tiles.every(t => t.onclick)).toBe(true);
    expect(m.pay).toEqual({ date: 'Sun 25 Oct', days: 1 });
    expect(m.week.pct).toBe(30);
  });

  it('still shows every tile with a neutral line when nothing loaded', () => {
    const m = H.homeEmployeeModel({ balances: null, week: null, payslips: null, glance: null });
    expect(m.tiles).toHaveLength(4);
    expect(m.tiles.every(t => t.detail && t.label)).toBe(true);
    expect(m.week).toBeNull();
    expect(m.pay).toBeNull();
    expect(H.homeEmployeeHtml(m, null)).toContain('Hours unavailable');
  });

  it('the hero offers Clock in when out and Clock out when in', () => {
    expect(H.homeHeroHtml(null)).toContain('dashShortcutClockIn()');
    const inRow = H.homeHeroHtml({ clock_in_at: '2026-10-24T01:02:00' });
    expect(inRow).toContain('dashShortcutClockOut()');
    expect(inRow).toContain('home-hero-in');
  });

  it('caps the progress bar at 100 percent', () => {
    expect(H.homeEmployeeModel({ week: { logged_hours: 50, expected_hours: 40, missing_hours: 0 } }).week.pct).toBe(100);
  });
});

describe('team Today', () => {
  const t = (over = {}) => ({
    scope: 'team', date: '2026-10-24', non_working_day: false, holiday: null, total_people: 8, attendance_configured: true,
    clocked_in: { count: 5, people: [{ employee_id: 'E1', name: 'Aisyah' }, { employee_id: 'E2', name: 'Wei Jie' }] },
    on_leave: { count: 1, people: [{ employee_id: 'E3', name: 'Raj' }] },
    late_or_missing: { count: 2, people: [{ employee_id: 'E4', name: 'Mei' }] },
    away_this_week: [{ employee_id: 'E3', name: 'Raj', start: '2026-10-22', end: '2026-10-24' }],
    coming_up: [{ employee_id: 'E5', name: 'Lim', kind: 'Probation ends', date: '2026-10-29', days: 5 }], coming_up_days: 30, ...over });

  it('titles by scope and shows the three counts, with the first names and "+N" for the rest', () => {
    const m = H.homeTeamModel(t());
    expect(m.title).toBe('Your team today');
    expect(H.homeTeamModel(t({ scope: 'company' })).title).toBe('Everyone today');
    expect(m.tiles.map(x => [x.id, x.value])).toEqual([['in', '5'], ['leave', '1'], ['late', '2']]);
    expect(m.tiles[0].line).toBe('Aisyah, Wei Jie +3');
    expect(m.tiles[2].tone).toBe('warn');
    expect(m.tiles[2].go).toBe('attendance-review');
  });

  it('says so instead of showing a zero when attendance rules are not set up', () => {
    const late = H.homeTeamModel(t({ attendance_configured: false })).tiles[2];
    expect(late.value).toBe('—');
    expect(late.line).toContain('not set up');
    expect(late.go).toBeUndefined();
  });

  it('formats away and coming-up lines', () => {
    const m = H.homeTeamModel(t());
    expect(m.away[0].when).toBe('Thu 22 Oct – Sat 24 Oct');
    expect(m.comingUp[0]).toMatchObject({ what: 'Probation ends', days: 5 });
    const html = H.homeTeamHtml(m);
    expect(html).toContain('in 5 days');
    expect(html).toContain('viewEmployee(');
  });

  it('notes a weekend or holiday, and handles an empty team', () => {
    expect(H.homeTeamModel(t({ non_working_day: true, holiday: 'Deepavali' })).note).toContain('Deepavali');
    expect(H.homeTeamModel(t({ non_working_day: true })).note).toBe('Today is a weekend.');
    expect(H.homeTeamHtml(H.homeTeamModel(t({ total_people: 0 })))).toContain('Nobody is in this view');
  });

  it('escapes names', () => {
    const html = H.homeTeamHtml(H.homeTeamModel(t({ on_leave: { count: 1, people: [{ employee_id: 'E3', name: '<img src=x onerror=alert(1)>' }] } })));
    expect(html).not.toContain('<img');
  });
});

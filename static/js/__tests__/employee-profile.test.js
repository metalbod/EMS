import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL pure pieces of employee-profile.js and core.js's route helpers.
const prof = readFileSync(resolve(__dirname, '..', 'employee-profile.js'), 'utf8');
const core = readFileSync(resolve(__dirname, '..', 'core.js'), 'utf8');
const pure = prof.slice(prof.indexOf('function profileYearsLabel'), prof.indexOf('let _overviewSeq'));
const P = new Function('esc', 'fmtDate', `${pure}\nreturn { profileYearsLabel, profileOverviewModel, profileOverviewHtml };`)(s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'), v => String(v));
const routes = new Function(`${core.slice(core.indexOf('function routeToHash'), core.indexOf('let _profileReturn'))}\nreturn { routeToHash, parseRoute };`)();

describe('route helpers', () => {
  it('round-trips a page, and a page with a record id (escaped)', () => {
    expect(routes.routeToHash('leave-my', null)).toBe('leave-my');
    expect(routes.routeToHash('employee', 'EMP 0042/x')).toBe('employee/EMP%200042%2Fx');
    expect(routes.parseRoute('#employee/EMP%200042%2Fx')).toEqual({ page: 'employee', id: 'EMP 0042/x' });
    expect(routes.parseRoute('#leave-my')).toEqual({ page: 'leave-my', id: null });
    expect(routes.parseRoute('')).toEqual({ page: '', id: null });
    expect(routes.parseRoute('#employee/%E0%A4%A')).toEqual({ page: 'employee', id: null });   // malformed escape: no id, no crash
    expect(routes.parseRoute('#employee/')).toEqual({ page: 'employee', id: null });
  });
});

describe('profile overview', () => {
  const emp = { designation: 'Engineer', department: 'IT', employment_type: 'Permanent', start_date: '2024-01-15', work_email: 'a@b.com', probation_end_date: '2026-11-01', status: 'Active' };

  it('service length in words', () => {
    const t = new Date(2026, 9, 24);
    expect(P.profileYearsLabel('2024-01-15', t)).toBe('2 years 9 mo');
    expect(P.profileYearsLabel('2026-10-01', t)).toBe('0 months');
    expect(P.profileYearsLabel('2025-10-24', t)).toBe('1 year');
    expect(P.profileYearsLabel('2027-01-01', t)).toBe('starts soon');
    expect(P.profileYearsLabel('', t)).toBe('');
  });

  it('shows only the facts that exist, and lets HR confirm probation from the attention list', () => {
    const m = P.profileOverviewModel({ emp: { ...emp, work_email: '' }, reportsTo: 'Dewi', canConfirm: true,
      attention: [{ kind: 'probation', text: 'Probation ends in 8 days' }, { kind: 'documents', text: '1 document expiring', tab: 'vt-documents' }], balances: [] });
    expect(m.facts.map(f => f[0])).toEqual(['Job title', 'Department', 'Reports to', 'Employment', 'Started']);
    expect(m.items[0].action.fn).toBe('confirmProbationFromView()');
    expect(m.items[1].action).toEqual({ label: 'Open', fn: "switchViewTab('vt-documents')" });
    expect(P.profileOverviewModel({ emp, attention: [{ kind: 'probation', text: 'x' }], balances: [], canConfirm: false }).items[0].action).toBeNull();
  });

  it('distinguishes loading, failed and loaded for both cards', () => {
    const loading = P.profileOverviewModel({ emp, attention: undefined, balances: undefined });
    expect([loading.attentionState, loading.leaveState]).toEqual(['loading', 'loading']);
    const failed = P.profileOverviewModel({ emp, attention: null, balances: null });
    expect([failed.attentionState, failed.leaveState]).toEqual(['failed', 'failed']);
    expect(P.profileOverviewHtml(failed)).toContain('Couldn’t check right now');
    const ok = P.profileOverviewModel({ emp, attention: [], balances: [{ leave_type_name: 'Annual', entitled_days: 14, carried_forward_days: 0, used_days: 3.5 }] });
    expect(ok.leave[0]).toEqual({ name: 'Annual', left: '10.5', of: '14' });
    expect(P.profileOverviewHtml(ok)).toContain('Nothing needs attention');
  });

  it('escapes what it prints', () => {
    const html = P.profileOverviewHtml(P.profileOverviewModel({ emp: { ...emp, designation: '<img src=x onerror=alert(1)>' }, attention: [], balances: [] }));
    expect(html).not.toContain('<img');
  });
});

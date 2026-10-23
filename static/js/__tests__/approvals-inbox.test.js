import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL pure pieces of approvals.js (decision requests, filtering, wording) and command-bar.js (matching).
const appr = readFileSync(resolve(__dirname, '..', 'approvals.js'), 'utf8');
const cmd = readFileSync(resolve(__dirname, '..', 'command-bar.js'), 'utf8');
const pure = appr.slice(appr.indexOf('const APPR_MODULE_LABELS'), appr.indexOf('const apprState'));
const A = new Function(`${pure}\nreturn { apprDecisionRequest, apprNeedsReason, apprBulkEligible, apprVisible, apprAge, APPR_MODULE_LABELS, APPR_NOUN };`)();
const matchSrc = cmd.slice(cmd.indexOf('function cmdMatch('), cmd.indexOf('function cmdPeople('));
const { cmdMatch } = new Function(`${matchSrc}\nreturn { cmdMatch };`)();

describe('apprDecisionRequest — the one call that decides each kind of request', () => {
  const t = (module, extra = {}) => ({ module, ref_id: 7, focus_id: 7, project_row: false, project_id: null, ...extra });

  it('leave and training: the same PATCH the Leave and L&D pages use, reason only on reject', () => {
    expect(A.apprDecisionRequest(t('leave'), 'approve', '')).toEqual({ method: 'PATCH', url: '/api/leave/applications/7/status', body: { status: 'Approved' } });
    expect(A.apprDecisionRequest(t('leave'), 'reject', 'Clash')).toEqual({ method: 'PATCH', url: '/api/leave/applications/7/status', body: { status: 'Rejected', notes: 'Clash' } });
    expect(A.apprDecisionRequest(t('ld_enrollment'), 'approve', '').url).toBe('/api/ld/enrollments/7/status');
  });

  it('a per-project timesheet or overtime split goes to the project endpoint, a whole record to the whole-record one', () => {
    expect(A.apprDecisionRequest(t('timesheet', { project_row: true, project_id: 3, ref_id: 55, focus_id: 9 }), 'approve', '').url).toBe('/api/timesheets/9/projects/3/status');
    expect(A.apprDecisionRequest(t('timesheet'), 'approve', '').url).toBe('/api/timesheets/7/status');
    expect(A.apprDecisionRequest(t('overtime', { project_row: true, ref_id: 12 }), 'approve', '').url).toBe('/api/overtime/projects/12/status');
    expect(A.apprDecisionRequest(t('overtime'), 'reject', 'No').url).toBe('/api/overtime/7/status');
    expect(A.apprDecisionRequest(t('overtime'), 'reject', 'No').body).toEqual({ status: 'Rejected' });
  });

  it('claims, requisitions, resignations and PIPs use their own endpoints and field names', () => {
    expect(A.apprDecisionRequest(t('claims'), 'reject', 'x')).toEqual({ method: 'PUT', url: '/api/benefits/claims/7/decide', body: { status: 'Rejected' } });
    expect(A.apprDecisionRequest(t('requisition'), 'reject', 'Too senior').body).toEqual({ action: 'reject', comments: 'Too senior' });
    expect(A.apprDecisionRequest(t('requisition'), 'approve', '').body.action).toBe('approve');
    expect(A.apprDecisionRequest(t('resignation'), 'approve', '').url).toBe('/api/resignations/7');
    expect(A.apprDecisionRequest(t('pip'), 'approve', '').url).toBe('/api/performance/pip/7/decide');
  });

  it('an unknown kind has no decision call at all', () => {
    expect(A.apprDecisionRequest(t('payroll'), 'approve', '')).toBeNull();
  });
});

describe('inbox rules', () => {
  it('only leave and training can be ticked for bulk approve', () => {
    expect(A.apprBulkEligible({ module: 'leave', ref_id: 1 })).toBe(true);
    expect(A.apprBulkEligible({ module: 'ld_enrollment', ref_id: 1 })).toBe(true);
    for (const m of ['claims', 'timesheet', 'overtime', 'requisition', 'resignation', 'pip']) expect(A.apprBulkEligible({ module: m, ref_id: 1 })).toBe(false);
  });

  it('a claim rejection takes no reason, everything else does', () => {
    expect(A.apprNeedsReason({ module: 'claims' })).toBe(false);
    expect(A.apprNeedsReason({ module: 'leave' })).toBe(true);
  });

  it('filters by type and keeps everything for "all"', () => {
    const items = [{ module: 'leave' }, { module: 'claims' }, { module: 'leave' }];
    expect(A.apprVisible(items, 'all')).toHaveLength(3);
    expect(A.apprVisible(items, 'leave')).toHaveLength(2);
    expect(A.apprVisible(items, 'pip')).toHaveLength(0);
  });

  it('says how long a request has waited in words', () => {
    expect(A.apprAge({ days_overdue: 3 })).toEqual({ text: 'Overdue 3 days', tone: 'overdue' });
    expect(A.apprAge({ days_overdue: 1 }).text).toBe('Overdue 1 day');
    expect(A.apprAge({ days_overdue: null, days_waiting: 0 }).text).toBe('Waiting since today');
    expect(A.apprAge({ days_overdue: null, days_waiting: 6 })).toEqual({ text: 'Waiting 6 days', tone: 'late' });
    expect(A.apprAge({ days_overdue: null, days_waiting: null }).text).toBe('');
  });
});

describe('cmdMatch — command bar ranking', () => {
  it('an empty query matches everything, a missing word matches nothing', () => {
    expect(cmdMatch('', 'Apply for leave', '')).toBeGreaterThan(0);
    expect(cmdMatch('payslip', 'Apply for leave', 'time off')).toBe(0);
  });

  it('every typed word must appear; prefix beats word-start beats anywhere', () => {
    const prefix = cmdMatch('apply', 'Apply for leave', '');
    const wordStart = cmdMatch('leave', 'Apply for leave', '');
    const inside = cmdMatch('pply', 'Apply for leave', '');
    expect(prefix).toBeGreaterThan(wordStart);
    expect(wordStart).toBeGreaterThan(inside);
    expect(inside).toBeGreaterThan(0);
    expect(cmdMatch('apply leave', 'Apply for leave', '')).toBeGreaterThan(0);
  });

  it('finds an action through its keywords but ranks a label hit higher', () => {
    expect(cmdMatch('vacation', 'Apply for leave', 'time off vacation')).toBe(1);
    expect(cmdMatch('leave', 'Apply for leave', 'time off vacation')).toBeGreaterThan(1);
  });
});

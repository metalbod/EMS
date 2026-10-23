import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL helpers from leave.js (no copies) for the "who can use this leave type" dialog and the Apply Leave type list.
const src = readFileSync(resolve(__dirname, '..', 'leave.js'), 'utf8');
const fnSource = name => {
  const start = src.indexOf(`function ${name}(`);
  expect(start).toBeGreaterThan(-1);
  return src.slice(start, src.indexOf('\n}\n', start) + 2);
};
const load = (names, extra = '') => new Function(`${extra}\n${names.map(fnSource).join('\n')}\nreturn {${names.join(',')}};`)();

describe('leaveEligibilityPreviewText', () => {
  const { leaveEligibilityPreviewText } = load(['leaveEligibilityPreviewText']);
  it('says everyone can use a type with no rules', () => {
    expect(leaveEligibilityPreviewText({ eligible: 12, total: 12, missing_data: 0 }, false)).toBe('Everyone can use this (12 active people).');
  });
  it('counts who a rule lets in', () => {
    expect(leaveEligibilityPreviewText({ eligible: 5, total: 12, missing_data: 0 }, true)).toBe('5 of 12 active people can use this today.');
  });
  it('warns when people are left out only because their record lacks the data', () => {
    expect(leaveEligibilityPreviewText({ eligible: 5, total: 12, missing_data: 3 }, true)).toContain('3 not counted');
  });
  it('is empty before the server has answered', () => {
    expect(leaveEligibilityPreviewText(null, true)).toBe('');
  });
});

describe('leaveApplyTypeLabel', () => {
  const { leaveApplyTypeLabel } = load(['leaveApplyTypeLabel']);
  const all = [{ id: 1, name: 'Annual Leave', annual_entitlement: 14 }, { id: 2, name: 'Birthday Leave', annual_entitlement: 1, shares_entitlement_with_id: 1 }];
  it('shows days per year for a type with its own balance', () => {
    expect(leaveApplyTypeLabel(all[0], all)).toBe('Annual Leave (14 days/yr)');
  });
  it('names the pool for a type that shares one', () => {
    expect(leaveApplyTypeLabel(all[1], all)).toBe('Birthday Leave (shares with Annual Leave, max 1/yr)');
  });
});

describe('refreshLeaveApplyForEmployee', () => {
  const setup = (me, picked) => {
    const typeSel = { value: '', innerHTML: '' };
    const calls = [];
    const els = { leaveApplyTypeId: typeSel, leaveApplyEmpId: { value: picked } };
    const api = async url => {
      calls.push(url);
      const body = url.startsWith('/api/leave/types') ? [{ id: 7, name: 'Paternity Leave', annual_entitlement: 7 }] : [];
      return { ok: true, json: async () => body };
    };
    const code = `${fnSource('leaveApplyTypeLabel')}\n${src.slice(src.indexOf('async function refreshLeaveApplyForEmployee('), src.indexOf('\n}\n', src.indexOf('async function refreshLeaveApplyForEmployee(')) + 2)}\nreturn refreshLeaveApplyForEmployee;`;
    const fn = new Function('document', 'api', 'currentUser', 'isLeaveManager', 'leaveTypesCache', 'esc', 'updateLeaveApplyBalanceNote', 'updateLeaveApplyDaysPreview',
      `let leaveApplyTypes=[], leaveApplyBalancesCache=[], leaveApplyLimitsCache=[];\n${code}`)(
      { getElementById: id => els[id] }, api, me, () => me.role === 'hr_manager', [], x => x, () => {}, () => {});
    return { fn, calls, typeSel };
  };
  it('asks for the types of the employee HR picked, not HR themself', async () => {
    const { fn, calls, typeSel } = setup({ role: 'hr_manager', employee_id: 'EMP1' }, 'EMP9');
    await fn();
    expect(calls[0]).toBe('/api/leave/types?employee_id=EMP9');
    expect(calls.every(c => !c.includes('EMP1'))).toBe(true);
    expect(typeSel.innerHTML).toContain('Paternity Leave');
  });
  it('uses the signed-in employee for a plain employee', async () => {
    const { fn, calls } = setup({ role: 'employee', employee_id: 'EMP2' }, '');
    await fn();
    expect(calls[0]).toBe('/api/leave/types?employee_id=EMP2');
  });
});

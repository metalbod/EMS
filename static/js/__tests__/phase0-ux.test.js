import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL notify() (core.js) and renderDashQuickActions() (dashboard.js).
const core = readFileSync(resolve(__dirname, '..', 'core.js'), 'utf8');
const dash = readFileSync(resolve(__dirname, '..', 'dashboard.js'), 'utf8');

const toastSrc = core.slice(core.indexOf('function apiErrorText('), core.indexOf('// Auth\n') - 80);
const loadNotify = () => new Function(`${toastSrc}\nreturn { notify, showToast };`)();

const cmd = readFileSync(resolve(__dirname, '..', 'command-bar.js'), 'utf8');
function loadQuickActions(ctx) {
  const rights = cmd.slice(cmd.indexOf('function quickActionRights('), cmd.indexOf('const CMD_ACTIONS'));
  const src = dash.slice(dash.indexOf('function renderDashQuickActions('), dash.indexOf('async function dashShortcutLogHours'));
  const names = ['currentUser', 'HR_STAFF_ROLES', 'HR_MANAGE_ROLES', 'refreshResignButtonState', 'refreshDashClockState', 'isPageReachableFromNav'];
  return new Function(...names, `${rights}\n${src}\nreturn renderDashQuickActions;`)(...names.map(n => ctx[n]));
}

describe('notify() replaces alert() with a toast', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('colours by wording: failures red, confirmations green, the rest blue', () => {
    const { notify } = loadNotify();
    notify('Failed to save leave type');
    notify('Overtime settings saved.');
    notify('Holiday list is up to date for 2026');
    const kinds = [...document.querySelectorAll('.toast')].map(t => t.className);
    expect(kinds[0]).toContain('toast-error');
    expect(kinds[1]).toContain('toast-success');
    expect(kinds[2]).toContain('toast-info');
  });

  it('shows server text as text, never markup', () => {
    const { notify } = loadNotify();
    notify('<img src=x onerror=alert(1)> Could not save');
    const t = document.querySelector('.toast');
    expect(t.querySelector('img')).toBeNull();
    expect(t.textContent).toContain('<img');
  });

  it('turns a non-string detail from the server into readable text and ignores empty messages', () => {
    const { notify } = loadNotify();
    notify([{ msg: 'Value error, Email is required' }]);
    notify('');
    notify(undefined);
    const toasts = document.querySelectorAll('.toast');
    expect(toasts).toHaveLength(1);
    expect(toasts[0].textContent).toBe('Email is required');
  });
});

describe('Home quick actions follow the person, not just the employee role', () => {
  const ids = ['dashboardQuickActions', 'dashQaApplyLeave', 'dashQaClaim', 'dashClockBtn', 'dashQaLogHours', 'dashboardResignBtn',
    'dashQaRoleDivider', 'dashQaAddEmployee', 'dashQaNewReq', 'dashQaNewPayrollRun'];
  const shown = id => !document.getElementById(id).classList.contains('hidden');
  const run = (user, canReq = false) => {
    const ctx = { currentUser: { ...user, can_manage_recruitment: canReq }, HR_STAFF_ROLES: ['hr_manager', 'hr_admin'], HR_MANAGE_ROLES: ['superadmin', 'hr_manager', 'hr_admin'], refreshResignButtonState: vi.fn(), refreshDashClockState: vi.fn(), isPageReachableFromNav: () => false };
    loadQuickActions(ctx)();
    return ctx;
  };
  beforeEach(() => { document.body.innerHTML = ids.map(i => `<div id="${i}" class="hidden"></div>`).join(''); });

  it('an employee gets the personal shortcuts and Resign, nothing administrative', () => {
    const ctx = run({ role: 'employee', employee_id: 'E1' });
    // the clock-in hero and task tiles (home-today.js) replace the four personal pills for an employee; Resign stays
    expect(shown('dashboardResignBtn')).toBe(true);
    expect(['dashQaApplyLeave', 'dashQaClaim', 'dashClockBtn', 'dashQaLogHours'].some(shown)).toBe(false);
    expect(['dashQaAddEmployee', 'dashQaNewReq', 'dashQaNewPayrollRun', 'dashQaRoleDivider'].some(shown)).toBe(false);
    expect(ctx.refreshResignButtonState).toHaveBeenCalled();
  });

  it('a manager gets the personal shortcuts but not Resign', () => {
    const ctx = run({ role: 'manager', employee_id: 'M1' });
    expect(shown('dashQaApplyLeave')).toBe(true);
    expect(shown('dashboardResignBtn')).toBe(false);
    expect(shown('dashQaAddEmployee')).toBe(false);
    expect(ctx.refreshResignButtonState).not.toHaveBeenCalled();
    expect(ctx.refreshDashClockState).toHaveBeenCalled();
  });

  it('an HR manager also gets Add Employee, and New Requisition only when allowed', () => {
    run({ role: 'hr_manager', employee_id: 'H1' }, true);
    expect(shown('dashQaAddEmployee')).toBe(true);
    expect(shown('dashQaNewReq')).toBe(true);
    expect(shown('dashQaRoleDivider')).toBe(true);
    run({ role: 'hr_manager', employee_id: 'H1' }, false);
    expect(shown('dashQaNewReq')).toBe(false);
  });

  it('a payroll manager gets New Payroll Run; a superadmin with no employee record gets no row', () => {
    run({ role: 'payroll_manager', employee_id: 'P1' });
    expect(shown('dashQaNewPayrollRun')).toBe(true);
    expect(shown('dashQaAddEmployee')).toBe(false);
    run({ role: 'superadmin', employee_id: null });
    expect(shown('dashboardQuickActions')).toBe(false);
    expect(shown('dashQaApplyLeave')).toBe(false);
  });
});

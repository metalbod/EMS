import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL nav.js against injected globals. The fixture is a snapshot of which pages each role could reach through the
// OLD accordion sidebar (captured from applyRoleUI + isPageReachableFromNav before the navigation was rebuilt); the new model
// must reproduce it exactly, apart from the pages that are new on purpose (me-overview).
const src = readFileSync(resolve(__dirname, '..', 'nav.js'), 'utf8');
const fixture = JSON.parse(readFileSync(resolve(__dirname, 'fixtures', 'nav-visibility.json'), 'utf8'));
const ALL_PAGES = [...new Set(Object.values(fixture).flat())];

const ROLES = {
  HR_MANAGE_ROLES: ['superadmin', 'hr_manager', 'hr_admin'],
  HR_AND_MANAGER_ROLES: ['superadmin', 'hr_manager', 'hr_admin', 'manager'],
  HR_STAFF_ROLES: ['hr_manager', 'hr_admin'],
  HR_MANAGER_ONLY_ROLES: ['superadmin', 'hr_manager'],
  COMPENSATION_STAFF_ROLES: ['hr_manager', 'payroll_manager', 'compensation_manager'],
};

function load(user, institution = null, pending = 0, page = 'dashboard') {
  window._approvalsPending = pending;
  const names = ['currentUser', 'currentInstitution', 'currentPage', ...Object.keys(ROLES), 'esc'];
  const args = [user, institution, page, ...Object.values(ROLES), s => String(s)];
  return new Function(...names, `${src}\nreturn { navPageVisible, navAreaOf, navAreaEntries, navVisibleAreas, navTabModel, navSearchPages, NAV_PAGES, NAV_AREAS, navRights };`)(...args);
}

const base = { can_view_recruitment: false, is_interviewer: false, manages_projects: false, employee_id: 'E1' };
const SCENARIOS = {
  hr_manager: [{ ...base, role: 'hr_manager', can_view_recruitment: true }],
  hr_admin: [{ ...base, role: 'hr_admin', can_view_recruitment: true }],
  payroll_manager: [{ ...base, role: 'payroll_manager' }],
  compensation_manager: [{ ...base, role: 'compensation_manager' }],
  manager: [{ ...base, role: 'manager' }],
  employee: [{ ...base, role: 'employee' }],
  superadmin_no_inst: [{ ...base, role: 'superadmin', employee_id: null }],
  superadmin_in_inst: [{ ...base, role: 'superadmin', employee_id: null, can_view_recruitment: true }, { id: 1, name: 'X' }],
  manager_recruit: [{ ...base, role: 'manager', can_view_recruitment: true }],
  employee_interviewer: [{ ...base, role: 'employee', is_interviewer: true }],
  employee_projectmgr: [{ ...base, role: 'employee', manages_projects: true }],
  manager_no_employee: [{ ...base, role: 'manager', employee_id: null }],
};

describe('the new navigation offers each role exactly the pages the old sidebar did', () => {
  for (const [name, [user, inst]] of Object.entries(SCENARIOS)) {
    it(name, () => {
      const nav = load(user, inst);
      const visible = nav.NAV_PAGES.map(e => e.page).filter(p => nav.navPageVisible(p) && p !== 'me-overview').sort();
      expect(visible).toEqual(fixture[name]);
    });
  }
});

describe('structure', () => {
  it('every page has one entry, an existing area, and unique page ids', () => {
    const nav = load(SCENARIOS.hr_manager[0]);
    const ids = nav.NAV_PAGES.map(e => e.page);
    expect(new Set(ids).size).toBe(ids.length);
    for (const e of nav.NAV_PAGES) {
      const areas = typeof e.area === 'function' ? [e.area({ hrManage: true }), e.area({ hrManage: false })] : [e.area];
      areas.forEach(a => expect(nav.NAV_AREAS.some(x => x.id === a)).toBe(true));
    }
    // every page the old sidebar could show is still in the model
    for (const p of ALL_PAGES) expect(ids).toContain(p);
  });

  it('rail size per role: employee 3, manager 4, HR manager 8', () => {
    const rail = n => load(...SCENARIOS[n]).navVisibleAreas().map(a => a.id);
    expect(rail('employee')).toEqual(['home', 'me', 'people']);
    expect(rail('manager')).toEqual(['home', 'me', 'team', 'people']);
    expect(rail('hr_manager')).toEqual(['home', 'me', 'team', 'people', 'hiring', 'pay', 'learning', 'admin']);
    expect(rail('superadmin_no_inst')).toEqual(['platform']);
  });

  it('the course catalog is HR\'s Learning area and everyone else\'s Me > Growth', () => {
    expect(load(...SCENARIOS.hr_manager).navAreaOf('ld-catalog')).toBe('learning');
    expect(load(...SCENARIOS.manager).navAreaOf('ld-catalog')).toBe('me');
    expect(load(...SCENARIOS.employee).navAreaOf('ld-catalog')).toBe('me');
  });

  it('an employee only gets Team while something waits on them', () => {
    const emp = SCENARIOS.employee;
    expect(load(...emp, 0).navVisibleAreas().map(a => a.id)).not.toContain('team');
    const withWork = load(emp[0], null, 3);
    expect(withWork.navVisibleAreas().map(a => a.id)).toContain('team');
    expect(withWork.navAreaEntries('team').map(e => e.page)).toEqual(['approvals']);
  });

  it('Me overview is for people with an employee record only', () => {
    expect(load(...SCENARIOS.manager).navPageVisible('me-overview')).toBe(true);
    expect(load(...SCENARIOS.manager_no_employee).navPageVisible('me-overview')).toBe(false);
    expect(load(...SCENARIOS.superadmin_in_inst).navPageVisible('me-overview')).toBe(false);
  });

  it('tab rows: sections first, a second row only when the section has several pages', () => {
    const hr = load(...SCENARIOS.hr_manager);
    const pay = hr.navTabModel('pay', 'comp-bonusplans');
    expect(pay.sections.map(s => s.label)).toEqual(['Payroll runs', 'Compensation', 'Benefits']);
    expect(pay.sections.find(s => s.active).key).toBe('Compensation');
    expect(pay.pages).toHaveLength(9);
    expect(pay.pages.find(p => p.active).page).toBe('comp-bonusplans');
    const team = hr.navTabModel('team', 'approvals');
    expect(team.sections.map(s => s.label)).toEqual(['Approvals', 'Requests', 'Work', 'Performance']);
    expect(team.pages).toEqual([]);              // Approvals is a one-page section: no second row
    expect(hr.navTabModel('hiring', 'candidates').sections.map(s => s.label)).toEqual(['Requisitions', 'Candidates', 'Interviews', 'Offers & letters']);
  });

  it('old names stay findable: Stationery, Employee List, Holiday Manager, My Leave', () => {
    const hr = load(...SCENARIOS.hr_manager);
    const text = p => `${p.label} ${p.group} ${p.aliases}`.toLowerCase();
    const find = page => hr.navSearchPages().find(p => p.page === page);
    expect(text(find('offers'))).toContain('stationery');
    expect(text(find('employees'))).toContain('employee list');
    expect(text(find('leave-holidays'))).toContain('holiday manager');
    expect(text(find('leave-my'))).toContain('my leave');
  });
});

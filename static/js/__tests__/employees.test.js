import { describe, it, expect, beforeEach } from 'vitest';

// Matches employees.js's EMP_COLUMNS / empAvailableColumns / loadEmpColumnPrefs —
// the Employee List's column picker. "Pay Grade" is roles-gated the same
// way the Compensation module itself is gated elsewhere (dashboard.js's
// canCompensation): hr_manager/payroll_manager/compensation_manager only.
// Everyone else never sees it in the picker, and any stale saved
// preference naming it is filtered out rather than honored.
describe('Employee List column picker', () => {
  const EMP_COLUMNS = [
    { key:'employee_id', label:'ID', default:false },
    { key:'email', label:'Email', default:false },
    { key:'phone', label:'Mobile No', default:false },
    { key:'designation', label:'Job Title', default:true },
    { key:'department', label:'Department', default:true },
    { key:'manager', label:'Manager', default:true },
    { key:'location', label:'Location', default:true },
    { key:'start_date', label:'Join Date', default:false },
    { key:'probation_end_date', label:'Confirm Date', default:false },
    { key:'date_of_birth', label:'Date of Birth', default:false },
    { key:'gender', label:'Gender', default:false },
    { key:'race', label:'Race', default:false },
    { key:'employment_type', label:'Employee Type', default:true },
    { key:'years_of_service', label:'Years of Service', default:true },
    { key:'status', label:'Status', default:true },
    { key:'pay_grade', label:'Pay Grade', default:false, roles:['hr_manager','payroll_manager','compensation_manager'] },
  ];
  const EMP_COLUMNS_STORAGE_KEY = 'empListColumns';

  function empAvailableColumns(role) {
    return EMP_COLUMNS.filter(c => !c.roles || c.roles.includes(role));
  }

  function loadEmpColumnPrefs(role, storage) {
    let saved = null;
    try { saved = JSON.parse(storage.getItem(EMP_COLUMNS_STORAGE_KEY) || 'null'); } catch { /* ignore malformed value */ }
    const available = new Set(empAvailableColumns(role).map(c => c.key));
    if (Array.isArray(saved)) return new Set(saved.filter(k => available.has(k)));
    return new Set(EMP_COLUMNS.filter(c => c.default).map(c => c.key));
  }

  beforeEach(() => {
    localStorage.clear();
  });

  it('offers Pay Grade in the picker for hr_manager/payroll_manager/compensation_manager', () => {
    for (const role of ['hr_manager', 'payroll_manager', 'compensation_manager']) {
      expect(empAvailableColumns(role).some(c => c.key === 'pay_grade')).toBe(true);
    }
  });

  it('hides Pay Grade from the picker for every other role', () => {
    for (const role of ['hr_admin', 'manager', 'employee', 'superadmin']) {
      expect(empAvailableColumns(role).some(c => c.key === 'pay_grade')).toBe(false);
    }
  });

  it('defaults to today\'s visible columns when nothing is saved', () => {
    const prefs = loadEmpColumnPrefs('hr_manager', localStorage);
    expect([...prefs].sort()).toEqual(['department', 'designation', 'employment_type', 'location', 'manager', 'status', 'years_of_service']);
  });

  it('restores a previously saved column selection', () => {
    localStorage.setItem(EMP_COLUMNS_STORAGE_KEY, JSON.stringify(['employee_id', 'email', 'status']));
    const prefs = loadEmpColumnPrefs('hr_manager', localStorage);
    expect([...prefs].sort()).toEqual(['email', 'employee_id', 'status']);
  });

  it('strips a saved Pay Grade preference for a role that can no longer see it', () => {
    // Simulates a browser shared across users, or a role change — a stale
    // "pay_grade" entry from an earlier hr_manager session must never leak
    // through for a manager/employee opening the same browser afterward.
    localStorage.setItem(EMP_COLUMNS_STORAGE_KEY, JSON.stringify(['status', 'pay_grade']));
    const prefs = loadEmpColumnPrefs('manager', localStorage);
    expect([...prefs]).toEqual(['status']);
  });

  it('keeps a saved Pay Grade preference for a role that can see it', () => {
    localStorage.setItem(EMP_COLUMNS_STORAGE_KEY, JSON.stringify(['status', 'pay_grade']));
    const prefs = loadEmpColumnPrefs('compensation_manager', localStorage);
    expect([...prefs].sort()).toEqual(['pay_grade', 'status']);
  });

  it('falls back to defaults when the saved value is malformed JSON', () => {
    localStorage.setItem(EMP_COLUMNS_STORAGE_KEY, '{not valid json');
    const prefs = loadEmpColumnPrefs('hr_manager', localStorage);
    expect([...prefs].sort()).toEqual(['department', 'designation', 'employment_type', 'location', 'manager', 'status', 'years_of_service']);
  });

  it('falls back to defaults when the saved value is not an array', () => {
    localStorage.setItem(EMP_COLUMNS_STORAGE_KEY, JSON.stringify({ status: true }));
    const prefs = loadEmpColumnPrefs('hr_manager', localStorage);
    expect([...prefs].sort()).toEqual(['department', 'designation', 'employment_type', 'location', 'manager', 'status', 'years_of_service']);
  });
});

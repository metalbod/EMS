import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL helpers from timesheet.js that decide what a project manager (not HR) sees on the Projects page.
const src = readFileSync(resolve(__dirname, '..', 'timesheet.js'), 'utf8');
const start = src.indexOf('function isProjectAdmin()');
const end = src.indexOf('// ---------------------------------------------------------------------------', start);
const make = currentUser => new Function('currentUser', 'HR_MANAGER_ONLY_ROLES', `${src.slice(start, end)}\nreturn { isProjectAdmin, myManagedProjects };`)(currentUser, ['superadmin', 'hr_manager']);

const projects = [
  { id: 1, name: 'EZFY', manager_ids: ['A002'] },
  { id: 2, name: 'Asia Food City', manager_ids: ['A007'] },
  { id: 3, name: 'Mandrill Tech', manager_ids: ['A009', 'A002'] },
  { id: 4, name: 'No managers', manager_ids: [] },
  { id: 5, name: 'Old shape' },
];

describe('Projects page for a project manager', () => {
  it('HR Manager and superadmin run the whole screen; a manager-role user does not', () => {
    expect(make({ role: 'hr_manager' }).isProjectAdmin()).toBe(true);
    expect(make({ role: 'superadmin' }).isProjectAdmin()).toBe(true);
    expect(make({ role: 'manager', employee_id: 'A002' }).isProjectAdmin()).toBe(false);
    expect(make({ role: 'employee', employee_id: 'A002' }).isProjectAdmin()).toBe(false);
    expect(make(null).isProjectAdmin()).toBe(false);
  });

  it('shows a project manager only the projects they are listed as a manager of', () => {
    const mine = make({ role: 'manager', employee_id: 'A002' }).myManagedProjects(projects);
    expect(mine.map(p => p.name)).toEqual(['EZFY', 'Mandrill Tech']);
  });

  it('shows nothing when there is no employee record, or nobody manages anything for them', () => {
    expect(make({ role: 'manager' }).myManagedProjects(projects)).toEqual([]);
    expect(make({ role: 'manager', employee_id: 'A777' }).myManagedProjects(projects)).toEqual([]);
  });
});

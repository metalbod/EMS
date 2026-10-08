import { describe, it, expect } from 'vitest';

// Mirrors static/js/onboarding.js's obGroupItemsByRole.
const OB_ROLES_ORDER = ['employee', 'manager', 'hr_admin', 'hr_manager'];
function obGroupItemsByRole(items) {
  const roles = [...OB_ROLES_ORDER];
  items.forEach(i => { if (!roles.includes(i.assigned_role)) roles.push(i.assigned_role); });
  const grouped = {};
  roles.forEach(r => grouped[r] = []);
  items.forEach(i => grouped[i.assigned_role].push(i));
  return { roles, grouped };
}

describe('Checklist detail — grouping items by role', () => {
  const items = [
    { id: 1, assigned_role: 'hr_manager' },
    { id: 2, assigned_role: 'it_infra' },
    { id: 3, assigned_role: 'hr_admin' },
    { id: 4, assigned_role: 'it_infra' },
    { id: 5, assigned_role: 'facilities' },
  ];

  it('shows every item, including those held by a custom role', () => {
    const { roles, grouped } = obGroupItemsByRole(items);
    const shown = roles.reduce((n, r) => n + grouped[r].length, 0);
    expect(shown).toBe(items.length);
  });

  it('lists the classic roles first, then custom roles in the order first seen', () => {
    expect(obGroupItemsByRole(items).roles).toEqual(['employee', 'manager', 'hr_admin', 'hr_manager', 'it_infra', 'facilities']);
  });

  it('keeps just the classic roles when no custom role holds an item', () => {
    expect(obGroupItemsByRole([{ id: 1, assigned_role: 'employee' }]).roles).toEqual(OB_ROLES_ORDER);
  });
});

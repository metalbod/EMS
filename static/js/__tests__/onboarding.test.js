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

// Mirrors static/js/onboarding.js's template-board helpers.
let rolesCache = [];
function obBoardRoles(items) {
  const roles = [...OB_ROLES_ORDER];
  rolesCache.forEach(r => { if (!roles.includes(r.role_key)) roles.push(r.role_key); });
  items.forEach(i => { if (!roles.includes(i.assigned_role)) roles.push(i.assigned_role); });
  return roles;
}
function obApplyDrop(items, dragId, targetRole, beforeId) {
  const moved = items.find(i => i.id === dragId);
  if (!moved) return items.map(i => ({ id: i.id, assigned_role: i.assigned_role }));
  const rest = items.filter(i => i.id !== dragId).map(i => ({ id: i.id, assigned_role: i.assigned_role }));
  const entry = { id: dragId, assigned_role: targetRole };
  let at = beforeId == null ? -1 : rest.findIndex(i => i.id === beforeId);
  if (at < 0) {
    let last = -1;
    rest.forEach((i, n) => { if (i.assigned_role === targetRole) last = n; });
    at = last >= 0 ? last + 1 : rest.length;
  }
  rest.splice(at, 0, entry);
  return rest;
}
function obLayoutChanged(items, layout) {
  return layout.some((l, n) => items[n].id !== l.id || items[n].assigned_role !== l.assigned_role);
}

describe('Template board — columns', () => {
  it('always lists the classic roles, then every other institution role, then orphaned item roles', () => {
    rolesCache = [{ role_key: 'hr_manager' }, { role_key: 'payroll_manager' }, { role_key: 'it_infra' }];
    expect(obBoardRoles([{ id: 1, assigned_role: 'gone_role' }])).toEqual(
      ['employee', 'manager', 'hr_admin', 'hr_manager', 'payroll_manager', 'it_infra', 'gone_role']);
  });
  it('shows classic roles even with no items and no role cache', () => {
    rolesCache = [];
    expect(obBoardRoles([])).toEqual(OB_ROLES_ORDER);
  });
});

describe('Template board — drop logic', () => {
  const items = [
    { id: 1, assigned_role: 'hr_admin' },
    { id: 2, assigned_role: 'manager' },
    { id: 3, assigned_role: 'hr_admin' },
    { id: 4, assigned_role: 'hr_admin' },
  ];
  const ids = l => l.map(x => x.id);

  it('reorders inside a column: drop item 4 before item 3', () => {
    const out = obApplyDrop(items, 4, 'hr_admin', 3);
    expect(ids(out)).toEqual([1, 2, 4, 3]);
    expect(out.every(x => x.assigned_role === items.find(i => i.id === x.id).assigned_role)).toBe(true);
  });
  it('drops at the bottom of its own column when no card is below', () => {
    expect(ids(obApplyDrop(items, 1, 'hr_admin', null))).toEqual([2, 3, 4, 1]);
  });
  it('hands an item to another column, placed before the chosen card', () => {
    const out = obApplyDrop([...items, { id: 5, assigned_role: 'manager' }], 3, 'manager', 5);
    expect(out.find(x => x.id === 3).assigned_role).toBe('manager');
    expect(ids(out)).toEqual([1, 2, 4, 3, 5]);
  });
  it('drops into an empty column and changes only that item\'s role', () => {
    const out = obApplyDrop(items, 2, 'it_infra', null);
    expect(out.find(x => x.id === 2).assigned_role).toBe('it_infra');
    expect(out.filter(x => x.id !== 2).map(x => x.assigned_role)).toEqual(['hr_admin', 'hr_admin', 'hr_admin']);
  });
  it('dropping a card back where it was is a no-op', () => {
    expect(obLayoutChanged(items, obApplyDrop(items, 3, 'hr_admin', 4))).toBe(false);
    expect(obLayoutChanged(items, obApplyDrop(items, 4, 'hr_admin', null))).toBe(false);
  });
  it('a real change is detected', () => {
    expect(obLayoutChanged(items, obApplyDrop(items, 4, 'hr_admin', 1))).toBe(true);
  });
});

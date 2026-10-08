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

// Mirrors static/js/onboarding.js's dependency helpers.
function obComputeRows(items) {
  const rows = {}, taken = {};
  let pending = [...items], progressed = true;
  while (pending.length && progressed) {
    progressed = false;
    pending = pending.filter(it => {
      const pre = (it.depends_on || []).filter(id => items.some(x => x.id === id));
      if (pre.some(id => rows[id] === undefined)) return true;
      let row = pre.length ? Math.max(...pre.map(id => rows[id])) + 1 : 0;
      taken[it.assigned_role] = taken[it.assigned_role] || new Set();
      while (taken[it.assigned_role].has(row)) row++;
      taken[it.assigned_role].add(row);
      rows[it.id] = row; progressed = true; return false;
    });
  }
  let bottom = Math.max(-1, ...Object.values(rows)) + 1;
  pending.forEach(it => { rows[it.id] = bottom++; });
  return rows;
}
function obStartsAfter(items, id, targetId) {
  const byId = new Map(items.map(i => [i.id, i]));
  const seen = new Set(), stack = [id];
  while (stack.length) {
    const n = stack.pop();
    if (n === targetId && n !== id) return true;
    if (seen.has(n)) continue;
    seen.add(n);
    (byId.get(n)?.depends_on || []).forEach(p => stack.push(p));
  }
  return false;
}

describe('Template board — dependency layout', () => {
  const mk = (id, role, dep = []) => ({ id, assigned_role: role, depends_on: dep });

  it('puts every item without prerequisites at the top of its own column', () => {
    const rows = obComputeRows([mk(1, 'employee'), mk(2, 'manager'), mk(3, 'hr_admin')]);
    expect(rows).toEqual({ 1: 0, 2: 0, 3: 0 });
  });

  it('stacks independent items of one role in list order', () => {
    expect(obComputeRows([mk(1, 'hr_admin'), mk(2, 'hr_admin'), mk(3, 'hr_admin')])).toEqual({ 1: 0, 2: 1, 3: 2 });
  });

  it('places a dependent card below all its prerequisites, across columns', () => {
    const rows = obComputeRows([mk(1, 'hr_manager'), mk(2, 'manager', [1]), mk(3, 'it_infra', [2]), mk(4, 'employee', [1, 3])]);
    expect(rows).toEqual({ 1: 0, 2: 1, 3: 2, 4: 3 });
  });

  it('bumps a card down when its target cell is taken', () => {
    const rows = obComputeRows([mk(1, 'hr_manager'), mk(2, 'hr_admin', [1]), mk(3, 'hr_admin', [1])]);
    expect(rows).toEqual({ 1: 0, 2: 1, 3: 2 });
  });

  it('handles an item listed before its prerequisite', () => {
    const rows = obComputeRows([mk(2, 'manager', [1]), mk(1, 'hr_admin')]);
    expect(rows).toEqual({ 1: 0, 2: 1 });
  });

  it('ignores links to items that are not on the board and never loses a card', () => {
    expect(obComputeRows([mk(1, 'employee', [99])])).toEqual({ 1: 0 });
    const looped = obComputeRows([mk(1, 'employee', [2]), mk(2, 'manager', [1])]);
    expect(Object.keys(looped).length).toBe(2);
  });
});

describe('Template board — loop detection', () => {
  const items = [
    { id: 1, depends_on: [] },
    { id: 2, depends_on: [1] },
    { id: 3, depends_on: [2] },
    { id: 4, depends_on: [] },
  ];
  it('sees a chain', () => {
    expect(obStartsAfter(items, 3, 1)).toBe(true);
    expect(obStartsAfter(items, 1, 3)).toBe(false);
  });
  it('unrelated items never start after each other', () => {
    expect(obStartsAfter(items, 4, 1)).toBe(false);
  });
  it('linking 1 after 3 would loop, linking 4 after 3 would not', () => {
    // "to starts after from" is a loop when `from` already starts after `to`.
    expect(obStartsAfter(items, 3, 1)).toBe(true);   // from=3,to=1
    expect(obStartsAfter(items, 3, 4)).toBe(false);  // from=3,to=4
  });
});

// Mirrors static/js/onboarding.js's obWaitingForLabel.
const obRoleLabel = r => ({ manager: 'Manager', hr_admin: 'HR Admin' }[r] || r);
function obWaitingForLabel(list) {
  return (list || []).map(w => w.title || `a ${obRoleLabel(w.assigned_role)} task`).join(', ');
}

describe('Checklist detail — waiting-for label', () => {
  it('names the unfinished prerequisites', () => {
    expect(obWaitingForLabel([{ title: 'Return laptop', assigned_role: 'hr_admin' }, { title: 'Exit interview', assigned_role: 'manager' }]))
      .toBe('Return laptop, Exit interview');
  });
  it('hides a title the server withheld, naming only the role', () => {
    expect(obWaitingForLabel([{ title: null, assigned_role: 'manager' }])).toBe('a Manager task');
  });
  it('is empty when nothing is outstanding', () => {
    expect(obWaitingForLabel([])).toBe('');
    expect(obWaitingForLabel(undefined)).toBe('');
  });
});

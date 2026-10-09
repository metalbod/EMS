import { describe, it, expect } from 'vitest';

// Mirrors static/js/leave.js's leaveTypeTree.
function leaveTypeTree(types) {
  const byId = new Map(types.map(t => [t.id, t]));
  const children = new Map();
  const roots = [];
  types.forEach(t => {
    const owner = t.shares_entitlement_with_id ? byId.get(t.shares_entitlement_with_id) : null;
    if (owner) { if (!children.has(owner.id)) children.set(owner.id, []); children.get(owner.id).push(t); }
    else roots.push(t);
  });
  const rows = [];
  roots.forEach(t => {
    const kids = children.get(t.id) || [];
    rows.push({ type: t, indent: false, sharedBy: kids.length });
    kids.forEach(k => rows.push({ type: k, indent: true, sharedBy: 0 }));
  });
  return rows;
}

const T = (id, name, shares = null) => ({ id, name, shares_entitlement_with_id: shares });
const names = rows => rows.map(r => (r.indent ? '  ' : '') + r.type.name);

describe('Leave types list — sharing types under their pool', () => {
  it('puts each sharing type, indented, right under its pool and keeps the list order otherwise', () => {
    const types = [T(1, 'Annual'), T(2, 'Emergency', 1), T(3, 'Medical'), T(4, 'Hospital', 3), T(5, 'Unpaid', 1), T(6, 'Study')];
    expect(names(leaveTypeTree(types))).toEqual(['Annual', '  Emergency', '  Unpaid', 'Medical', '  Hospital', 'Study']);
  });

  it('counts how many types share a pool', () => {
    const rows = leaveTypeTree([T(1, 'Annual'), T(2, 'A', 1), T(3, 'B', 1), T(4, 'Study')]);
    expect(rows.map(r => r.sharedBy)).toEqual([2, 0, 0, 0]);
  });

  it('a sharing type whose pool is missing stays at the top level', () => {
    const rows = leaveTypeTree([T(2, 'Orphan', 99), T(3, 'Solo')]);
    expect(rows.map(r => r.indent)).toEqual([false, false]);
    expect(rows.length).toBe(2);
  });

  it('every type appears exactly once', () => {
    const types = [T(1, 'A'), T(2, 'B', 1), T(3, 'C', 1), T(4, 'D', 9)];
    expect(leaveTypeTree(types).length).toBe(types.length);
  });
});

import { describe, it, expect } from 'vitest';

// Mirrors static/js/orgchart.js's renderOrgChart's internal layout()
// function — the tree's box-positioning algorithm. Root (depth 0) still
// spreads its own children (depth 1, direct reports) horizontally, same
// as before this feature; from depth 1 on, a node lays ITS OWN children
// out in a vertical, indented column instead, so depth 2 (grandchildren)
// and everything deeper cascades downward rather than spreading sideways —
// this is what actually keeps a large org's chart from growing extremely
// wide past the first two rows.
const NODE_W = 180, NODE_H = 70, GAP_X = 30, GAP_Y = 60;
const VERTICAL_FROM_DEPTH = 1;
const V_GAP_Y = 14, V_INDENT = 44;

function layout(pos, children, id, x, y, depth) {
  const kids = children[id] || [];
  pos[id] = { x, y };
  if (!kids.length) return { w: NODE_W, h: NODE_H };

  if (depth < VERTICAL_FROM_DEPTH) {
    let totalW = 0, maxKidH = 0;
    const childY = y + NODE_H + GAP_Y;
    kids.forEach(kid => {
      const { w, h } = layout(pos, children, kid, x + totalW, childY, depth + 1);
      totalW += w + GAP_X;
      if (h > maxKidH) maxKidH = h;
    });
    totalW -= GAP_X;
    const center = x + totalW / 2 - NODE_W / 2;
    pos[id] = { x: center, y };
    return { w: totalW, h: NODE_H + GAP_Y + maxKidH };
  }

  let curY = y + NODE_H + V_GAP_Y;
  let maxRight = x + NODE_W;
  kids.forEach(kid => {
    const { w, h } = layout(pos, children, kid, x + V_INDENT, curY, depth + 1);
    curY += h + V_GAP_Y;
    if (x + V_INDENT + w > maxRight) maxRight = x + V_INDENT + w;
  });
  return { w: maxRight - x, h: curY - V_GAP_Y - y };
}

function runLayout(childrenMap, rootId) {
  const pos = {};
  layout(pos, childrenMap, rootId, 0, 0, 0);
  return pos;
}

describe('Org Chart tree — depth-based horizontal/vertical layout', () => {
  it('still spreads the root\'s direct reports horizontally (same y, distinct x)', () => {
    const children = { root: ['a', 'b', 'c'] };
    const pos = runLayout(children, 'root');
    expect(pos.a.y).toBe(pos.b.y);
    expect(pos.b.y).toBe(pos.c.y);
    expect(pos.a.x).toBeLessThan(pos.b.x);
    expect(pos.b.x).toBeLessThan(pos.c.x);
  });

  it('stacks a direct report\'s own children vertically instead of spreading them', () => {
    const children = { root: ['mgr'], mgr: ['g1', 'g2', 'g3'] };
    const pos = runLayout(children, 'root');
    // Same indent (x), strictly increasing y, one below the other
    expect(pos.g1.x).toBe(pos.mgr.x + V_INDENT);
    expect(pos.g2.x).toBe(pos.mgr.x + V_INDENT);
    expect(pos.g3.x).toBe(pos.mgr.x + V_INDENT);
    expect(pos.g2.y).toBeGreaterThan(pos.g1.y);
    expect(pos.g3.y).toBeGreaterThan(pos.g2.y);
  });

  it('never overlaps two stacked siblings vertically', () => {
    const children = { root: ['mgr'], mgr: ['g1', 'g2'] };
    const pos = runLayout(children, 'root');
    expect(pos.g2.y).toBeGreaterThanOrEqual(pos.g1.y + NODE_H + V_GAP_Y);
  });

  it('keeps cascading vertically for great-grandchildren, indented one step further', () => {
    const children = { root: ['mgr'], mgr: ['g1'], g1: ['gg1', 'gg2'] };
    const pos = runLayout(children, 'root');
    expect(pos.gg1.x).toBe(pos.g1.x + V_INDENT);
    expect(pos.gg1.x).toBe(pos.mgr.x + V_INDENT * 2);
    expect(pos.gg2.y).toBeGreaterThan(pos.gg1.y);
  });

  it('sibling direct-report branches of different depths don\'t collide horizontally', () => {
    // "mgrA" has a deep vertical chain; "mgrB" is a childless leaf — mgrB
    // must still land to the right of mgrA's whole subtree width, not
    // just mgrA's own box, since mgrA's reported width includes its
    // indented vertical descendants.
    const children = { root: ['mgrA', 'mgrB'], mgrA: ['g1', 'g2', 'g3', 'g4'] };
    const pos = runLayout(children, 'root');
    const mgrARightEdge = pos.mgrA.x + V_INDENT + NODE_W;
    expect(pos.mgrB.x).toBeGreaterThanOrEqual(mgrARightEdge);
  });
});

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL pure helpers from ld.js's Policies section.
const src = readFileSync(resolve(__dirname, '..', 'ld.js'), 'utf8');
const fn = name => {
  const start = src.indexOf(`function ${name}(`);
  expect(start).toBeGreaterThan(-1);
  return src.slice(start, src.indexOf('\n}\n', start) + 2);
};
const { policyAudienceLabel, policyProgressPct, policyTrackerRows, policyLinkHost } = new Function(
  `${fn('policyAudienceLabel')}${fn('policyProgressPct')}${fn('policyTrackerRows')}${fn('policyLinkHost')}
   return { policyAudienceLabel, policyProgressPct, policyTrackerRows, policyLinkHost };`)();

describe('policy helpers', () => {
  it('labels each audience type', () => {
    expect(policyAudienceLabel('all')).toBe('All employees');
    expect(policyAudienceLabel('department', 'Sales')).toBe('Department: Sales');
    expect(policyAudienceLabel('people')).toBe('Named people');
    expect(policyAudienceLabel('team', 'A001', id => (id === 'A001' ? 'Davent Low' : null))).toBe('Team of Davent Low');
    expect(policyAudienceLabel('team', 'A001')).toBe('Team of A001');
  });

  it('computes a whole-number progress percentage and never divides by zero', () => {
    expect(policyProgressPct(50, 31)).toBe(62);
    expect(policyProgressPct(3, 1)).toBe(33);
    expect(policyProgressPct(0, 0)).toBe(0);
  });

  it('shows just the host of a link, and falls back to the raw text', () => {
    expect(policyLinkHost('https://company.sharepoint.com/sites/hr/Handbook.pdf?v=3')).toBe('company.sharepoint.com');
    expect(policyLinkHost('not a url')).toBe('not a url');
    expect(policyLinkHost(null)).toBe('');
  });

  it('filters tracker rows into outstanding / acknowledged / all', () => {
    const rows = [{ status: 'acknowledged' }, { status: 'overdue' }, { status: 'opened' }, { status: 'not_opened' }];
    expect(policyTrackerRows(rows, 'outstanding').map(r => r.status)).toEqual(['overdue', 'opened', 'not_opened']);
    expect(policyTrackerRows(rows, 'acknowledged').map(r => r.status)).toEqual(['acknowledged']);
    expect(policyTrackerRows(rows, 'all')).toHaveLength(4);
  });
});

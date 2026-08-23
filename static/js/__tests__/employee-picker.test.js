import { describe, it, expect } from 'vitest';

// Matches employee-picker.js's filterEmployeeOptions — the pure filtering
// logic behind initEmployeeSearchSelect, the shared searchable-dropdown
// helper used everywhere a <select> lists employees (Start Onboarding,
// Reports To, Approval Workflow's specific-employee step, L&D enrollment,
// Apply Leave on behalf of, Total Rewards, User Management's linked
// employee) — institutions can have 100+ employees, so every one of these
// now filters by a search box instead of forcing a scroll through the
// whole roster.
describe('Employee search picker — option filtering', () => {
  function filterEmployeeOptions(options, query) {
    const q = (query || '').trim().toLowerCase();
    return options.filter(o => o.label.toLowerCase().includes(q));
  }

  const options = [
    { value: '', label: 'Select employee…' },
    { value: 'A001', label: 'A001 — Davent Low' },
    { value: 'A002', label: 'A002 — Kenneth Yong' },
    { value: '', label: 'None (Top Level)' },
    { value: 'SELF', label: '⭐ Self (CEO / Top of Org)' },
  ];

  it('matches case-insensitively against the option label', () => {
    const rows = filterEmployeeOptions(options, 'kenneth');
    expect(rows.map(o => o.value)).toEqual(['A002']);
  });

  it('matches a substring anywhere in the label, not just a prefix', () => {
    const rows = filterEmployeeOptions(options, 'yong');
    expect(rows.map(o => o.value)).toEqual(['A002']);
  });

  it('a pinned non-employee option (e.g. "Self (CEO...)") is matchable by its own label like anyone else', () => {
    const rows = filterEmployeeOptions(options, 'self');
    expect(rows.map(o => o.value)).toEqual(['SELF']);
  });

  it('a blank-value option that is a *meaningful* choice (e.g. fReportsTo\'s "None (Top Level)") stays reachable by typing its label — not conflated with a "please select…" placeholder just because both happen to share value=""', () => {
    const rows = filterEmployeeOptions(options, 'level');
    expect(rows.map(o => o.label)).toEqual(['None (Top Level)']);
  });

  it('an empty query returns every option, including placeholder/blank-value ones — a harmless redundancy, not a bug', () => {
    const rows = filterEmployeeOptions(options, '');
    expect(rows).toHaveLength(options.length);
  });

  it('a query with no matches returns an empty list', () => {
    const rows = filterEmployeeOptions(options, 'zzznomatch');
    expect(rows).toHaveLength(0);
  });

  it('trims surrounding whitespace from the query before matching', () => {
    const rows = filterEmployeeOptions(options, '  kenneth  ');
    expect(rows.map(o => o.value)).toEqual(['A002']);
  });
});

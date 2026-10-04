import { describe, it, expect } from 'vitest';

// Mirrors static/js/ai-assistant-settings.js's Usage tab helpers.
function _isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function aiUsageDateRange(preset, today = new Date()) {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const start = new Date(end);
  if (preset === 'this_month') start.setDate(1);
  else if (preset === 'last_30') start.setDate(start.getDate() - 29);
  else if (preset === 'last_90') start.setDate(start.getDate() - 89);
  else return { date_from: '2000-01-01', date_to: _isoDate(end) };
  return { date_from: _isoDate(start), date_to: _isoDate(end) };
}

function sortAiUsageRows(rows, sort) {
  const dir = sort.dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = a[sort.key], y = b[sort.key];
    const cmp = typeof x === 'string' ? x.localeCompare(y) : (x - y);
    return cmp * dir || a.name.localeCompare(b.name);
  });
}

describe('AI usage — date range presets', () => {
  const today = new Date(2026, 9, 4); // 4 Oct 2026 (local)

  it('this month starts on the 1st and ends today', () => {
    expect(aiUsageDateRange('this_month', today)).toEqual({ date_from: '2026-10-01', date_to: '2026-10-04' });
  });

  it('last 30 days is 30 calendar days inclusive of today', () => {
    expect(aiUsageDateRange('last_30', today)).toEqual({ date_from: '2026-09-05', date_to: '2026-10-04' });
  });

  it('last 90 days crosses month boundaries correctly', () => {
    expect(aiUsageDateRange('last_90', today)).toEqual({ date_from: '2026-07-07', date_to: '2026-10-04' });
  });

  it('all time starts at a fixed early date and ends today', () => {
    expect(aiUsageDateRange('all', today)).toEqual({ date_from: '2000-01-01', date_to: '2026-10-04' });
  });
});

describe('AI usage — table sorting', () => {
  const rows = [
    { name: 'Bala', total_tokens: 50, chat_tokens: 50 },
    { name: 'Amy', total_tokens: 900, chat_tokens: 100 },
    { name: 'Chen', total_tokens: 50, chat_tokens: 10 },
  ];

  it('sorts numeric columns descending by default, ties broken by name', () => {
    expect(sortAiUsageRows(rows, { key: 'total_tokens', dir: 'desc' }).map(r => r.name)).toEqual(['Amy', 'Bala', 'Chen']);
  });

  it('sorts ascending', () => {
    expect(sortAiUsageRows(rows, { key: 'chat_tokens', dir: 'asc' }).map(r => r.name)).toEqual(['Chen', 'Bala', 'Amy']);
  });

  it('sorts by name alphabetically', () => {
    expect(sortAiUsageRows(rows, { key: 'name', dir: 'asc' }).map(r => r.name)).toEqual(['Amy', 'Bala', 'Chen']);
  });

  it('does not mutate the input array', () => {
    const copy = rows.map(r => r.name);
    sortAiUsageRows(rows, { key: 'total_tokens', dir: 'desc' });
    expect(rows.map(r => r.name)).toEqual(copy);
  });
});

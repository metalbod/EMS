import { describe, it, expect } from 'vitest';

// Matches leave.js's ldLeaveHalfDayDeduction and ldHalfDaySuffix — the
// pure client-side half-day (AM/PM) preview and display logic behind the
// Apply for Leave modal's Start Day / End Day selectors. The server-side
// equivalent is routers/leave.py's _half_day_deduction; this mirrors its
// 0 / 0.5 / 1.0 arithmetic for the live "≈ N day(s) will be deducted"
// preview, since the server recomputes independently and is authoritative.
describe('Leave half-day preview — day-count deduction', () => {
  function ldLeaveHalfDayDeduction(start, end, startPeriod, endPeriod) {
    let deduction = 0;
    if (startPeriod) deduction += 0.5;
    if (endPeriod && end !== start) deduction += 0.5;
    return deduction;
  }

  it('a full-day range with no periods set deducts nothing', () => {
    expect(ldLeaveHalfDayDeduction('2027-03-01', '2027-03-05', '', '')).toBe(0);
  });

  it('a single-day range with only startPeriod set deducts half a day', () => {
    expect(ldLeaveHalfDayDeduction('2027-03-01', '2027-03-01', 'AM', '')).toBe(0.5);
  });

  it('a multi-day range with both start and end periods set deducts a full day', () => {
    expect(ldLeaveHalfDayDeduction('2027-03-01', '2027-03-05', 'PM', 'AM')).toBe(1.0);
  });

  it('a multi-day range with only endPeriod set deducts half a day', () => {
    expect(ldLeaveHalfDayDeduction('2027-03-01', '2027-03-05', '', 'AM')).toBe(0.5);
  });

  it('endPeriod is ignored on a single-day range (start===end), matching the backend/DB constraint', () => {
    // The UI is expected to keep the End Day selector hidden/blank in this
    // case, but the pure function itself stays correct even if called with
    // a stray endPeriod value — it never double-counts a single date.
    expect(ldLeaveHalfDayDeduction('2027-03-01', '2027-03-01', '', 'AM')).toBe(0);
  });
});

describe('Leave half-day display — list suffix formatting', () => {
  function ldHalfDaySuffix(a) {
    const parts = [];
    if (a.start_day_period) parts.push(`${a.start_day_period} start`);
    if (a.end_day_period) parts.push(`${a.end_day_period} end`);
    return parts.length ? ` (${parts.join(', ')})` : '';
  }

  it('a full-day application (neither period set) has no suffix', () => {
    expect(ldHalfDaySuffix({ start_day_period: null, end_day_period: null })).toBe('');
  });

  it('a start-only half-day shows just the start period', () => {
    expect(ldHalfDaySuffix({ start_day_period: 'PM', end_day_period: null })).toBe(' (PM start)');
  });

  it('both start and end half-days show both, comma-separated', () => {
    expect(ldHalfDaySuffix({ start_day_period: 'PM', end_day_period: 'AM' })).toBe(' (PM start, AM end)');
  });
});

// Matches leave.js's shiftDateByOneYear — the date-shift behind "Populate
// Next Year" (Holiday Manager). Proposes next year's holidays by moving each
// of this year's dates forward by exactly one year (same month/day); the
// review modal lets HR correct any row before it's actually added, which
// matters for lunar/Islamic-calendar holidays (Chinese New Year, Hari Raya,
// Deepavali, ...) that don't fall on the same date every year.
describe('Populate Next Year — date-shift helper (shiftDateByOneYear)', () => {
  function shiftDateByOneYear(dateStr) {
    const [y, m, d] = dateStr.split('-').map(Number);
    const targetYear = y + 1;
    const isLeap = (targetYear % 4 === 0 && targetYear % 100 !== 0) || targetYear % 400 === 0;
    const day = (m === 2 && d === 29 && !isLeap) ? 28 : d;
    return `${targetYear}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }

  it('shifts a fixed-date holiday forward by exactly one year', () => {
    expect(shiftDateByOneYear('2026-08-31')).toBe('2027-08-31');
  });

  it('shifts Jan 1 correctly across the year boundary', () => {
    expect(shiftDateByOneYear('2026-01-01')).toBe('2027-01-01');
  });

  it('Feb 29 falls back to Feb 28 the following year (consecutive leap years never occur, so this is the only real case)', () => {
    expect(shiftDateByOneYear('2028-02-29')).toBe('2029-02-28');
  });

  it('a plain Feb 28 (non-leap source) shifts to Feb 28, untouched by the leap-year fallback', () => {
    expect(shiftDateByOneYear('2027-02-28')).toBe('2028-02-28');
  });
});

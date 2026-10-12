import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL localDateStr (core.js) and ldLeaveComputeWorkdays (leave.js) with the
// process time zone set to Malaysia (UTC+8), where toISOString().slice(0,10) used to
// return the previous day for local midnight and for the first 8 hours of every day.
const read = f => readFileSync(resolve(__dirname, '..', f), 'utf8');
const fnSource = (src, name) => {
  const start = src.indexOf(`function ${name}(`);
  const end = src.indexOf('\n}\n', start);
  expect(start).toBeGreaterThan(-1);
  return src.slice(start, end + 2);
};

let oldTz;
beforeAll(() => { oldTz = process.env.TZ; process.env.TZ = 'Asia/Kuala_Lumpur'; });
afterAll(() => { if (oldTz === undefined) delete process.env.TZ; else process.env.TZ = oldTz; });

const localDateStr = () => new Function(`${fnSource(read('core.js'), 'localDateStr')}\nreturn localDateStr;`)();

describe('localDateStr', () => {
  it('keeps local midnight on its own calendar day (the toISOString bug)', () => {
    const d = new Date(2026, 9, 5); // Mon 5 Oct 2026 00:00 local
    expect(d.toISOString().slice(0, 10)).toBe('2026-10-04'); // documents the bug being avoided
    expect(localDateStr()(d)).toBe('2026-10-05');
  });

  it('keeps an early-morning "now" on today, and pads month/day', () => {
    expect(localDateStr()(new Date(2026, 0, 3, 1, 30))).toBe('2026-01-03');
  });
});

describe('ldLeaveComputeWorkdays', () => {
  const compute = holidays => new Function('leaveHolidaysCache', 'localDateStr',
    `${fnSource(read('leave.js'), 'ldLeaveComputeWorkdays')}\nreturn ldLeaveComputeWorkdays;`)(
    holidays.map(date => ({ date })), localDateStr());

  it('excludes a holiday on the day it falls, not the day before', () => {
    // Mon 5 - Fri 9 Oct 2026, holiday Wed 7 Oct -> 4 working days
    expect(compute([ '2026-10-07' ])('2026-10-05', '2026-10-09')).toBe(4);
  });

  it('a holiday on the first day of the range is excluded', () => {
    expect(compute([ '2026-10-05' ])('2026-10-05', '2026-10-09')).toBe(4);
  });

  it('a holiday the day after the range does not affect it', () => {
    expect(compute([ '2026-10-10' ])('2026-10-05', '2026-10-09')).toBe(5);
  });

  it('skips weekends', () => {
    expect(compute([])('2026-10-05', '2026-10-11')).toBe(5);
  });
});

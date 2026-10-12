import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL ldScoreSummary from ld.js.
const src = readFileSync(resolve(__dirname, '..', 'ld.js'), 'utf8');
const start = src.indexOf('function ldScoreSummary(');
const fn = src.slice(start, src.indexOf('\n}\n', start) + 2);
const ldScoreSummary = new Function(`${fn}\nreturn ldScoreSummary;`)();

describe('ldScoreSummary', () => {
  it('shows a dash for a course with no quiz', () => {
    expect(ldScoreSummary({ quiz_id: null })).toMatchObject({ label: '—', tone: 'none', clickable: false });
  });

  it('says "Not attempted" before the first try, with how many attempts are allowed', () => {
    expect(ldScoreSummary({ quiz_id: 1, attempts_used: 0, quiz_max_attempts: 3 }))
      .toMatchObject({ label: 'Not attempted', detail: '3 attempts allowed', tone: 'none', clickable: false });
  });

  it('shows the best score as Passed once any attempt passed', () => {
    expect(ldScoreSummary({ quiz_id: 1, attempts_used: 2, quiz_max_attempts: 3, best_score: 100, passed_any: 1 }))
      .toMatchObject({ label: '100% · Passed', detail: '2 of 3 attempts used', tone: 'pass', clickable: true });
  });

  it('shows Not passed with the attempts left, and says so when none are left', () => {
    expect(ldScoreSummary({ quiz_id: 1, attempts_used: 1, quiz_max_attempts: 3, best_score: 60, passed_any: null }))
      .toMatchObject({ label: '60% · Not passed', detail: '2 attempts left', tone: 'fail' });
    expect(ldScoreSummary({ quiz_id: 1, attempts_used: 2, quiz_max_attempts: 3, best_score: 60, passed_any: 0 }).detail).toBe('1 attempt left');
    expect(ldScoreSummary({ quiz_id: 1, attempts_used: 3, quiz_max_attempts: 3, best_score: 60, passed_any: 0 }).detail).toBe('No attempts left');
  });
});

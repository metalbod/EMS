import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL ldQuizOutcome from ld.js.
const src = readFileSync(resolve(__dirname, '..', 'ld.js'), 'utf8');
const start = src.indexOf('function ldQuizOutcome(');
const fn = src.slice(start, src.indexOf('\n}\n', start) + 2);
const ldQuizOutcome = new Function(`${fn}\nreturn ldQuizOutcome;`)();

const base = { score: 60, correct: 3, total: 5, pass_threshold: 80, required_correct: 4, attempt_number: 1, max_attempts: 3, attempts_remaining: 2, incorrect_question_ids: [11, 13], passed: false };

describe('ldQuizOutcome', () => {
  it('a pass shows the score against the pass mark and that the course is complete', () => {
    const o = ldQuizOutcome({ ...base, passed: true, score: 80, correct: 4, incorrect_question_ids: [] });
    expect(o.headline).toBe('Passed');
    expect(o.passed).toBe(true);
    expect(o.lines[0]).toBe('You scored 80% (4 of 5 correct). The pass mark is 80%.');
    expect(o.lines[1]).toMatch(/marked complete/);
    expect(o.canRetake).toBe(false);
  });

  it('a fail says why, which questions to review (by the numbers shown) and how many tries are left', () => {
    const numbers = { 11: 2, 13: 4 };
    const o = ldQuizOutcome(base, id => numbers[id]);
    expect(o.headline).toBe('Not passed');
    expect(o.lines[0]).toBe('You scored 60% (3 of 5 correct). The pass mark is 80%.');
    expect(o.lines[1]).toBe('You needed at least 4 of 5 correct to pass, so you will need to retake the quiz.');
    expect(o.lines).toContain('Questions to review: 2, 4.');
    expect(o.lines[o.lines.length - 1]).toBe('Attempt 1 of 3 used — you have 2 attempts left.');
    expect(o.canRetake).toBe(true);
  });

  it('uses the singular for one attempt left, and points to HR when none are left', () => {
    expect(ldQuizOutcome({ ...base, attempts_remaining: 1, attempt_number: 2 }, id => id).lines.pop()).toBe('Attempt 2 of 3 used — you have 1 attempt left.');
    const none = ldQuizOutcome({ ...base, attempts_remaining: 0, attempt_number: 3 }, id => id);
    expect(none.lines.pop()).toBe('You have used all 3 attempts. Please contact HR to arrange another attempt.');
    expect(none.canRetake).toBe(false);
  });

  it('sorts the review numbers and skips questions it cannot number', () => {
    const o = ldQuizOutcome({ ...base, incorrect_question_ids: [5, 9, 7] }, id => ({ 5: 3, 9: 1, 7: null })[id]);
    expect(o.lines).toContain('Questions to review: 1, 3.');
  });
});

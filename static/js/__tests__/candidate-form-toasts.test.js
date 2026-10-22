import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL candFormProblems / showCandFormProblems (recruitment.js) and showToast
// (core.js): saving an Add Candidate form with something wrong reports every problem as a
// fading pop-up, whichever tab the problem is on.
const read = f => readFileSync(resolve(__dirname, '..', f), 'utf8');
const fnSource = (src, name) => {
  const start = src.indexOf(`function ${name}(`);
  const end = src.indexOf('\n}\n', start);
  expect(start).toBeGreaterThan(-1);
  return src.slice(start, end + 2);
};
const rec = read('recruitment.js');
const candFormProblems = new Function(`${fnSource(rec, 'candFormProblems')}\nreturn candFormProblems;`)();
const showToast = new Function(`${fnSource(read('core.js'), 'showToast')}\nreturn showToast;`)();

const ok = { full_name: 'Aida', email: 'aida@example.com', experience_years: '0', graduation_year: '', expected_salary: '', linkedin_url: '' };

describe('candFormProblems', () => {
  it('is empty for a valid form', () => {
    expect(candFormProblems(ok)).toEqual([]);
  });

  it('reports a missing email and name, in tab order, naming the field and tab', () => {
    const p = candFormProblems({ ...ok, full_name: '  ', email: '' });
    expect(p.map(x => x.msg)).toEqual(['Full Name is required', 'Email is required']);
    expect(p.every(x => x.tab === 'cm-personal')).toBe(true);
    expect(p[1].field).toBe('candEmail');
  });

  it('rejects the same malformed emails the server does', () => {
    for (const bad of ['no-at-sign', '@x.com', 'x@', 'a b@c.com']) {
      expect(candFormProblems({ ...ok, email: bad }).map(x => x.msg)).toContain('Email must be a valid email address');
    }
    expect(candFormProblems({ ...ok, email: ' a@b.co ' })).toEqual([]);
  });

  it('finds problems on the other tabs, so they are not silent', () => {
    const p = candFormProblems({ ...ok, experience_years: '-1', graduation_year: '1900', expected_salary: '-5', linkedin_url: 'linkedin.com/in/x' });
    expect(p.map(x => x.tab)).toEqual(['cm-employment', 'cm-education', 'cm-others', 'cm-others']);
    expect(p.map(x => x.field)).toEqual(['candExp', 'candGradYear', 'candExpSalary', 'candLinkedin']);
  });

  it('accepts blank optional fields and a good URL / year', () => {
    expect(candFormProblems({ ...ok, graduation_year: '2020', linkedin_url: 'https://linkedin.com/in/aida' })).toEqual([]);
  });
});

describe('showToast', () => {
  beforeEach(() => { document.body.innerHTML = ''; vi.useFakeTimers(); });

  it('shows the message as text (never markup), then fades and removes it', () => {
    showToast('<img src=x onerror=alert(1)> Email is required', 'error', 1000);
    const t = document.querySelector('#toastHost .toast');
    expect(t.textContent).toBe('<img src=x onerror=alert(1)> Email is required');
    expect(t.querySelector('img')).toBeNull();
    expect(t.getAttribute('role')).toBe('alert');
    vi.advanceTimersByTime(1000);
    expect(t.classList.contains('toast-out')).toBe(true);
    vi.advanceTimersByTime(400);
    expect(document.querySelector('#toastHost .toast')).toBeNull();
  });

  it('stacks several at once and clicking one dismisses it early', () => {
    showToast('one'); showToast('two');
    const toasts = document.querySelectorAll('#toastHost .toast');
    expect(toasts.length).toBe(2);
    toasts[0].click();
    vi.advanceTimersByTime(400);
    expect(document.querySelectorAll('#toastHost .toast').length).toBe(1);
  });

  it('ignores an empty message', () => {
    showToast('');
    expect(document.getElementById('toastHost')).toBeNull();
  });
});

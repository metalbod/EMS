import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL helpers from recruitment.js's Interviews table.
const src = readFileSync(resolve(__dirname, '..', 'recruitment.js'), 'utf8');
const fn = name => { const s = src.indexOf(`function ${name}(`); return src.slice(s, src.indexOf('\n}\n', s) + 2); };
const { fmtInterviewScore, interviewScoreTitle, interviewScoreChipsHtml } = new Function('esc',
  `${fn('fmtInterviewScore')}${fn('interviewScoreTitle')}${fn('interviewScoreChipsHtml')}
   return { fmtInterviewScore, interviewScoreTitle, interviewScoreChipsHtml };`)(s => String(s).replace(/</g, '&lt;'));

describe('interview score display', () => {
  it('shows whole numbers plain and averages to one decimal', () => {
    expect(fmtInterviewScore(4)).toBe('4');
    expect(fmtInterviewScore(4.5)).toBe('4.5');
    expect(fmtInterviewScore(3.6667)).toBe('3.7');
    expect(fmtInterviewScore(null)).toBe('—');
  });

  it('lists one chip per interviewer who scored, with their name and score', () => {
    const html = interviewScoreChipsHtml([
      { scored_by: 'ahmad', scored_by_name: 'Ahmad Tan', score: 4, technical_score: 5, recommendation: 'Yes' },
      { scored_by: 'siti', scored_by_name: null, score: 2.5 },
    ]);
    expect(html.match(/<span class="inline-flex/g)).toHaveLength(2);
    expect(html).toContain('Ahmad Tan');
    expect(html).toContain('<b class="font-semibold">4</b>');
    expect(html).toContain('siti');                       // falls back to the username
    expect(html).toContain('<b class="font-semibold">2.5</b>');
  });

  it('says "Not scored yet" when nobody has scored, and escapes names', () => {
    expect(interviewScoreChipsHtml([])).toContain('Not scored yet');
    expect(interviewScoreChipsHtml(null)).toContain('Not scored yet');
    expect(interviewScoreChipsHtml([{ scored_by: 'x', scored_by_name: '<b>x</b>', score: 3 }])).not.toContain('<b>x</b>');
  });

  it('the hover text names the criteria that were scored and the recommendation', () => {
    expect(interviewScoreTitle({ technical_score: 5, communication_score: null, attitude_score: 4, recommendation: 'Yes' }))
      .toBe('Technical 5 · Attitude 4 · Recommendation: Yes');
  });
});

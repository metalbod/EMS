import { describe, it, expect } from 'vitest';

// Matches onboarding.js's renderObProbationPanel — maps an appraisal's
// status (shared with the standard Performance engine — Self -> Manager
// -> Calibration -> Final) to the label shown on each Month 1/2/3 card.
describe('Probation Review panel — status label mapping', () => {
  function statusLabel(r) {
    return r.appraisal_status === 'Finalized' ? `Final rating: ${r.final_rating ?? '—'}/5`
      : r.appraisal_status === 'Calibration' ? 'Awaiting HR finalization'
      : r.appraisal_status === 'ManagerReview' ? 'Awaiting manager review'
      : 'Awaiting self-review';
  }

  it('shows "Awaiting self-review" for a freshly created review', () => {
    expect(statusLabel({ appraisal_status: 'SelfReview' })).toBe('Awaiting self-review');
  });

  it('shows "Awaiting manager review" once the employee has self-reviewed', () => {
    expect(statusLabel({ appraisal_status: 'ManagerReview' })).toBe('Awaiting manager review');
  });

  it('shows "Awaiting HR finalization" once the manager has reviewed', () => {
    expect(statusLabel({ appraisal_status: 'Calibration' })).toBe('Awaiting HR finalization');
  });

  it('shows the final rating once HR has closed the cycle', () => {
    expect(statusLabel({ appraisal_status: 'Finalized', final_rating: 4 })).toBe('Final rating: 4/5');
  });

  it('falls back to an em dash if a Finalized review somehow has no rating', () => {
    expect(statusLabel({ appraisal_status: 'Finalized', final_rating: null })).toBe('Final rating: —/5');
  });
});

// Matches performance.js's populateCycleSelect — a company accumulates many
// Closed cycles over time (standard org-wide ones, plus 3 per employee per
// probation review), so every cycle dropdown (My Goals, Team Appraisals,
// Calibration) defaults to hiding them, with a "Show closed" checkbox to
// opt back in per page.
describe('Performance cycle dropdown — hiding Closed cycles by default', () => {
  function visibleCycles(cycles, showClosed) {
    return showClosed ? cycles : cycles.filter(c => c.status !== 'Closed');
  }

  const cycles = [
    { id: 1, name: 'H1 2026', status: 'Active' },
    { id: 2, name: 'Probation Review — Month 1 — Jane Doe', status: 'Closed' },
    { id: 3, name: 'Probation Review — Month 2 — Jane Doe', status: 'Active' },
    { id: 4, name: 'zz Test Cycle H1 2026', status: 'Calibration' },
  ];

  it('hides Closed cycles by default', () => {
    const visible = visibleCycles(cycles, false);
    expect(visible.map(c => c.id)).toEqual([1, 3, 4]);
  });

  it('includes Closed cycles once the "Show closed" checkbox is on', () => {
    const visible = visibleCycles(cycles, true);
    expect(visible.map(c => c.id)).toEqual([1, 2, 3, 4]);
  });

  it('never filters out non-Closed statuses (Active, Calibration) regardless of the toggle', () => {
    expect(visibleCycles(cycles, false).every(c => c.status !== 'Closed')).toBe(true);
    expect(visibleCycles(cycles, false)).toHaveLength(3);
  });
});

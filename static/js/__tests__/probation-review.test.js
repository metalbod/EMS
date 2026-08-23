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

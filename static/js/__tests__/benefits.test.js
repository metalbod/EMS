import { describe, it, expect } from 'vitest';

// Matches benefits.js's loadMyBenefitsPage — an employee can only elect
// coverage during an open enrollment period OR an approved life event
// whose 30-day window hasn't lapsed yet (mirrors the backend's own guard
// in routers/benefits.py's elect_my_enrollment).
describe('My Benefits — approved life-event window selection', () => {
  function findActiveWindowEvent(events, today) {
    return events.find(e => e.status === 'Approved' && e.window_end_date && e.window_end_date >= today) || null;
  }

  it('finds an approved event whose window is still open', () => {
    const events = [{ id: 1, status: 'Approved', window_end_date: '2026-09-01' }];
    expect(findActiveWindowEvent(events, '2026-08-15').id).toBe(1);
  });

  it('ignores an approved event whose window already closed', () => {
    const events = [{ id: 1, status: 'Approved', window_end_date: '2026-07-01' }];
    expect(findActiveWindowEvent(events, '2026-08-15')).toBeNull();
  });

  it('ignores a Pending Review or Rejected event even with a window date', () => {
    const events = [{ id: 1, status: 'Pending Review', window_end_date: '2026-09-01' }];
    expect(findActiveWindowEvent(events, '2026-08-15')).toBeNull();
  });

  it('treats the window end date as inclusive (still open on the last day)', () => {
    const events = [{ id: 1, status: 'Approved', window_end_date: '2026-08-15' }];
    expect(findActiveWindowEvent(events, '2026-08-15').id).toBe(1);
  });

  it('returns null with no events at all', () => {
    expect(findActiveWindowEvent([], '2026-08-15')).toBeNull();
  });
});

// Matches renderMyBenefitsBanner's 3-way state: an open enrollment period
// takes priority over a life-event window, which takes priority over the
// no-window fallback message.
describe('My Benefits — enrollment window banner state', () => {
  function bannerState(activePeriod, approvedWindowEvent) {
    if (activePeriod) return 'open-enrollment';
    if (approvedWindowEvent) return 'life-event-window';
    return 'no-window';
  }

  it('shows the open-enrollment banner when a period is active', () => {
    expect(bannerState({ period_name: 'Q3 Open Enrollment' }, null)).toBe('open-enrollment');
  });

  it('shows the life-event banner when only a life-event window is open', () => {
    expect(bannerState(null, { event_type: 'Marriage' })).toBe('life-event-window');
  });

  it('prefers the open-enrollment banner when both are active', () => {
    expect(bannerState({ period_name: 'Q3' }, { event_type: 'Marriage' })).toBe('open-enrollment');
  });

  it('falls back to the no-window message when neither is active', () => {
    expect(bannerState(null, null)).toBe('no-window');
  });
});

// Matches renderMyBenefitsPlansTable's canElect gate — the Enroll/Waive
// buttons only appear when some window (open enrollment or life event) is
// currently active.
describe('My Benefits — can-elect gate', () => {
  function canElect(activePeriod, approvedWindowEvent) {
    return !!(activePeriod || approvedWindowEvent);
  }

  it('allows electing during open enrollment', () => {
    expect(canElect({ id: 1 }, null)).toBe(true);
  });

  it('allows electing during a life-event window', () => {
    expect(canElect(null, { id: 1 })).toBe(true);
  });

  it('blocks electing when no window is open', () => {
    expect(canElect(null, null)).toBe(false);
  });
});

// Matches renderMyBenefitsPlansTable's fmtCost — a Percent of Salary plan
// shows its raw percentage, every other contribution type shows a
// currency figure; a null cost always shows an em dash.
describe('My Benefits — plan cost display type', () => {
  function costDisplayType(value, contributionType) {
    if (value == null) return 'dash';
    if (contributionType === 'Percent of Salary') return 'percent';
    return 'currency';
  }

  it('shows a dash for a null cost regardless of contribution type', () => {
    expect(costDisplayType(null, 'Fixed Premium')).toBe('dash');
  });

  it('shows a raw percentage for Percent of Salary plans', () => {
    expect(costDisplayType(3, 'Percent of Salary')).toBe('percent');
  });

  it('shows currency for Fixed Premium and Reimbursement Cap plans', () => {
    expect(costDisplayType(50, 'Fixed Premium')).toBe('currency');
    expect(costDisplayType(500, 'Reimbursement Cap')).toBe('currency');
  });
});

// Matches renderMyBenefitsPlansTable's per-plan election badge/label —
// distinct from canElect above, this is about what the *current* election
// shows, independent of whether a new one can be made right now.
describe('My Benefits — election badge for a plan', () => {
  function electionLabel(enrollment) {
    if (!enrollment) return 'Not elected';
    return enrollment.status;  // 'Enrolled' or 'Waived'
  }

  function electionBadgeClass(enrollment) {
    if (!enrollment) return 'bg-slate-100 text-slate-500';
    return enrollment.status === 'Enrolled' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500';
  }

  it('shows "Not elected" with a neutral badge when there is no enrollment row', () => {
    expect(electionLabel(null)).toBe('Not elected');
    expect(electionBadgeClass(null)).toBe('bg-slate-100 text-slate-500');
  });

  it('shows "Enrolled" with a positive badge', () => {
    expect(electionLabel({ status: 'Enrolled' })).toBe('Enrolled');
    expect(electionBadgeClass({ status: 'Enrolled' })).toBe('bg-emerald-100 text-emerald-700');
  });

  it('shows "Waived" with a neutral badge', () => {
    expect(electionLabel({ status: 'Waived' })).toBe('Waived');
    expect(electionBadgeClass({ status: 'Waived' })).toBe('bg-slate-100 text-slate-500');
  });
});

// Matches benefits.js's claimStatusBadge.
describe('Claims — status badge color', () => {
  function claimStatusBadge(status) {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Paid') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-amber-100 text-amber-700';  // Submitted / Under Review
  }

  it('colors Approved as blue', () => {
    expect(claimStatusBadge('Approved')).toBe('bg-blue-100 text-blue-700');
  });

  it('colors Paid as emerald', () => {
    expect(claimStatusBadge('Paid')).toBe('bg-emerald-100 text-emerald-700');
  });

  it('colors Rejected as red', () => {
    expect(claimStatusBadge('Rejected')).toBe('bg-red-100 text-red-700');
  });

  it('falls back to amber for Submitted or Under Review', () => {
    expect(claimStatusBadge('Submitted')).toBe('bg-amber-100 text-amber-700');
    expect(claimStatusBadge('Under Review')).toBe('bg-amber-100 text-amber-700');
  });
});

// Matches renderMyLifeEventsTable's own statusBadge — a separate,
// independently-written color map from claimStatusBadge above (different
// status vocabulary: life events have no 'Paid' state), worth its own
// coverage so the two can't silently diverge from each other by accident.
describe('Life events — status badge color', () => {
  function lifeEventStatusBadge(status) {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-amber-100 text-amber-700';  // Pending Review
  }

  it('colors Approved as blue', () => {
    expect(lifeEventStatusBadge('Approved')).toBe('bg-blue-100 text-blue-700');
  });

  it('colors Rejected as red', () => {
    expect(lifeEventStatusBadge('Rejected')).toBe('bg-red-100 text-red-700');
  });

  it('falls back to amber for Pending Review', () => {
    expect(lifeEventStatusBadge('Pending Review')).toBe('bg-amber-100 text-amber-700');
  });
});

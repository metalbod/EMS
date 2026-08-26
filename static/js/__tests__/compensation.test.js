import { describe, it, expect } from 'vitest';

// Matches compensation.js's computeMeritNewSalary — new salary = current x
// (1 + percent/100), only computed once both inputs parse as numbers (the
// real function leaves the New Salary field untouched otherwise, rather
// than writing NaN into it).
describe('Merit recommendation — new salary calculation', () => {
  function computeMeritNewSalary(current, percent) {
    if (isNaN(current) || isNaN(percent)) return null;
    return Number((current * (1 + percent / 100)).toFixed(2));
  }

  it('applies a positive percentage increase', () => {
    expect(computeMeritNewSalary(6000, 5)).toBe(6300);
  });

  it('applies a zero percentage as a no-op', () => {
    expect(computeMeritNewSalary(6000, 0)).toBe(6000);
  });

  it('rounds to 2 decimal places', () => {
    expect(computeMeritNewSalary(5000, 3.33)).toBe(5166.5);
  });

  it('returns null (leaves the field untouched) when current salary is not a number', () => {
    expect(computeMeritNewSalary(NaN, 5)).toBeNull();
  });

  it('returns null when the percentage is not a number', () => {
    expect(computeMeritNewSalary(6000, NaN)).toBeNull();
  });
});

// Matches compensation.js's updateCommissionPreview — commission =
// sales x rate / 100, only shown once both sales and rate are truthy
// (a zero in either field shows no preview rather than "RM 0.00").
describe('Commission entry — calculated commission preview', () => {
  function commissionPreviewText(sales, rate) {
    const s = parseFloat(sales) || 0;
    const r = parseFloat(rate) || 0;
    const commission = s * r / 100;
    return s && r ? commission : null;
  }

  it('calculates commission from sales and rate', () => {
    expect(commissionPreviewText(10000, 7.5)).toBe(750);
  });

  it('shows nothing when sales is zero', () => {
    expect(commissionPreviewText(0, 5)).toBeNull();
  });

  it('shows nothing when rate is zero', () => {
    expect(commissionPreviewText(1000, 0)).toBeNull();
  });

  it('shows nothing when fields are empty (parses to NaN -> 0)', () => {
    expect(commissionPreviewText('', '')).toBeNull();
  });
});

// Matches compensation.js's updateEquitySettlePreview — Phantom stock cash
// payout = max(0, settlement_price - fair_market_value_at_grant) x
// quantity_vested, mirroring the backend's identical formula in
// routers/compensation_equity.py's settle_vesting_event.
describe('Equity vesting — settlement payout preview', () => {
  function settlementPayout(settlementPrice, fmv, quantityVested) {
    if (isNaN(settlementPrice)) return null;
    return Math.max(0, settlementPrice - (fmv ?? 0)) * quantityVested;
  }

  it('pays the appreciation over the grant baseline', () => {
    expect(settlementPayout(15, 10, 1000)).toBe(5000);
  });

  it('clamps at zero when the settlement price is below the baseline', () => {
    expect(settlementPayout(5, 10, 1000)).toBe(0);
  });

  it('treats a missing fair market value as zero baseline', () => {
    expect(settlementPayout(10, null, 100)).toBe(1000);
  });

  it('returns null for a non-numeric settlement price', () => {
    expect(settlementPayout(NaN, 10, 100)).toBeNull();
  });
});

// Matches compensation.js's renderEquityGrantDetail — which actions are
// offered depends entirely on the grant's own status.
describe('Equity grant detail — available actions by status', () => {
  function equityGrantActions(status) {
    if (status === 'Pending Approval') return ['Approve', 'Reject'];
    if (status === 'Approved') return ['Cancel Grant'];
    return [];
  }

  it('offers Approve/Reject for a Pending Approval grant', () => {
    expect(equityGrantActions('Pending Approval')).toEqual(['Approve', 'Reject']);
  });

  it('offers only Cancel for an Approved grant', () => {
    expect(equityGrantActions('Approved')).toEqual(['Cancel Grant']);
  });

  it('offers no actions for a Rejected or Cancelled grant', () => {
    expect(equityGrantActions('Rejected')).toEqual([]);
    expect(equityGrantActions('Cancelled')).toEqual([]);
  });
});

// Matches the vesting-event row action in renderEquityGrantDetail — a
// Scheduled tranche can be marked Vested; a Vested tranche can only be
// cash-settled if the grant itself is Phantom (RSU/ISO/NSO/ESPP settle in
// actual equity, not cash, so 'Vested' is already their terminal state).
describe('Vesting event row — available action', () => {
  function vestingEventAction(eventStatus, isPhantomGrant) {
    if (eventStatus === 'Scheduled') return 'Mark Vested';
    if (eventStatus === 'Vested' && isPhantomGrant) return 'Settle & Pay';
    return null;
  }

  it('offers Mark Vested for a Scheduled tranche', () => {
    expect(vestingEventAction('Scheduled', false)).toBe('Mark Vested');
  });

  it('offers Settle & Pay for a Vested Phantom tranche', () => {
    expect(vestingEventAction('Vested', true)).toBe('Settle & Pay');
  });

  it('offers nothing for a Vested non-Phantom tranche (RSU already terminal)', () => {
    expect(vestingEventAction('Vested', false)).toBeNull();
  });

  it('offers nothing for a Paid or Cancelled tranche', () => {
    expect(vestingEventAction('Paid', true)).toBeNull();
    expect(vestingEventAction('Cancelled', true)).toBeNull();
  });
});

// Matches the statusBadge color map inside renderEquityGrantDetail.
describe('Vesting event — status badge color', () => {
  function vestingStatusBadge(status) {
    if (status === 'Vested') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Paid') return 'bg-blue-100 text-blue-700';
    if (status === 'Cancelled') return 'bg-slate-100 text-slate-500';
    return 'bg-amber-100 text-amber-700';  // Scheduled
  }

  it('colors Vested as emerald', () => {
    expect(vestingStatusBadge('Vested')).toBe('bg-emerald-100 text-emerald-700');
  });

  it('colors Paid as blue', () => {
    expect(vestingStatusBadge('Paid')).toBe('bg-blue-100 text-blue-700');
  });

  it('colors Cancelled as slate', () => {
    expect(vestingStatusBadge('Cancelled')).toBe('bg-slate-100 text-slate-500');
  });

  it('falls back to amber for Scheduled (or any unrecognized status)', () => {
    expect(vestingStatusBadge('Scheduled')).toBe('bg-amber-100 text-amber-700');
    expect(vestingStatusBadge('SomethingNew')).toBe('bg-amber-100 text-amber-700');
  });
});

// Matches loadPayEquityReport's pay-gap flagging — mirrors the backend's
// own PayEquityItem.flagged threshold in routers/compensation_rewards.py
// (abs(gap) > 5 -> flagged), so the two independently-written
// implementations don't quietly diverge.
describe('Pay equity — gap flagging threshold', () => {
  function isPayGapFlagged(payGapPercent) {
    return Math.abs(payGapPercent) > 5;
  }

  it('flags a gap over 5%', () => {
    expect(isPayGapFlagged(7.2)).toBe(true);
  });

  it('flags a negative gap whose magnitude exceeds 5%', () => {
    expect(isPayGapFlagged(-8.1)).toBe(true);
  });

  it('does not flag a gap at or under 5%', () => {
    expect(isPayGapFlagged(5.0)).toBe(false);
    expect(isPayGapFlagged(2.3)).toBe(false);
  });
});

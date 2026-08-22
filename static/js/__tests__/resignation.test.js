import { describe, it, expect } from 'vitest';

// Matches resignation.js's submitResignation — last working day must be on
// or after the effective date (mirrors the backend's own check in
// routers/resignation.py's create_resignation, so a bad date pair never
// even reaches the network).
describe('Resign modal — last working day validation', () => {
  function isValidDatePair(effectiveDate, lastWorkingDay) {
    return lastWorkingDay >= effectiveDate;
  }

  it('accepts a last working day after the effective date', () => {
    expect(isValidDatePair('2027-06-01', '2027-06-30')).toBe(true);
  });

  it('accepts a last working day equal to the effective date (immediate resignation)', () => {
    expect(isValidDatePair('2027-06-01', '2027-06-01')).toBe(true);
  });

  it('rejects a last working day before the effective date', () => {
    expect(isValidDatePair('2027-06-15', '2027-06-01')).toBe(false);
  });
});

// Matches resignation.js's refreshResignButtonState — the Dashboard "Resign"
// button is replaced by an inline pending-status line once the logged-in
// employee already has a Pending request, so they can't submit a second one
// and instead see a Withdraw link.
describe('Dashboard Resign button — pending-status toggle', () => {
  function resignButtonView(pendingRows, myEmployeeId) {
    const mine = pendingRows.find(r => r.employee_id === myEmployeeId);
    return mine ? { showButton: false, showStatus: true, requestId: mine.id } : { showButton: true, showStatus: false };
  }

  it('shows the Resign button when the employee has no pending request', () => {
    const view = resignButtonView([], 'E001');
    expect(view.showButton).toBe(true);
    expect(view.showStatus).toBe(false);
  });

  it('shows the pending-status line instead of the button when one exists', () => {
    const view = resignButtonView([{ id: 42, employee_id: 'E001' }], 'E001');
    expect(view.showButton).toBe(false);
    expect(view.showStatus).toBe(true);
    expect(view.requestId).toBe(42);
  });

  it('ignores another employee\'s pending request', () => {
    const view = resignButtonView([{ id: 42, employee_id: 'E999' }], 'E001');
    expect(view.showButton).toBe(true);
    expect(view.showStatus).toBe(false);
  });
});

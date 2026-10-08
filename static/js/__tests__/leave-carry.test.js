import { describe, it, expect } from 'vitest';

// Mirrors static/js/leave.js's carried-forward display helpers.
const fmtDate = s => s;
const leaveDaysUntil = d => d.__days;   // overridden per test via a fake below
function leaveCarryRemaining(b) { return Math.max(0, b.carried_forward_remaining ?? ((b.carried_forward_days || 0) - (b.carried_forward_used_days || 0))); }
function leaveCarryUsableFor(b, startDate) {
  const exp = b.carried_forward_expires_on;
  if (startDate && exp && startDate > exp) return 0;
  return leaveCarryRemaining(b) + (b.carried_forward_forfeited_days || 0);
}
function leaveAvailableFor(b, startDate) {
  const entitled = b.accrued_days ?? b.entitled_days;
  const regularUsed = (b.used_days || 0) - (b.carried_forward_used_days || 0);
  return leaveCarryUsableFor(b, startDate) + entitled - regularUsed;
}
function leaveCarryNote(b, daysUntil) {
  const left = leaveCarryRemaining(b);
  const exp = b.carried_forward_expires_on;
  if (left > 0) return { text: `${left} carried forward${exp ? ` · use by ${fmtDate(exp)}` : ''}`, urgent: !!exp && daysUntil <= 30 };
  const lost = b.carried_forward_forfeited_days || 0;
  if (lost > 0) return { text: `${lost} carried-forward day(s) forfeited`, urgent: false };
  return null;
}

const base = { entitled_days: 10, accrued_days: 10, carried_forward_days: 3, carried_forward_used_days: 1, used_days: 4, carried_forward_forfeited_days: 0, carried_forward_expires_on: '2027-06-29' };

describe('carried-forward balance helpers', () => {
  it('remaining is carried minus used, never negative; prefers the server field', () => {
    expect(leaveCarryRemaining(base)).toBe(2);
    expect(leaveCarryRemaining({ carried_forward_days: 1, carried_forward_used_days: 3 })).toBe(0);
    expect(leaveCarryRemaining({ ...base, carried_forward_remaining: 5 })).toBe(5);
  });

  it('carry is usable only for leave starting on or before the expiry', () => {
    expect(leaveCarryUsableFor(base, '2027-06-29')).toBe(2);
    expect(leaveCarryUsableFor(base, '2027-06-30')).toBe(0);
    expect(leaveCarryUsableFor(base, null)).toBe(2);
  });

  it('available days = usable carry + entitlement - regular days already used', () => {
    expect(leaveAvailableFor(base, '2027-06-01')).toBe(2 + 10 - 3);    // regular used = 4 - 1
    expect(leaveAvailableFor(base, '2027-08-01')).toBe(10 - 3);        // carry not usable
  });

  it('days the sweep forfeited count again for earlier leave', () => {
    const swept = { ...base, carried_forward_days: 1, carried_forward_used_days: 1, carried_forward_forfeited_days: 2, carried_forward_remaining: 0 };
    expect(leaveCarryUsableFor(swept, '2027-06-10')).toBe(2);
  });

  it('note: shows what is left and when it expires, urgent in the last 30 days', () => {
    expect(leaveCarryNote(base, 90)).toEqual({ text: '2 carried forward · use by 2027-06-29', urgent: false });
    expect(leaveCarryNote(base, 12).urgent).toBe(true);
  });

  it('note: after expiry shows the forfeited days; none at all shows nothing', () => {
    const lapsed = { ...base, carried_forward_days: 1, carried_forward_used_days: 1, carried_forward_forfeited_days: 2 };
    expect(leaveCarryNote(lapsed, -5).text).toBe('2 carried-forward day(s) forfeited');
    expect(leaveCarryNote({ ...base, carried_forward_days: 0, carried_forward_used_days: 0 }, 0)).toBeNull();
  });
});

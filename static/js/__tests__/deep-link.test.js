import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL deep-link.js and list-state.js (plain global-scope scripts) in
// a function scope, so the tests exercise the code that ships.
const read = f => readFileSync(resolve(__dirname, '..', f), 'utf8');
const dl = new Function(`${read('deep-link.js')}
return { setPendingFocus, pendingFocusId, clearPendingFocus, showPageNotice, clearPageNotice, applyFocus, openFocusedRecord, focusOpensModal };`)();
const { createListState } = new Function(`${read('list-state.js')}\nreturn { createListState };`)();

const notice = page => document.querySelector(`[data-page-notice="${page}"]`);

beforeEach(() => {
  document.body.innerHTML = `
    <div id="page-leave-approvals"><table><tbody>
      <tr data-focus-id="11"><td><button id="b11">Approve</button></td></tr>
      <tr data-focus-id="12"><td><button id="b12">Approve</button></td></tr>
    </tbody></table></div>
    <div id="page-requisitions"></div>
    <div id="reqDetailModal" class="hidden"></div>`;
  dl.clearPendingFocus();
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => { vi.useRealTimers(); });

describe('pending focus', () => {
  it('belongs to the page it was set for, and any showPage without a focus clears it', () => {
    dl.setPendingFocus('leave-approvals', 12);
    expect(dl.pendingFocusId('leave-approvals')).toBe('12'); // ids are normalised to strings
    expect(dl.pendingFocusId('requisitions')).toBeNull();
    dl.setPendingFocus('leave-approvals', undefined); // what showPage(page) with no focus does
    expect(dl.pendingFocusId('leave-approvals')).toBeNull();
    dl.setPendingFocus('leave-approvals', 0);
    expect(dl.pendingFocusId('leave-approvals')).toBe('0'); // 0 is a real id, not "no focus"
    dl.setPendingFocus('leave-approvals', '');
    expect(dl.pendingFocusId('leave-approvals')).toBeNull();
  });
});

describe('applyFocus (list pages)', () => {
  it('highlights the target row, scrolls to it, moves focus to its first button, then clears the highlight', () => {
    vi.useFakeTimers();
    dl.setPendingFocus('leave-approvals', 12);
    expect(dl.applyFocus('leave-approvals')).toBe(true);
    const row = document.querySelector('[data-focus-id="12"]');
    expect(row.classList.contains('focus-target')).toBe(true);
    expect(document.querySelector('[data-focus-id="11"]').classList.contains('focus-target')).toBe(false);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(document.activeElement.id).toBe('b12');
    expect(notice('leave-approvals')).toBeNull(); // nothing to explain when it simply worked
    vi.advanceTimersByTime(4000);
    expect(row.classList.contains('focus-target')).toBe(false);
  });

  it('is a one-shot: the pending target is consumed', () => {
    dl.setPendingFocus('leave-approvals', 11);
    dl.applyFocus('leave-approvals');
    expect(dl.pendingFocusId('leave-approvals')).toBeNull();
    expect(dl.applyFocus('leave-approvals')).toBe(false);
  });

  it('does nothing when there is no pending target for that page', () => {
    dl.setPendingFocus('requisitions', 5);
    expect(dl.applyFocus('leave-approvals')).toBe(false);
    expect(dl.pendingFocusId('requisitions')).toBe('5'); // someone else's target is left alone
  });

  it('says so — in words — when the row is not there (decided, deleted, filtered out)', () => {
    dl.setPendingFocus('leave-approvals', 999);
    expect(dl.applyFocus('leave-approvals')).toBe(false);
    expect(notice('leave-approvals').getAttribute('role')).toBe('status');
    expect(notice('leave-approvals').textContent).toMatch(/isn't in this list any more/);
    expect(document.querySelector('.focus-target')).toBeNull();
  });

  it('offers "Show all" when the page was narrowed to one record, and the action clears the notice and runs', () => {
    const showAll = vi.fn();
    dl.setPendingFocus('leave-approvals', 11);
    dl.applyFocus('leave-approvals', { showAll });
    expect(notice('leave-approvals').textContent).toContain('Showing only this request.');
    notice('leave-approvals').querySelector('.page-notice-action').click();
    expect(showAll).toHaveBeenCalledOnce();
    expect(notice('leave-approvals')).toBeNull();
  });

  it('does not match a row by prefix or by a hostile id', () => {
    dl.setPendingFocus('leave-approvals', '1');
    expect(dl.applyFocus('leave-approvals')).toBe(false); // "1" must not match 11 or 12
    dl.setPendingFocus('leave-approvals', '"] , button, [x="');
    expect(dl.applyFocus('leave-approvals')).toBe(false);
  });
});

describe('stale notices', () => {
  it('a later render with no pending target (e.g. the user changes a filter) retires the old notice', () => {
    dl.setPendingFocus('leave-approvals', 11);
    dl.applyFocus('leave-approvals', { showAll: () => {} });
    expect(notice('leave-approvals')).not.toBeNull();
    dl.applyFocus('leave-approvals'); // the list re-rendered for some other reason
    expect(notice('leave-approvals')).toBeNull();
  });
});

describe('page notices', () => {
  it('replaces rather than stacks, can be dismissed, and never renders text as HTML', () => {
    dl.showPageNotice('leave-approvals', '<img src=x onerror=alert(1)>');
    dl.showPageNotice('leave-approvals', 'second <b>bold</b>');
    expect(document.querySelectorAll('[data-page-notice="leave-approvals"]')).toHaveLength(1);
    expect(notice('leave-approvals').querySelector('img')).toBeNull();
    expect(notice('leave-approvals').querySelector('b')).toBeNull();
    expect(notice('leave-approvals').textContent).toContain('second <b>bold</b>');
    expect(notice('leave-approvals').querySelector('.page-notice-dismiss').getAttribute('aria-label')).toBe('Dismiss');
    notice('leave-approvals').querySelector('.page-notice-dismiss').click();
    expect(notice('leave-approvals')).toBeNull();
  });

  it('is a no-op for a page that is not in the document', () => {
    expect(() => dl.showPageNotice('nope', 'x')).not.toThrow();
  });
});

describe('openFocusedRecord (modal pages)', () => {
  it('opens the record by numeric id and reports success when the modal appears', async () => {
    globalThis.openReqDetail = vi.fn(async () => { document.getElementById('reqDetailModal').classList.remove('hidden'); });
    dl.setPendingFocus('requisitions', '42');
    expect(await dl.openFocusedRecord('requisitions')).toBe(true);
    expect(globalThis.openReqDetail).toHaveBeenCalledWith(42);
    expect(notice('requisitions')).toBeNull();
    expect(dl.pendingFocusId('requisitions')).toBeNull();
  });

  it('tells the user when the record could not be opened (fetch failed → modal stays hidden)', async () => {
    globalThis.openReqDetail = vi.fn(async () => {});
    dl.setPendingFocus('requisitions', 42);
    expect(await dl.openFocusedRecord('requisitions')).toBe(false);
    expect(notice('requisitions').textContent).toMatch(/couldn't be opened/);
  });

  it('survives an opener that throws', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    globalThis.openReqDetail = vi.fn(async () => { throw new Error('boom'); });
    dl.setPendingFocus('requisitions', 42);
    await expect(dl.openFocusedRecord('requisitions')).resolves.toBe(false);
    expect(notice('requisitions')).not.toBeNull();
    err.mockRestore();
  });

  it('knows which pages open a modal, and ignores pages that do not or have no pending target', async () => {
    for (const p of ['requisitions', 'perf-team', 'timesheet-approvals', 'onboarding', 'offboarding']) expect(dl.focusOpensModal(p)).toBe(true);
    for (const p of ['leave-approvals', 'ben-claims', 'resignation-approvals', 'ld-trainings', 'toString']) expect(dl.focusOpensModal(p)).toBe(false);
    expect(await dl.openFocusedRecord('requisitions')).toBe(false); // nothing pending
    expect(await dl.openFocusedRecord('leave-approvals')).toBe(false);
  });
});

describe('list-state showItem (paged lists land on the right page)', () => {
  const rows = Array.from({ length: 25 }, (_, i) => ({ id: i + 1, name: `n${String(i + 1).padStart(2, '0')}` }));

  it('moves to the page that holds the item in the CURRENT sort order', () => {
    const list = createListState({ sortKey: 'name', pageSize: 10 });
    expect(list.showItem(rows, r => r.id === 23)).toBe(true);
    expect(list.page).toBe(3);
    expect(list.view(rows).pageItems.map(r => r.id)).toContain(23);
    list.setSort('name'); // toggles to descending: item 23 is now near the front
    expect(list.showItem(rows, r => r.id === 23)).toBe(true);
    expect(list.page).toBe(1);
  });

  it('leaves the page alone and returns false when nothing matches', () => {
    const list = createListState({ sortKey: 'name', pageSize: 10 });
    list.nextPage(rows.length);
    expect(list.showItem(rows, r => r.id === 999)).toBe(false);
    expect(list.page).toBe(2);
  });
});

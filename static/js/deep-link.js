// Deep links
// ---------------------------------------------------------------------------
// The Home to-do links to the exact record: showPage(page, {focus: id}) records
// a pending target here, and the destination page then either
//   - opens the record (pages whose record view is a modal: requisitions,
//     timesheets + overtime, PIPs, onboarding/offboarding checklists), or
//   - scrolls to and highlights its row (list pages: leave, resignation,
//     claims, L&D enrollments — their rows carry data-focus-id="<id>"),
// and says so plainly when the record can't be found (already decided, deleted,
// hidden by a filter) instead of silently landing on a list.
//
// Plain global-scope script like the rest of the bundle; loaded before core.js.

let _pendingFocus = null; // { page, id: string } — consumed by the page that owns it

function setPendingFocus(page, id) {
  _pendingFocus = (id === undefined || id === null || id === '') ? null : { page, id: String(id) };
}
function pendingFocusId(page) {
  return _pendingFocus && _pendingFocus.page === page ? _pendingFocus.id : null;
}
function clearPendingFocus() { _pendingFocus = null; }

const _NOTICE_X_ICON = '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>';

function clearPageNotice(page) {
  document.querySelectorAll(`[data-page-notice="${page}"]`).forEach(el => el.remove());
}

// A small status line at the top of a page ("Showing only this request · Show
// all", or why a link couldn't land). Text goes in via textContent, never HTML.
function showPageNotice(page, text, action) {
  clearPageNotice(page);
  const host = document.getElementById(`page-${page}`);
  if (!host) return;
  const el = document.createElement('div');
  el.className = 'page-notice';
  el.setAttribute('role', 'status');
  el.dataset.pageNotice = page;
  const msg = document.createElement('span');
  msg.textContent = text;
  el.append(msg);
  if (action) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'pill-btn pill-btn-outline page-notice-action';
    b.textContent = action.label;
    b.addEventListener('click', () => { clearPageNotice(page); action.onClick(); });
    el.append(b);
  }
  const x = document.createElement('button');
  x.type = 'button';
  x.className = 'page-notice-dismiss';
  x.setAttribute('aria-label', 'Dismiss');
  x.innerHTML = _NOTICE_X_ICON;
  x.addEventListener('click', () => clearPageNotice(page));
  el.append(x);
  host.prepend(el);
}

const _FOCUS_MISSING = "That item isn't in this list any more — it may already have been decided, or a filter may be hiding it.";

// List pages call this right after they render their rows. Returns true when a
// pending target was found and highlighted. `showAll` (server-filtered pages
// only) adds a "Show all" action, since the list was narrowed to one record.
function applyFocus(page, { showAll } = {}) {
  const id = pendingFocusId(page);
  if (id === null) { clearPageNotice(page); return false; } // a later render (filter change) retires a stale notice
  clearPendingFocus();
  const host = document.getElementById(`page-${page}`);
  const row = host && [...host.querySelectorAll('[data-focus-id]')].find(el => el.dataset.focusId === id);
  if (!row) { showPageNotice(page, _FOCUS_MISSING); return false; }
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  row.classList.add('focus-target');
  row.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  row.querySelector('button, a[href]')?.focus({ preventScroll: true });
  setTimeout(() => row.classList.remove('focus-target'), 4000);
  if (showAll) showPageNotice(page, 'Showing only this request.', { label: 'Show all', onClick: showAll });
  return true;
}

// Pages whose record view is a modal that already opens a record by id.
const _FOCUS_MODALS = {
  requisitions: { open: id => openReqDetail(id), modal: 'reqDetailModal' },
  'perf-team': { open: id => openPipDetail(id), modal: 'pipDetailModal' },
  'timesheet-approvals': { open: id => openTimesheetDetail(id), modal: 'timesheetDetailModal' },
  onboarding: { open: id => openObDetail(id), modal: 'obDetailModal' },
  offboarding: { open: id => openObDetail(id), modal: 'obDetailModal' },
};
function focusOpensModal(page) { return Object.prototype.hasOwnProperty.call(_FOCUS_MODALS, page); }

async function openFocusedRecord(page) {
  const target = _FOCUS_MODALS[page];
  const id = pendingFocusId(page);
  if (!target || id === null) return false;
  clearPendingFocus();
  try { await target.open(Number(id)); } catch (e) { console.error(e); }
  const shown = !document.getElementById(target.modal)?.classList.contains('hidden');
  if (!shown) showPageNotice(page, "That record couldn't be opened — it may have been deleted, or you may no longer have access to it.");
  return shown;
}

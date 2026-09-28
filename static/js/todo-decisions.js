// Inline decisions on the Home to-do
// ---------------------------------------------------------------------------
// Leave requests and L&D enrollments can be approved or rejected straight from
// the "Needs your decision" table; every other kind of request keeps a plain
// "Review" link to its record (deep-link.js) because it needs more than one
// click to decide well — resignations start offboarding, claims need an
// approved amount checked against a cap, timesheets/overtime need their hours
// read. The calls are the same PATCH endpoints the Leave and L&D pages use
// (same permission and workflow checks — nothing is decided here that the
// server would not allow there), with an optional `notes` for a rejection.
//
// A decision may only ADVANCE a multi-step workflow (the request then waits on
// the next approver) and it emails the employee, so there is no undo and no
// optimistic removal: after every decision the whole list is re-fetched from
// /api/todos, which is the source of truth for what is still waiting on this
// user. Home-page state that must survive a re-render (which row has its
// reject reason open, the text typed so far, a row's error) lives in
// _todoDecisionUi, keyed by the to-do's `key`.
//
// Depends on dashboard.js (_todoItems, _renderTodos, loadDashboardTodos,
// _todoNav) and core.js (api, esc, apiErrorText). Plain global-scope script.

const _INLINE_DECISIONS = {
  leave: { url: id => `/api/leave/applications/${id}/status`, noun: 'leave request', approvedStatus: 'Approved' },
  ld_enrollment: { url: id => `/api/ld/enrollments/${id}/status`, noun: 'training enrollment', approvedStatus: 'In Progress' },
};

// key -> { mode: 'reject' | 'busy' | 'error', action: 'approve' | 'reject', reason, error }
const _todoDecisionUi = new Map();
let _todoResultTimer = null;

function todoDecisionSupported(t) {
  return t.kind === 'approval' && Object.prototype.hasOwnProperty.call(_INLINE_DECISIONS, t.module)
    && Number.isInteger(t.ref_id) && /^[\w-]+$/.test(String(t.key));
}

function _todoDecisionLabel(t) {
  return `${t.employee_name || 'the employee'}'s ${_INLINE_DECISIONS[t.module].noun}`;
}

function _todoFind(key) { return _todoItems.find(t => t.key === key && todoDecisionSupported(t)); }

// Approve / Reject / Details for one row. The Approve button is the filled one
// only on the highlighted row, like every other primary in the card.
function _todoDecisionActionsHtml(t, isUrgent) {
  const ui = _todoDecisionUi.get(t.key);
  const busy = ui?.mode === 'busy';
  const label = _todoDecisionLabel(t);
  const key = esc(t.key);
  const approveCls = isUrgent ? 'todo-action todo-action-primary' : 'todo-action pill-btn-outline';
  return `<span class="todo-decision-actions">
      <button type="button" class="pill-btn ${approveCls}" onclick="todoApprove('${key}')" ${busy ? 'disabled' : ''} aria-label="Approve ${esc(label)}">${busy && ui.action === 'approve' ? 'Approving…' : 'Approve'}</button>
      <button type="button" class="pill-btn todo-action todo-action-reject" data-todo-reject="${key}" onclick="todoRejectOpen('${key}')" aria-expanded="${ui?.action === 'reject' && ui?.mode !== 'error'}" aria-controls="todo-decision-${key}" ${busy ? 'disabled' : ''} aria-label="Reject ${esc(label)}">${busy && ui.action === 'reject' ? 'Rejecting…' : 'Reject'}</button>
      <button type="button" class="todo-link" onclick="${_todoNav(t.page, t.focus_id)}" aria-label="Open ${esc(label)} for details">Details</button>
    </span>`;
}

// The row under a request while its reject reason is open, or when its last
// attempt failed. Text goes through esc(); the typed reason is kept in
// _todoDecisionUi so a re-render never loses it.
function _todoDecisionPanelHtml(t) {
  const ui = _todoDecisionUi.get(t.key);
  if (!ui) return '';
  const key = esc(t.key);
  const rejecting = ui.action === 'reject' && ui.mode !== 'error';
  const busy = ui.mode === 'busy';
  const error = ui.error ? `<p class="todo-decision-error" role="alert">${esc(ui.error)}</p>` : '';
  if (!rejecting && !error) return '';
  const form = rejecting ? `
      <label class="todo-decision-label" for="todo-reason-${key}">Reason for rejecting ${esc(_todoDecisionLabel(t))} <span>(required)</span></label>
      <textarea id="todo-reason-${key}" class="inp todo-decision-reason" rows="2" maxlength="500" ${busy ? 'disabled' : ''}
        oninput="todoRejectInput('${key}', this.value)">${esc(ui.reason || '')}</textarea>
      <div class="todo-decision-buttons">
        <button type="button" class="pill-btn todo-action todo-action-danger" onclick="todoRejectConfirm('${key}')" ${busy ? 'disabled' : ''}>${busy ? 'Rejecting…' : 'Confirm reject'}</button>
        <button type="button" class="pill-btn todo-action pill-btn-outline" onclick="todoRejectCancel('${key}')" ${busy ? 'disabled' : ''}>Cancel</button>
      </div>` : '';
  return `<tr role="row" class="todo-decision-row" id="todo-decision-${key}"><td role="cell" colspan="5">${error}${form}</td></tr>`;
}

// Visible result line (auto-hides) + the screen-reader announcement.
function _todoAnnounce(message) {
  const live = document.getElementById('dashboardTodoLive');
  if (live) live.textContent = message;
  _todoResultPending = message; // the list refresh that follows speaks this, then its own summary
  const strip = document.getElementById('dashboardTodoResult');
  if (!strip) return;
  strip.textContent = message;
  strip.classList.remove('hidden');
  clearTimeout(_todoResultTimer);
  _todoResultTimer = setTimeout(() => strip.classList.add('hidden'), 8000);
}

function _todoFocusAnchor() {
  (document.getElementById('todo-decisions') || document.querySelector('#dashboardTodoCard h2'))?.focus({ preventScroll: true });
}

function todoRejectOpen(key) {
  const t = _todoFind(key);
  if (!t || _todoDecisionUi.get(key)?.mode === 'busy') return;
  const prev = _todoDecisionUi.get(key);
  _todoDecisionUi.set(key, { mode: 'reject', action: 'reject', reason: prev?.reason || '', error: '' });
  _renderTodos(`#todo-reason-${key}`);
}

function todoRejectInput(key, value) {
  const ui = _todoDecisionUi.get(key);
  if (ui) ui.reason = value; // no re-render: it would steal focus mid-typing
}

function todoRejectCancel(key) {
  if (_todoDecisionUi.get(key)?.mode === 'busy') return;
  _todoDecisionUi.delete(key);
  _renderTodos(`[data-todo-reject="${key}"]`);
}

function todoApprove(key) {
  const t = _todoFind(key);
  if (!t || _todoDecisionUi.get(key)?.mode === 'busy') return;
  return _submitTodoDecision(t, 'approve', '');
}

function todoRejectConfirm(key) {
  const t = _todoFind(key);
  const ui = _todoDecisionUi.get(key);
  if (!t || !ui || ui.mode === 'busy') return;
  const reason = (ui.reason || '').trim();
  if (!reason) {
    ui.error = 'Add a reason — it is saved with the request.';
    _renderTodos(`#todo-reason-${key}`);
    return;
  }
  return _submitTodoDecision(t, 'reject', reason);
}

async function _submitTodoDecision(t, action, notes) {
  const cfg = _INLINE_DECISIONS[t.module];
  const label = _todoDecisionLabel(t);
  const verb = action === 'approve' ? 'approve' : 'reject';
  _todoDecisionUi.set(t.key, { mode: 'busy', action, reason: notes, error: '' });
  _renderTodos();

  let res = null, threw = false;
  try {
    res = await api(cfg.url(t.ref_id), {
      method: 'PATCH',
      body: JSON.stringify(action === 'approve' ? { status: 'Approved' } : { status: 'Rejected', notes }),
    });
  } catch (e) { threw = true; }
  if (!threw && !res) return; // 401: api() has already started the logout flow

  if (res?.ok) {
    let row = null;
    try { row = await res.json(); } catch (e) { /* the decision went through either way */ }
    _todoDecisionUi.delete(t.key);
    _todoAnnounce(action === 'reject' ? `Rejected ${label}.`
      : row && row.status !== cfg.approvedStatus ? `Approved at your step — ${label} is now with the next approver.`
      : `Approved ${label}.`);
    await loadDashboardTodos();
    _todoFocusAnchor();
    return;
  }

  let detail = '';
  try { detail = apiErrorText((await res.json()).detail, ''); } catch (e) { /* no body */ }
  // Someone else got there first (or it was removed): nothing to retry.
  if (res && (res.status === 404 || (res.status === 400 && /already/i.test(detail)))) {
    _todoDecisionUi.delete(t.key);
    _todoAnnounce(`${label[0].toUpperCase()}${label.slice(1)} was already decided by someone else — your list has been refreshed.`);
    await loadDashboardTodos();
    _todoFocusAnchor();
    return;
  }

  const message = threw ? `Couldn't ${verb} ${label}. Check your connection and try again.`
    : res.status === 403 ? `You're not able to ${verb} ${label}${detail ? `: ${detail}` : '.'}`
    : `Couldn't ${verb} ${label}${detail ? `: ${detail}` : '. Please try again.'}`;
  // A failed reject keeps its reason open so nothing typed is lost.
  _todoDecisionUi.set(t.key, action === 'reject'
    ? { mode: 'reject', action, reason: notes, error: message }
    : { mode: 'error', action, reason: '', error: message });
  _renderTodos(action === 'reject' ? `#todo-reason-${t.key}` : null);
}

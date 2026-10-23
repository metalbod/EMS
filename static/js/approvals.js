// ---------------------------------------------------------------------------
// Approvals inbox — every request waiting on you, with the context to decide it
// ---------------------------------------------------------------------------
// GET /api/approvals lists the same approval rows as the Home to-do (one source of
// truth); GET /api/approvals/{module}/{ref_id}/context supplies the facts beside a
// request. Decisions go through each module's OWN endpoint (apprDecisionRequest) —
// the same PATCH/PUT calls the Leave, Timesheet, Claims … pages make — so every
// permission and workflow check stays where it was; nothing is decided here that
// those pages would refuse. A decision can only ADVANCE a multi-step workflow and
// emails the requester, so there is no undo and no optimistic removal: the list is
// re-fetched after every decision. Bulk approve is leave and L&D only (the two kinds
// whose decision is one plain call), and approve only — a rejection needs its reason.
//
// Depends on core.js (api, esc, apiErrorText, notify, showPage, currentPage),
// dashboard.js (_todoNav). Plain global-scope script.

const APPR_MODULE_LABELS = {
  leave: 'Leave', claims: 'Claims', requisition: 'Requisitions', timesheet: 'Timesheets',
  ld_enrollment: 'Training', overtime: 'Overtime', resignation: 'Resignations', pip: 'Improvement plans',
};
const APPR_NOUN = {
  leave: 'leave request', claims: 'claim', requisition: 'requisition', timesheet: 'timesheet',
  ld_enrollment: 'training enrollment', overtime: 'overtime request', resignation: 'resignation', pip: 'improvement plan',
};
const APPR_BULK_MODULES = ['leave', 'ld_enrollment'];

// The one call that decides a request, per module. Pure: no DOM, no fetch.
function apprDecisionRequest(t, action, notes) {
  const approve = action === 'approve';
  const status = approve ? 'Approved' : 'Rejected';
  const withNotes = approve ? { status } : { status, notes };
  switch (t.module) {
    case 'leave': return { method: 'PATCH', url: `/api/leave/applications/${t.ref_id}/status`, body: withNotes };
    case 'ld_enrollment': return { method: 'PATCH', url: `/api/ld/enrollments/${t.ref_id}/status`, body: withNotes };
    case 'timesheet':
      return t.project_row
        ? { method: 'PATCH', url: `/api/timesheets/${t.focus_id}/projects/${t.project_id}/status`, body: withNotes }
        : { method: 'PATCH', url: `/api/timesheets/${t.ref_id}/status`, body: withNotes };
    case 'overtime':
      return { method: 'PATCH', url: t.project_row ? `/api/overtime/projects/${t.ref_id}/status` : `/api/overtime/${t.ref_id}/status`, body: { status } };
    case 'claims': return { method: 'PUT', url: `/api/benefits/claims/${t.ref_id}/decide`, body: { status } };
    case 'requisition': return { method: 'PATCH', url: `/api/recruitment/requisitions/${t.ref_id}/approve`, body: { action, comments: approve ? undefined : notes } };
    case 'resignation': return { method: 'PATCH', url: `/api/resignations/${t.ref_id}`, body: withNotes };
    case 'pip': return { method: 'PATCH', url: `/api/performance/pip/${t.ref_id}/decide`, body: withNotes };
    default: return null;
  }
}

// A claim's decision has no field for a reason, so rejecting one never asks for it.
function apprNeedsReason(t) { return t.module !== 'claims'; }
function apprBulkEligible(t) { return APPR_BULK_MODULES.includes(t.module) && Number.isInteger(t.ref_id); }

function apprVisible(items, filter) {
  return filter === 'all' ? items : items.filter(t => t.module === filter);
}

// How long it has waited, in words (never by colour alone).
function apprAge(t) {
  if (t.days_overdue) return { text: `Overdue ${t.days_overdue} day${t.days_overdue === 1 ? '' : 's'}`, tone: 'overdue' };
  if (t.days_waiting == null) return { text: '', tone: 'none' };
  if (t.days_waiting === 0) return { text: 'Waiting since today', tone: 'waiting' };
  return { text: `Waiting ${t.days_waiting} day${t.days_waiting === 1 ? '' : 's'}`, tone: t.days_waiting >= 5 ? 'late' : 'waiting' };
}

const apprState = {
  items: [], counts: {}, filter: 'all', selected: null, checked: new Set(),
  ctx: new Map(), busy: false, reject: null, error: '', loaded: false, failed: false,
};

function apprSelectedItem() {
  return apprState.items.find(t => t.key === apprState.selected) || null;
}

// Nav badge + (for the plain employee role) whether the item shows at all. Called whenever a fresh list is known.
function updateApprovalsNav(count) {
  window._approvalsPending = count;
  const nav = document.getElementById('nav-approvals');
  const badge = document.getElementById('navApprovalsBadge');
  if (badge) { badge.textContent = count > 99 ? '99+' : String(count); badge.classList.toggle('hidden', !count); }
  if (nav && currentUser) {
    const hide = (currentUser.role === 'superadmin' && !currentInstitution) || (currentUser.role === 'employee' && !count);
    nav.classList.toggle('hidden', hide);
  }
}

async function loadApprovals(keepSelection = false) {
  const listEl = document.getElementById('apprList');
  if (!listEl) return;
  if (!apprState.loaded) listEl.innerHTML = '<p class="appr-empty">Loading…</p>';
  const prevIndex = apprState.items.findIndex(t => t.key === apprState.selected);
  const res = await api('/api/approvals');
  if (!res) return; // 401: api() has started the logout flow
  if (!res.ok) { apprState.failed = true; apprState.loaded = true; apprRender(); return; }
  const data = await res.json();
  apprState.failed = false;
  apprState.loaded = true;
  apprState.items = data.items || [];
  apprState.counts = data.counts || {};
  updateApprovalsNav(data.total || 0);
  // Forget anything that is no longer waiting on this person.
  const keys = new Set(apprState.items.map(t => t.key));
  apprState.checked = new Set([...apprState.checked].filter(k => keys.has(k)));
  for (const k of [...apprState.ctx.keys()]) if (!keys.has(k)) apprState.ctx.delete(k);
  if (apprState.filter !== 'all' && !apprState.counts[apprState.filter]) apprState.filter = 'all';
  const visible = apprVisible(apprState.items, apprState.filter);
  if (!keepSelection || !visible.some(t => t.key === apprState.selected)) {
    // after a decision, land on whatever now sits where the decided request was
    const next = visible[Math.min(Math.max(prevIndex, 0), visible.length - 1)];
    apprState.selected = next ? next.key : null;
    apprState.reject = null;
    apprState.error = '';
  }
  apprRender();
  apprEnsureContext();
}

async function apprEnsureContext() {
  const t = apprSelectedItem();
  if (!t || apprState.ctx.has(t.key)) return;
  apprState.ctx.set(t.key, 'loading');
  apprRenderDetail();
  const q = t.project_row ? '?project_row=true' : '';
  let ctx = 'error';
  try {
    const res = await api(`/api/approvals/${t.module}/${t.ref_id}/context${q}`);
    if (res && res.ok) ctx = await res.json();
    else if (res && res.status === 404) ctx = 'gone';
  } catch (e) { /* network: shown as an error line, the decision buttons still work */ }
  if (!apprStillListed(t)) return;
  apprState.ctx.set(t.key, ctx);
  if (apprState.selected === t.key) apprRenderDetail();
}
function apprStillListed(t) { return apprState.items.some(x => x.key === t.key); }

// ---- rendering --------------------------------------------------------------
function apprRender() {
  apprRenderFilters();
  apprRenderList();
  apprRenderDetail();
}

function apprRenderFilters() {
  const el = document.getElementById('apprFilters');
  if (!el) return;
  const total = apprState.items.length;
  const chips = [['all', 'All', total], ...Object.keys(APPR_MODULE_LABELS).filter(m => apprState.counts[m]).map(m => [m, APPR_MODULE_LABELS[m], apprState.counts[m]])];
  el.innerHTML = chips.map(([id, label, n]) =>
    `<button type="button" class="btn-ghost text-xs appr-chip${apprState.filter === id ? ' tab-active' : ''}" aria-pressed="${apprState.filter === id}" onclick="apprSetFilter('${id}')">${esc(label)} <span class="appr-chip-n">${n}</span></button>`).join('');
}

function apprSetFilter(id) {
  apprState.filter = id;
  const visible = apprVisible(apprState.items, id);
  if (!visible.some(t => t.key === apprState.selected)) { apprState.selected = visible[0]?.key || null; apprState.reject = null; apprState.error = ''; }
  apprRender();
  apprEnsureContext();
}

function apprRenderList() {
  const listEl = document.getElementById('apprList');
  const bulkEl = document.getElementById('apprBulk');
  if (!listEl) return;
  if (apprState.failed) {
    listEl.innerHTML = '<div class="appr-empty" role="alert">Couldn’t load your approvals. <button type="button" class="pill-btn pill-btn-outline" onclick="loadApprovals()">Try again</button></div>';
    bulkEl?.classList.add('hidden');
    return;
  }
  const visible = apprVisible(apprState.items, apprState.filter);
  if (!visible.length) {
    listEl.innerHTML = `<div class="appr-empty"><strong>You’re all caught up.</strong><br>Nothing is waiting on your decision${apprState.filter === 'all' ? '' : ' in this group'}. New requests appear here and on Home.</div>`;
    bulkEl?.classList.add('hidden');
    return;
  }
  listEl.innerHTML = visible.map(t => {
    const age = apprAge(t);
    const sel = t.key === apprState.selected;
    const canTick = apprBulkEligible(t);
    return `<li class="appr-row${sel ? ' appr-row-selected' : ''}" data-key="${esc(t.key)}">
      ${canTick ? `<input type="checkbox" class="appr-check" aria-label="Select ${esc(t.employee_name || 'request')}’s ${esc(APPR_NOUN[t.module])}" ${apprState.checked.has(t.key) ? 'checked' : ''} onchange="apprToggleCheck('${esc(t.key)}', this.checked)">` : '<span class="appr-check-spacer" aria-hidden="true"></span>'}
      <button type="button" class="appr-row-main" aria-current="${sel}" onclick="apprSelect('${esc(t.key)}')">
        <span class="appr-row-top"><span class="appr-name">${esc(t.employee_name || 'Unknown')}</span><span class="appr-type">${esc(t.stage_type || APPR_NOUN[t.module])}</span></span>
        <span class="appr-row-stage">${esc(t.stage || '')}</span>
        ${age.text ? `<span class="appr-age appr-age-${age.tone}">${esc(age.text)}</span>` : ''}
      </button></li>`;
  }).join('');
  const n = visible.filter(t => apprState.checked.has(t.key)).length;
  if (bulkEl) {
    const any = visible.some(apprBulkEligible);
    bulkEl.classList.toggle('hidden', !any);
    const btn = document.getElementById('apprBulkBtn');
    if (btn) { btn.disabled = !n || apprState.busy; btn.textContent = n ? `Approve selected (${n})` : 'Approve selected'; }
    const all = document.getElementById('apprSelectAll');
    if (all) { const elig = visible.filter(apprBulkEligible); all.checked = elig.length > 0 && elig.every(t => apprState.checked.has(t.key)); }
  }
}

function apprToggleCheck(key, on) {
  if (on) apprState.checked.add(key); else apprState.checked.delete(key);
  apprRenderList();
}

function apprToggleAll(on) {
  apprVisible(apprState.items, apprState.filter).filter(apprBulkEligible).forEach(t => { if (on) apprState.checked.add(t.key); else apprState.checked.delete(t.key); });
  apprRenderList();
}

function apprSelect(key) {
  if (apprState.busy) return;
  apprState.selected = key;
  apprState.reject = null;
  apprState.error = '';
  apprRenderList();
  apprRenderDetail();
  apprEnsureContext();
  if (window.innerWidth < 1024) document.getElementById('apprDetail')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function apprRenderDetail() {
  const el = document.getElementById('apprDetail');
  if (!el) return;
  const t = apprSelectedItem();
  if (!t) {
    el.innerHTML = apprState.failed ? '' : '<p class="appr-empty">Select a request to see it here.</p>';
    return;
  }
  const ctx = apprState.ctx.get(t.key);
  const emp = ctx && typeof ctx === 'object' ? ctx.employee : null;
  const name = emp?.name || t.employee_name || 'Unknown';
  const sub = emp ? [emp.designation, emp.department].filter(Boolean).join(' · ') : '';
  let body;
  if (ctx === 'loading' || ctx === undefined) body = '<p class="appr-muted">Loading details…</p>';
  else if (ctx === 'gone') body = '<p class="appr-muted" role="alert">This request is no longer waiting on you. The list will refresh.</p>';
  else if (ctx === 'error') body = '<p class="appr-muted" role="alert">Couldn’t load the details. You can still decide, or open the full record.</p>';
  else {
    const facts = ctx.facts.map(f => `<div class="appr-fact"><dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd></div>`).join('');
    const warns = ctx.warnings.map(w => `<p class="appr-warn" role="note">${esc(w)}</p>`).join('');
    const steps = ctx.steps.length ? `<h4 class="appr-h">Approval steps</h4><ol class="appr-steps">${ctx.steps.map(s =>
      `<li class="appr-step appr-step-${s.state}"><span class="appr-step-dot" aria-hidden="true"></span>${esc(s.label)}<span class="appr-step-state">${s.state === 'done' ? 'Approved' : s.state === 'current' ? 'Waiting' : 'Next'}</span></li>`).join('')}</ol>` : '';
    body = `${warns}<dl class="appr-facts">${facts}</dl>${steps}`;
  }
  el.innerHTML = `<div class="appr-card">
      <div class="appr-card-head">
        <div><h3 class="appr-card-title">${esc(name)}</h3>${sub ? `<p class="appr-muted">${esc(sub)}</p>` : ''}</div>
        <span class="appr-type">${esc(t.stage_type || APPR_NOUN[t.module])}</span>
      </div>
      <p class="appr-stage">${esc(t.stage || '')}</p>
      ${body}
    </div>
    ${apprDecisionBarHtml(t)}`;
}

function apprDecisionBarHtml(t) {
  const busy = apprState.busy;
  const rej = apprState.reject && apprState.reject.key === t.key ? apprState.reject : null;
  const label = `${t.employee_name || 'the employee'}’s ${APPR_NOUN[t.module]}`;
  const err = apprState.error ? `<p class="appr-error" role="alert">${esc(apprState.error)}</p>` : '';
  const key = esc(t.key);
  if (rej) {
    const needs = apprNeedsReason(t);
    return `<div class="appr-bar" role="group" aria-label="Reject ${esc(label)}">
      ${err}
      ${needs ? `<label class="appr-label" for="apprReason">Reason for rejecting <span>(required — saved with the request)</span></label>
      <textarea id="apprReason" class="inp" rows="2" maxlength="500" ${busy ? 'disabled' : ''} oninput="apprRejectInput(this.value)">${esc(rej.reason)}</textarea>` : '<p class="appr-muted">This decision is recorded without a reason.</p>'}
      <div class="appr-bar-buttons">
        <button type="button" class="pill-btn appr-danger" ${busy ? 'disabled' : ''} onclick="apprDecide('reject')">${busy ? 'Rejecting…' : 'Confirm reject'}</button>
        <button type="button" class="pill-btn pill-btn-outline" ${busy ? 'disabled' : ''} onclick="apprRejectCancel()">Cancel</button>
      </div></div>`;
  }
  return `<div class="appr-bar" role="group" aria-label="Decide ${esc(label)}">
      ${err}
      <div class="appr-bar-buttons">
        <button type="button" class="pill-btn pill-btn-primary" ${busy ? 'disabled' : ''} onclick="apprDecide('approve')" aria-keyshortcuts="A">${busy ? 'Working…' : 'Approve'}</button>
        <button type="button" class="pill-btn appr-reject" ${busy ? 'disabled' : ''} onclick="apprRejectOpen()" aria-keyshortcuts="R">Reject</button>
        <button type="button" class="pill-btn pill-btn-outline" onclick="${_todoNav(t.page, t.focus_id)}">Open full record</button>
      </div>
      <p class="appr-keys"><kbd>A</kbd> approve · <kbd>R</kbd> reject · <kbd>J</kbd>/<kbd>K</kbd> next/previous</p></div>`;
}

function apprRejectOpen() {
  const t = apprSelectedItem();
  if (!t || apprState.busy) return;
  apprState.reject = { key: t.key, reason: apprState.reject?.key === t.key ? apprState.reject.reason : '' };
  apprState.error = '';
  apprRenderDetail();
  document.getElementById('apprReason')?.focus();
}
function apprRejectInput(v) { if (apprState.reject) apprState.reject.reason = v; } // no re-render: it would steal focus
function apprRejectCancel() { apprState.reject = null; apprState.error = ''; apprRenderDetail(); }

// ---- deciding ---------------------------------------------------------------
async function apprSend(t, action, notes) {
  const req = apprDecisionRequest(t, action, notes);
  const res = await api(req.url, { method: req.method, body: JSON.stringify(req.body) });
  if (!res) return { aborted: true };
  if (res.ok) {
    let row = null;
    try { row = await res.json(); } catch (e) { /* decided either way */ }
    return { ok: true, row };
  }
  let detail = '';
  try { detail = apiErrorText((await res.json()).detail, ''); } catch (e) { /* no body */ }
  const gone = res.status === 404 || (res.status === 400 && /already/i.test(detail));
  return { ok: false, gone, status: res.status, detail };
}

async function apprDecide(action) {
  const t = apprSelectedItem();
  if (!t || apprState.busy) return;
  const label = `${t.employee_name || 'the employee'}’s ${APPR_NOUN[t.module]}`;
  let notes = '';
  if (action === 'reject' && apprNeedsReason(t)) {
    notes = (apprState.reject?.reason || '').trim();
    if (!notes) { apprState.error = 'Add a reason — it is saved with the request.'; apprRenderDetail(); document.getElementById('apprReason')?.focus(); return; }
  }
  if (action === 'approve' && t.module === 'resignation' && !confirm(`Approving ${label} starts offboarding. Continue?`)) return;
  apprState.busy = true; apprState.error = ''; apprRenderDetail(); apprRenderList();
  let out;
  try { out = await apprSend(t, action, notes); } catch (e) { out = { ok: false, detail: '', network: true }; }
  apprState.busy = false;
  if (out.aborted) return;
  if (out.ok) {
    apprState.reject = null;
    const advanced = action === 'approve' && out.row && typeof out.row.status === 'string' && /pending/i.test(out.row.status);
    notify(action === 'reject' ? `Rejected ${label}.` : advanced ? `Approved at your step — ${label} is now with the next approver.` : `Approved ${label}.`, 'success');
    await loadApprovals();
    if (typeof loadDashboardTodos === 'function') loadDashboardTodos();
    return;
  }
  if (out.gone) {
    apprState.reject = null;
    notify(`${label[0].toUpperCase()}${label.slice(1)} was already decided by someone else. Your list has been refreshed.`, 'info');
    await loadApprovals();
    return;
  }
  const verb = action === 'approve' ? 'approve' : 'reject';
  apprState.error = out.network ? `Couldn’t ${verb} ${label}. Check your connection and try again.`
    : out.status === 403 ? `You’re not able to ${verb} ${label}${out.detail ? `: ${out.detail}` : '.'}`
    : `Couldn’t ${verb} ${label}${out.detail ? `: ${out.detail}` : '. Please try again.'}`;
  apprRenderDetail();
  apprRenderList();
}

async function apprBulkApprove() {
  if (apprState.busy) return;
  const chosen = apprVisible(apprState.items, apprState.filter).filter(t => apprBulkEligible(t) && apprState.checked.has(t.key));
  if (!chosen.length) return;
  if (!confirm(`Approve ${chosen.length} request${chosen.length === 1 ? '' : 's'}? Each requester is notified.`)) return;
  apprState.busy = true; apprRenderList(); apprRenderDetail();
  let ok = 0; const failures = [];
  for (const t of chosen) {
    let out;
    try { out = await apprSend(t, 'approve', ''); } catch (e) { out = { ok: false, detail: '' }; }
    if (out.aborted) { apprState.busy = false; return; }
    if (out.ok || out.gone) ok++; else failures.push(`${t.employee_name || 'Request'}${out.detail ? ` (${out.detail})` : ''}`);
  }
  apprState.busy = false;
  apprState.checked.clear();
  notify(failures.length ? `Approved ${ok} of ${chosen.length}. Couldn’t approve: ${failures.join('; ')}.` : `Approved ${ok} request${ok === 1 ? '' : 's'}.`, failures.length ? 'error' : 'success');
  await loadApprovals();
  if (typeof loadDashboardTodos === 'function') loadDashboardTodos();
}

// ---- keyboard: J/K move, A approve, R reject (only on this page, never while typing) --------
document.addEventListener('keydown', e => {
  if (currentPage !== 'approvals' || e.ctrlKey || e.metaKey || e.altKey) return;
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
  if (document.getElementById('cmdPalette') && !document.getElementById('cmdPalette').classList.contains('hidden')) return;
  const k = e.key.toLowerCase();
  const visible = apprVisible(apprState.items, apprState.filter);
  const i = visible.findIndex(t => t.key === apprState.selected);
  if (k === 'j' || k === 'k') {
    if (!visible.length) return;
    e.preventDefault();
    apprSelect(visible[Math.min(Math.max(i + (k === 'j' ? 1 : -1), 0), visible.length - 1)].key);
  } else if (k === 'a' && apprSelectedItem() && !apprState.reject) { e.preventDefault(); apprDecide('approve'); }
  else if (k === 'r' && apprSelectedItem() && !apprState.reject) { e.preventDefault(); apprRejectOpen(); }
});

// Performance Improvement Plan (PIP) — manager-initiated, HR-approved.
// Lives on the Team Appraisals page (page-perf-team), the one page both
// manager and hr_manager already see. Reuses perfCyclesCache/
// loadPerfCyclesCache (performance.js) rather than a separate fetch —
// PIP cycles are just performance_cycles rows with cycle_type='pip'.
// ---------------------------------------------------------------------------
const PIP_STATUS_COLORS = {
  PendingApproval: 'bg-amber-100 text-amber-700',
  Active: 'bg-blue-100 text-blue-700',
  Rejected: 'bg-red-100 text-red-700',
  Closed: 'bg-slate-100 text-slate-600',
};
const PIP_OUTCOME_COLORS = {
  Successful: 'bg-green-100 text-green-700',
  Extended: 'bg-amber-100 text-amber-700',
  Failed: 'bg-red-100 text-red-700',
};

let pipGoalDraft = [];
let _pipDetailId = null;

async function loadPipList() {
  const listEl = document.getElementById('pipList');
  const emptyEl = document.getElementById('pipEmpty');
  if (!listEl) return;
  listEl.innerHTML = '<p class="text-slate-400 text-sm text-center py-6">Loading…</p>';
  await loadPerfCyclesCache();
  const rows = perfCyclesCache.filter(c => c.cycle_type === 'pip');
  if (!rows.length) { listEl.innerHTML = ''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML = rows.map(pipCardHtml).join('');
}

// perf-my is the one Performance page every role (including a plain
// employee) can see — this is the only place an employee ever sees
// their own PIP, read-only (renderPipDetailBody's isHr/canAddCheckin
// checks naturally render nothing actionable for the 'employee' role).
async function loadMyPip() {
  const wrap = document.getElementById('perfMyPipWrap');
  if (!wrap) return;
  const empId = currentUser?.employee_id;
  const myPip = perfCyclesCache.find(c => c.cycle_type === 'pip' && c.employee_id === empId);
  if (!myPip) { wrap.innerHTML = ''; return; }
  const [goalsRes, checkinsRes] = await Promise.all([
    api(`/api/performance/goals?cycle_id=${myPip.id}&employee_id=${encodeURIComponent(empId)}`),
    api(`/api/performance/pip/${myPip.id}/checkins`),
  ]);
  const goals = goalsRes?.ok ? await goalsRes.json() : [];
  const checkins = checkinsRes?.ok ? await checkinsRes.json() : [];
  wrap.innerHTML = `<div class="bg-white rounded-xl border border-slate-200 p-5 mb-5">
    <h3 class="text-sm font-semibold text-slate-700 mb-3">${esc(myPip.name)}</h3>
    ${renderPipDetailBody(myPip, goals, checkins)}
  </div>`;
}

function pipCardHtml(c) {
  return `<div class="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:bg-slate-50 transition" onclick="openPipDetail(${c.id})">
    <div class="flex items-center gap-2 flex-wrap mb-0.5">
      <p class="font-medium text-slate-800">${esc(c.name)}</p>
      <span class="badge text-xs ${statusColor(PIP_STATUS_COLORS, c.status)}">${c.status}</span>
      ${c.outcome ? `<span class="badge text-xs ${statusColor(PIP_OUTCOME_COLORS, c.outcome)}">${c.outcome}</span>` : ''}
    </div>
    <p class="text-xs text-slate-500">${fmtDate(c.period_start)} → ${fmtDate(c.period_end)}</p>
    ${c.reason ? `<p class="text-xs text-slate-400 italic mt-1">${esc(c.reason)}</p>` : ''}
  </div>`;
}

function openPipProposeModal() {
  const sel = document.getElementById('pipEmpId');
  sel.innerHTML = '<option value="">Select employee…</option>';
  employees.filter(e => e.status === 'Active' && e.employee_id !== currentUser?.employee_id)
    .forEach(e => {
      const o = document.createElement('option');
      o.value = e.employee_id;
      o.textContent = `${e.employee_id} — ${displayName(e.full_name, e.preferred_name)}`;
      sel.appendChild(o);
    });
  initEmployeeSearchSelect('pipEmpId', 'Search employee…');
  document.getElementById('pipReason').value = '';
  document.getElementById('pipStartDate').value = todayStr();
  document.getElementById('pipEndDate').value = '';
  document.getElementById('pipProposeErr').classList.add('hidden');
  pipGoalDraft = [];
  renderPipGoalRows();
  document.getElementById('pipProposeModal').classList.remove('hidden');
}
function closePipProposeModal() { closeModal('pipProposeModal'); }

function addPipGoalRow() {
  pipGoalDraft.push({ title: '', weight: 0 });
  renderPipGoalRows();
}
function removePipGoalRow(i) {
  pipGoalDraft.splice(i, 1);
  renderPipGoalRows();
}
function updatePipGoalRow(i, field, value) {
  pipGoalDraft[i][field] = value;
}
function renderPipGoalRows() {
  const el = document.getElementById('pipGoalRows');
  el.innerHTML = pipGoalDraft.length ? pipGoalDraft.map((g, i) => `
    <div class="flex gap-2 items-center">
      <input value="${esc(g.title)}" oninput="updatePipGoalRow(${i},'title',this.value)" class="inp text-sm flex-1" placeholder="Goal title"/>
      <input type="number" step="1" min="0" max="100" value="${g.weight}" oninput="updatePipGoalRow(${i},'weight',this.value)" class="inp text-sm" style="width:90px" placeholder="Weight %"/>
      <button type="button" onclick="removePipGoalRow(${i})" class="text-red-500 hover:text-red-700 text-lg leading-none px-1">&times;</button>
    </div>`).join('') : '<p class="text-xs text-slate-400">No goals added.</p>';
}

const submitPipPropose = guardAsync(async function() {
  const err = document.getElementById('pipProposeErr');
  err.classList.add('hidden');
  const employee_id = document.getElementById('pipEmpId').value;
  const reason = document.getElementById('pipReason').value.trim();
  const start_date = document.getElementById('pipStartDate').value;
  const end_date = document.getElementById('pipEndDate').value;
  if (!employee_id || !reason || !start_date || !end_date) {
    err.textContent = 'Employee, reason, start date, and end date are all required.';
    err.classList.remove('hidden');
    return;
  }
  const goals = pipGoalDraft
    .filter(g => g.title && g.title.trim())
    .map(g => ({ title: g.title.trim(), weight: parseFloat(g.weight) || 0 }));
  const res = await api('/api/performance/pip', {
    method: 'POST',
    body: JSON.stringify({ employee_id, reason, start_date, end_date, goals }),
  });
  if (!res || !res.ok) {
    const d = await res?.json().catch(() => ({}));
    err.textContent = d?.detail || 'Failed to submit PIP proposal';
    err.classList.remove('hidden');
    return;
  }
  closePipProposeModal();
  loadPipList();
});

async function openPipDetail(id) {
  let cycle = perfCyclesCache.find(c => c.id === id);
  if (!cycle) { await loadPerfCyclesCache(); cycle = perfCyclesCache.find(c => c.id === id); }
  if (!cycle) return;
  _pipDetailId = id;
  document.getElementById('pipDetailTitle').textContent = cycle.name;
  document.getElementById('pipDetailMeta').textContent = `${fmtDate(cycle.period_start)} → ${fmtDate(cycle.period_end)}`;
  const [goalsRes, checkinsRes] = await Promise.all([
    api(`/api/performance/goals?cycle_id=${id}&employee_id=${encodeURIComponent(cycle.employee_id)}`),
    api(`/api/performance/pip/${id}/checkins`),
  ]);
  const goals = goalsRes?.ok ? await goalsRes.json() : [];
  const checkins = checkinsRes?.ok ? await checkinsRes.json() : [];
  document.getElementById('pipDetailBody').innerHTML = renderPipDetailBody(cycle, goals, checkins);
  document.getElementById('pipDetailModal').classList.remove('hidden');
}
function closePipDetailModal() { closeModal('pipDetailModal', () => { _pipDetailId = null; }); }

function renderPipDetailBody(cycle, goals, checkins) {
  const role = currentUser?.role;
  const isHr = role === 'hr_manager';
  const canAddCheckin = (role === 'manager' || role === 'hr_manager') && cycle.status === 'Active';

  let html = `<div class="flex items-center gap-2 flex-wrap">
    <span class="badge text-xs ${statusColor(PIP_STATUS_COLORS, cycle.status)}">${cycle.status}</span>
    ${cycle.outcome ? `<span class="badge text-xs ${statusColor(PIP_OUTCOME_COLORS, cycle.outcome)}">${cycle.outcome}</span>` : ''}
  </div>
  <div>
    <p class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Reason</p>
    <p class="text-sm text-slate-700">${esc(cycle.reason || '—')}</p>
  </div>`;

  if (cycle.outcome_notes) {
    html += `<div>
      <p class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Outcome Notes</p>
      <p class="text-sm text-slate-700">${esc(cycle.outcome_notes)}</p>
    </div>`;
  }

  if (goals.length) {
    html += `<div>
      <p class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">Goals</p>
      <div class="space-y-2">${goals.map(g => renderGoalRow(g, false)).join('')}</div>
    </div>`;
  }

  if (isHr && cycle.status === 'PendingApproval') {
    html += `<div class="flex gap-2">
      <button onclick="decidePip(${cycle.id},'Approved')" class="btn-primary text-sm px-4 py-2">Approve</button>
      <button onclick="decidePip(${cycle.id},'Rejected')" class="btn-ghost text-sm px-4 py-2 text-red-600">Reject</button>
    </div>`;
  }

  if (['Active', 'Closed'].includes(cycle.status) || checkins.length) {
    html += `<div>
      <p class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">Check-ins</p>
      <div class="space-y-2 mb-3">${
        checkins.length
          ? checkins.map(c => `<div class="bg-slate-50 rounded-lg p-3">
              <p class="text-xs text-slate-400">${fmtDate(c.checkin_date)} · ${esc(c.created_by)}</p>
              <p class="text-sm text-slate-700 mt-0.5">${esc(c.notes)}</p>
            </div>`).join('')
          : '<p class="text-xs text-slate-400">No check-ins yet.</p>'
      }</div>
      ${canAddCheckin ? `<div class="border border-slate-200 rounded-lg p-3 space-y-2">
        <input type="date" id="pipCheckinDate" class="inp" value="${todayStr()}"/>
        <textarea id="pipCheckinNotes" class="inp" rows="2" placeholder="Check-in notes"></textarea>
        <button type="button" onclick="submitPipCheckin(${cycle.id})" class="btn-primary text-xs px-3 py-1.5">Add Check-in</button>
      </div>` : ''}
    </div>`;
  }

  if (isHr && cycle.status === 'Active') {
    html += `<div class="border-t border-slate-200 pt-4">
      <p class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">Record Outcome</p>
      <div class="space-y-2">
        <select id="pipOutcomeSelect" class="inp" onchange="togglePipOutcomeEndDate()">
          <option value="">Select outcome…</option>
          <option value="Successful">Successful</option>
          <option value="Extended">Extended</option>
          <option value="Failed">Failed</option>
        </select>
        <div id="pipOutcomeEndDateWrap" class="hidden">
          <label class="lbl">New End Date</label>
          <input type="date" id="pipOutcomeEndDate" class="inp"/>
        </div>
        <textarea id="pipOutcomeNotes" class="inp" rows="2" placeholder="Notes"></textarea>
        <p id="pipOutcomeErr" class="hidden text-xs text-red-600"></p>
        <button type="button" onclick="submitPipOutcome(${cycle.id})" class="btn-primary text-sm px-4 py-2">Record Outcome</button>
      </div>
    </div>`;
  }

  return html;
}

function togglePipOutcomeEndDate() {
  const v = document.getElementById('pipOutcomeSelect').value;
  document.getElementById('pipOutcomeEndDateWrap').classList.toggle('hidden', v !== 'Extended');
}

async function decidePip(id, status) {
  if (status === 'Rejected' && !confirm('Reject this PIP proposal?')) return;
  const res = await api(`/api/performance/pip/${id}/decide`, { method: 'PATCH', body: JSON.stringify({ status }) });
  if (!res?.ok) { const d = await res.json(); alert(d.detail || 'Failed to update'); return; }
  closePipDetailModal();
  loadPipList();
}

const submitPipCheckin = guardAsync(async function(id) {
  const checkin_date = document.getElementById('pipCheckinDate').value;
  const notes = document.getElementById('pipCheckinNotes').value.trim();
  if (!checkin_date || !notes) { alert('Date and notes are required'); return; }
  const res = await api(`/api/performance/pip/${id}/checkins`, { method: 'POST', body: JSON.stringify({ checkin_date, notes }) });
  if (!res?.ok) { const d = await res.json(); alert(d.detail || 'Failed to add check-in'); return; }
  openPipDetail(id);
});

const submitPipOutcome = guardAsync(async function(id) {
  const err = document.getElementById('pipOutcomeErr');
  err.classList.add('hidden');
  const outcome = document.getElementById('pipOutcomeSelect').value;
  const notes = document.getElementById('pipOutcomeNotes').value.trim() || null;
  const new_end_date = document.getElementById('pipOutcomeEndDate')?.value || null;
  if (!outcome) { err.textContent = 'Select an outcome'; err.classList.remove('hidden'); return; }
  if (outcome === 'Extended' && !new_end_date) { err.textContent = 'New end date is required for Extended'; err.classList.remove('hidden'); return; }
  const res = await api(`/api/performance/pip/${id}/outcome`, { method: 'PATCH', body: JSON.stringify({ outcome, notes, new_end_date }) });
  if (!res?.ok) { const d = await res.json(); err.textContent = d.detail || 'Failed to record outcome'; err.classList.remove('hidden'); return; }
  closePipDetailModal();
  loadPipList();
});

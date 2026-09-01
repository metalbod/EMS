// Employee Resignation — self-service submission (Home dashboard "Resign"
// button), HR-on-behalf submission (Employee detail "File Resignation"),
// and the Resignation Approvals page (manager/HR review).
// ---------------------------------------------------------------------------
const RESIGN_STATUS_COLORS = {
  Pending: 'status-pending', Approved: 'status-positive',
  Rejected: 'status-negative', Withdrawn: 'status-neutral',
};
const RESIGN_ATTACH_MAX_BYTES = 6 * 1024 * 1024;

let _resignAttachment = null;
let resignApprovalFilter = 'Pending';

function todayStr() { return new Date().toISOString().slice(0, 10); }

function openResignModal(empId, empName) {
  document.getElementById('resignModalTitle').textContent = empId ? 'File Resignation' : 'Submit Resignation';
  document.getElementById('resignEmpId').value = empId || '';
  const nameEl = document.getElementById('resignForEmpName');
  if (empId) { nameEl.textContent = `For: ${empName}`; nameEl.classList.remove('hidden'); }
  else { nameEl.classList.add('hidden'); }
  document.getElementById('resignReason').value = '';
  document.getElementById('resignEffectiveDate').value = todayStr();
  document.getElementById('resignLastDay').value = todayStr();
  document.getElementById('resignAttachFile').value = '';
  _resignAttachment = null;
  document.getElementById('resignErr').classList.add('hidden');
  document.getElementById('resignModal').classList.remove('hidden');
}
function closeResignModal() { closeModal('resignModal', () => { _resignAttachment = null; }); }

function fileResignationFromView() {
  if (!viewingId) return;
  const e = employees.find(em => em.employee_id === viewingId);
  if (!e) return;
  openResignModal(viewingId, displayName(e.full_name, e.preferred_name));
}

async function handleResignAttachFile(e) {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file) return;
  if (file.size > RESIGN_ATTACH_MAX_BYTES) { alert('File is too large. Please choose a file under ~6MB.'); return; }
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  _resignAttachment = { file_name: file.name, mime_type: file.type || 'application/octet-stream', data_url: dataUrl };
}

const submitResignation = guardAsync(async function(e) {
  e.preventDefault();
  const err = document.getElementById('resignErr');
  err.classList.add('hidden');
  const effectiveDate = document.getElementById('resignEffectiveDate').value;
  const lastDay = document.getElementById('resignLastDay').value;
  if (lastDay < effectiveDate) {
    err.textContent = 'Last working day must be on or after the effective date.';
    err.classList.remove('hidden');
    return;
  }
  const empId = document.getElementById('resignEmpId').value;
  const body = {
    employee_id: empId || null,
    reason: document.getElementById('resignReason').value,
    effective_date: effectiveDate,
    last_working_day: lastDay,
    attachment: _resignAttachment,
  };
  const res = await api('/api/resignations', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) {
    const d = await res?.json().catch(() => ({}));
    err.textContent = d?.detail || 'Failed to submit resignation';
    err.classList.remove('hidden');
    return;
  }
  closeResignModal();
  if (empId) { closeViewModal(); alert('Resignation filed.'); }
  else { await refreshResignButtonState(); }
});

// Toggles the "Resign" button vs. an inline pending-status line on the
// Dashboard General tab — called from renderDashboard() (dashboard.js) for
// the employee role only, same gate as dashboardQuickActions itself.
async function refreshResignButtonState() {
  const btn = document.getElementById('dashboardResignBtn');
  const statusEl = document.getElementById('dashboardResignStatus');
  if (!btn || !currentUser?.employee_id) return;
  const res = await api('/api/resignations?status=Pending');
  const rows = res?.ok ? await res.json() : [];
  const mine = rows.find(r => r.employee_id === currentUser.employee_id);
  if (mine) {
    btn.classList.add('hidden');
    statusEl.innerHTML = `Your resignation is pending approval. <a href="#" onclick="withdrawMyResignation(${mine.id});return false;" class="text-blue-600 hover:underline">Withdraw</a>`;
    statusEl.classList.remove('hidden');
  } else {
    btn.classList.remove('hidden');
    statusEl.classList.add('hidden');
  }
}

async function withdrawMyResignation(id) {
  if (!confirm('Withdraw your resignation request?')) return;
  const res = await api(`/api/resignations/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'Withdrawn' }) });
  if (!res?.ok) { const d = await res?.json().catch(() => ({})); alert(d?.detail || 'Failed to withdraw'); return; }
  await refreshResignButtonState();
}

// ---------------------------------------------------------------------------
// Resignation Approvals (manager / HR)
// ---------------------------------------------------------------------------
async function loadResignationApprovals() {
  const listEl = document.getElementById('resignationApprovalList');
  const emptyEl = document.getElementById('resignationApprovalEmpty');
  listEl.innerHTML = '<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  let url = '/api/resignations';
  if (resignApprovalFilter) url += `?status=${encodeURIComponent(resignApprovalFilter)}`;
  const res = await api(url);
  if (!res?.ok) { listEl.innerHTML = ''; return; }
  const rows = await res.json();
  if (!rows.length) { listEl.innerHTML = ''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML = rows.map(r => `
    <div class="bg-white border border-slate-200 rounded-xl p-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-0.5 flex-wrap">
            <p class="font-medium text-slate-800">${esc(displayName(r.employee_name, r.employee_preferred_name))}</p>
            <span class="badge ${statusColor(RESIGN_STATUS_COLORS, r.status)} text-xs">${r.status}</span>
          </div>
          <p class="text-xs text-slate-500">Effective ${fmtDate(r.effective_date)} · Last working day ${fmtDate(r.last_working_day)}</p>
          <p class="text-xs text-slate-400">${esc(r.department || '')}${r.designation ? ' · ' + esc(r.designation) : ''}</p>
          <p class="text-xs text-slate-400 italic mt-1">${esc(r.reason)}</p>
          ${r.attachment_data_url ? `<a href="${r.attachment_data_url}" target="_blank" class="text-xs text-blue-600 hover:underline mt-1 inline-block">${esc(r.attachment_file_name || 'View attachment')}</a>` : ''}
        </div>
      </div>
      ${r.status === 'Pending' ? `<div class="mt-3 flex gap-2">
        <button onclick="reviewResignationRequest(${r.id},'Approved')" class="btn-primary text-xs px-3 py-1.5">Approve</button>
        <button onclick="reviewResignationRequest(${r.id},'Rejected')" class="btn-ghost text-xs px-3 py-1.5 text-red-600">Reject</button>
      </div>` : ''}
      <p class="text-xs text-slate-400 mt-2">Submitted ${fmtDate(r.created_at)} by ${esc(r.submitted_by)}</p>
    </div>`).join('');
}

function setResignationApprovalFilter(status) {
  resignApprovalFilter = status;
  document.querySelectorAll('.resign-appr-filter-btn').forEach(b => b.classList.remove('resign-appr-filter-active'));
  event?.target?.classList?.add('resign-appr-filter-active');
  loadResignationApprovals();
}

async function reviewResignationRequest(id, status) {
  const res = await api(`/api/resignations/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
  if (res?.ok) loadResignationApprovals();
  else { const d = await res.json(); alert(d.detail || 'Failed to update'); }
}

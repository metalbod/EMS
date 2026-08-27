// Employee Document Compliance
// ---------------------------------------------------------------------------
// HR-configurable document types (Settings → Document Types) + per-employee
// tracked instances (Employee Detail → Documents tab). Reminders surface via
// the Dashboard To-Do widget and the Dashboard monthly Leave Calendar (see
// static/js/dashboard.js) — both driven by status computed server-side
// (routers/employee_documents.py's STATUS_CASE_SQL), so there's no
// client-side day-math to duplicate here.
// ---------------------------------------------------------------------------
let employeeDocTypesCache = [];
let employeeDocumentsCache = [];
let employeeDocAttachment = { fileName: null, mimeType: null, dataUrl: null };

const EMPLOYEE_DOC_STATUS_BADGE = {
  overdue: 'bg-red-100 text-red-700',
  expiring_soon: 'bg-amber-100 text-amber-700',
  ok: 'bg-slate-100 text-slate-500',
};
const EMPLOYEE_DOC_STATUS_LABEL = {
  overdue: 'Overdue', expiring_soon: 'Expiring soon', ok: 'OK',
};

function employeeDocStatusBadge(status) {
  const cls = EMPLOYEE_DOC_STATUS_BADGE[status] || EMPLOYEE_DOC_STATUS_BADGE.ok;
  const label = EMPLOYEE_DOC_STATUS_LABEL[status] || status;
  return `<span class="badge ${cls} text-xs">${label}</span>`;
}

async function loadEmployeeDocTypesCache() {
  const res = await api('/api/employee-document-types');
  employeeDocTypesCache = res?.ok ? await res.json() : [];
}

// ---------------------------------------------------------------------------
// Settings → Document Types
// ---------------------------------------------------------------------------
async function loadEmployeeDocTypesPage() {
  await loadEmployeeDocTypesCache();
  const wrap = document.getElementById('employeeDocTypeList');
  const emptyEl = document.getElementById('employeeDocTypeEmpty');
  if (!employeeDocTypesCache.length) {
    wrap.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');
  wrap.innerHTML = employeeDocTypesCache.map(t => `
    <div class="flex items-center gap-2 py-3">
      <span class="flex-1 text-sm text-slate-700">${esc(t.name)}</span>
      <span class="text-xs text-slate-400">Reminds ${t.reminder_window_days} day(s) before</span>
      <button onclick="openEmployeeDocTypeModal(${t.id})" class="text-slate-300 hover:text-blue-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
      <button onclick="deleteEmployeeDocType(${t.id})" class="text-slate-300 hover:text-red-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>`).join('');
}

function openEmployeeDocTypeModal(typeId) {
  document.getElementById('employeeDocTypeId').value = typeId || '';
  document.getElementById('employeeDocTypeModalTitle').textContent = typeId ? 'Edit Document Type' : 'Add Document Type';
  if (typeId) {
    const t = employeeDocTypesCache.find(x => x.id === typeId);
    document.getElementById('employeeDocTypeName').value = t?.name || '';
    document.getElementById('employeeDocTypeWindow').value = t?.reminder_window_days || 30;
    document.getElementById('employeeDocTypeActive').checked = t?.is_active === undefined ? true : !!t.is_active;
  } else {
    document.getElementById('employeeDocTypeName').value = '';
    document.getElementById('employeeDocTypeWindow').value = 30;
    document.getElementById('employeeDocTypeActive').checked = true;
  }
  document.getElementById('employeeDocTypeModal').classList.remove('hidden');
}
function closeEmployeeDocTypeModal() { closeModal('employeeDocTypeModal'); }

async function submitEmployeeDocType(e) {
  e.preventDefault();
  const id = document.getElementById('employeeDocTypeId').value;
  const body = {
    name: document.getElementById('employeeDocTypeName').value.trim(),
    reminder_window_days: parseInt(document.getElementById('employeeDocTypeWindow').value) || 30,
    is_active: document.getElementById('employeeDocTypeActive').checked,
  };
  const url = id ? `/api/employee-document-types/${id}` : '/api/employee-document-types';
  const res = await api(url, { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) });
  if (res?.ok) { closeEmployeeDocTypeModal(); loadEmployeeDocTypesPage(); }
  else if (res) { const d = await res.json().catch(() => ({})); alert(d.detail || 'Failed to save document type'); }
}

async function deleteEmployeeDocType(id) {
  if (!confirm('Remove this document type?')) return;
  await api(`/api/employee-document-types/${id}`, { method: 'DELETE' });
  loadEmployeeDocTypesPage();
}

// ---------------------------------------------------------------------------
// Employee Detail → Documents tab
// ---------------------------------------------------------------------------
async function loadEmployeeDocuments(employeeId) {
  if (!employeeId) return;
  if (!employeeDocTypesCache.length) await loadEmployeeDocTypesCache();
  const listEl = document.getElementById('employeeDocumentList');
  const emptyEl = document.getElementById('employeeDocumentEmpty');
  listEl.innerHTML = '<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  const res = await api(`/api/employees/${employeeId}/documents`);
  employeeDocumentsCache = res?.ok ? await res.json() : [];
  if (!employeeDocumentsCache.length) {
    listEl.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');
  listEl.innerHTML = employeeDocumentsCache.map(d => `
    <div class="bg-white border border-slate-200 rounded-xl p-3 flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2 mb-0.5 flex-wrap">
          <p class="font-medium text-slate-800 text-sm">${esc(d.document_type_name)}</p>
          ${employeeDocStatusBadge(d.status)}
        </div>
        <p class="text-xs text-slate-500">Expires ${fmtDate(d.expiry_date)}${d.document_number ? ` · ${esc(d.document_number)}` : ''}</p>
        ${d.notes ? `<p class="text-xs text-slate-400 italic mt-1">${esc(d.notes)}</p>` : ''}
        ${d.attachment_data_url ? `<a href="${d.attachment_data_url}" target="_blank" class="text-xs text-blue-600 hover:underline mt-1 inline-block">View attachment</a>` : ''}
      </div>
      <div class="flex gap-1 shrink-0">
        <button onclick="openEmployeeDocumentForm(${d.id})" class="text-slate-300 hover:text-blue-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
        <button onclick="deleteEmployeeDocument(${d.id})" class="text-slate-300 hover:text-red-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
      </div>
    </div>`).join('');
}

function openEmployeeDocumentForm(docId) {
  document.getElementById('employeeDocumentErr').classList.add('hidden');
  document.getElementById('employeeDocumentId').value = docId || '';
  document.getElementById('employeeDocumentModalTitle').textContent = docId ? 'Edit Document' : 'Add Document';
  const typeSel = document.getElementById('employeeDocumentTypeId');
  typeSel.innerHTML = employeeDocTypesCache.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  employeeDocAttachment = { fileName: null, mimeType: null, dataUrl: null };
  document.getElementById('employeeDocumentAttachFile').value = '';
  const d = docId ? employeeDocumentsCache.find(x => x.id === docId) : null;
  // Only force a value on edit — on add there's no blank placeholder
  // option, so setting .value to '' would match nothing and leave the
  // select with no selection at all (selectedIndex -1), rather than
  // falling back to the browser's natural first-option default.
  if (d) typeSel.value = d.document_type_id;
  document.getElementById('employeeDocumentNumber').value = d?.document_number || '';
  document.getElementById('employeeDocumentIssueDate').value = d?.issue_date || '';
  document.getElementById('employeeDocumentExpiryDate').value = d?.expiry_date || '';
  document.getElementById('employeeDocumentNotes').value = d?.notes || '';
  document.getElementById('employeeDocumentAttachName').textContent =
    d?.attachment_file_name ? `Current: ${d.attachment_file_name} (choose a new file to replace)` : 'Optional — max ~6MB.';
  document.getElementById('employeeDocumentModal').classList.remove('hidden');
}
function closeEmployeeDocumentModal() { closeModal('employeeDocumentModal'); }

function handleEmployeeDocumentAttachFile(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  if (file.size > 6 * 1024 * 1024) { alert('File is too large. Please choose a file under ~6MB.'); e.target.value = ''; return; }
  const reader = new FileReader();
  reader.onload = () => {
    employeeDocAttachment = { fileName: file.name, mimeType: file.type, dataUrl: reader.result };
    document.getElementById('employeeDocumentAttachName').textContent = `Selected: ${file.name}`;
  };
  reader.readAsDataURL(file);
}

async function submitEmployeeDocument(e) {
  e.preventDefault();
  const err = document.getElementById('employeeDocumentErr');
  err.classList.add('hidden');
  const docId = document.getElementById('employeeDocumentId').value;
  const body = {
    document_type_id: parseInt(document.getElementById('employeeDocumentTypeId').value),
    document_number: document.getElementById('employeeDocumentNumber').value.trim() || null,
    issue_date: document.getElementById('employeeDocumentIssueDate').value || null,
    expiry_date: document.getElementById('employeeDocumentExpiryDate').value,
    notes: document.getElementById('employeeDocumentNotes').value.trim() || null,
  };
  if (employeeDocAttachment.dataUrl) {
    body.attachment_file_name = employeeDocAttachment.fileName;
    body.attachment_mime_type = employeeDocAttachment.mimeType;
    body.attachment_data_url = employeeDocAttachment.dataUrl;
  } else if (docId) {
    // PUT replaces every field — keep the existing attachment when no new
    // file was chosen for this edit, instead of wiping it.
    const existing = employeeDocumentsCache.find(x => x.id === parseInt(docId));
    body.attachment_file_name = existing?.attachment_file_name || null;
    body.attachment_mime_type = existing?.attachment_mime_type || null;
    body.attachment_data_url = existing?.attachment_data_url || null;
  }
  const url = docId ? `/api/employees/${viewingId}/documents/${docId}` : `/api/employees/${viewingId}/documents`;
  const res = await api(url, { method: docId ? 'PUT' : 'POST', body: JSON.stringify(body) });
  if (res?.ok) {
    closeEmployeeDocumentModal();
    loadEmployeeDocuments(viewingId);
  } else {
    const d = await res.json();
    err.textContent = d.detail || 'Failed to save document';
    err.classList.remove('hidden');
  }
}

async function deleteEmployeeDocument(docId) {
  if (!confirm('Remove this document?')) return;
  const res = await api(`/api/employees/${viewingId}/documents/${docId}`, { method: 'DELETE' });
  if (res?.ok) loadEmployeeDocuments(viewingId);
  else { const d = await res.json(); alert(d.detail || 'Failed to remove document'); }
}

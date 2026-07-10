// Institutions
// ---------------------------------------------------------------------------
let instLogoDataUrl = null;

function setInstLogoPreview(url) {
  instLogoDataUrl = url || null;
  const img = document.getElementById('instLogoPreview');
  const placeholder = document.getElementById('instLogoPlaceholder');
  const removeBtn = document.getElementById('instLogoRemoveBtn');
  if (instLogoDataUrl) {
    img.src = instLogoDataUrl;
    img.classList.remove('hidden');
    placeholder.classList.add('hidden');
    removeBtn.classList.remove('hidden');
  } else {
    img.src = '';
    img.classList.add('hidden');
    placeholder.classList.remove('hidden');
    removeBtn.classList.add('hidden');
  }
}

function handleInstLogoFile(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  if (file.size > 500 * 1024) {
    alert('Logo image is too large. Please choose a file under ~500KB.');
    e.target.value = '';
    return;
  }
  const reader = new FileReader();
  reader.onload = () => setInstLogoPreview(reader.result);
  reader.readAsDataURL(file);
}

function removeInstLogo() {
  setInstLogoPreview(null);
  document.getElementById('instLogoFile').value = '';
}

async function loadInstitutions() {
  const res = await api('/api/institutions');
  if (!res || !res.ok) return;
  institutions = await res.json();
}

function renderInstTable() {
  const tbody = document.getElementById('instTableBody');
  const empty = document.getElementById('instEmpty');
  const planColors = {starter:'bg-slate-100 text-slate-600',professional:'bg-blue-100 text-blue-700',enterprise:'bg-violet-100 text-violet-700'};
  if (!institutions.length) { tbody.innerHTML=''; empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');
  tbody.innerHTML = institutions.map(i=>`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <div class="flex items-center gap-3">
          ${i.logo_url
            ? `<img src="${i.logo_url}" class="w-9 h-9 rounded-lg object-cover flex-shrink-0"/>`
            : `<div class="w-9 h-9 bg-blue-100 rounded-lg flex items-center justify-center text-blue-700 text-xs font-bold flex-shrink-0">${esc(i.code.slice(0,2).toUpperCase())}</div>`}
          <div>
            <p class="font-medium">${esc(i.name)}</p>
            <p class="text-xs text-slate-400">${esc(i.code)} · ${i.created_at.slice(0,10)}</p>
          </div>
        </div>
      </td>
      <td class="px-4 py-3 hidden sm:table-cell">
        <p class="text-sm">${esc(i.contact_name||'—')}</p>
        <p class="text-xs text-slate-400">${esc(i.contact_email)}</p>
      </td>
      <td class="px-4 py-3"><span class="badge ${planColors[i.plan]||''}">${meta.plan_labels?.[i.plan]||i.plan}</span></td>
      <td class="px-4 py-3 text-center">
        <p class="text-sm font-semibold">${i.employee_count}</p>
        <p class="text-xs text-slate-400">/ ${i.max_employees}</p>
      </td>
      <td class="px-4 py-3"><span class="badge ${i.status==='Active'?'bg-emerald-100 text-emerald-700':'bg-red-100 text-red-600'}">${i.status}</span></td>
      <td class="px-4 py-3">
        <div class="flex justify-end gap-1 flex-wrap">
          <button onclick="enterInstitutionContext(this.dataset.inst)" data-inst='${JSON.stringify(i).replace(/'/g,"&apos;")}' class="btn-primary" style="font-size:.75rem;padding:.25rem .75rem">Manage</button>
          <button onclick="openInstModal(this.dataset.inst)" data-inst='${JSON.stringify(i).replace(/'/g,"&apos;")}' class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem">Edit</button>
          <button onclick="toggleInstStatus(${i.id},'${i.status==='Active'?'Suspended':'Active'}')" class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem;color:${i.status==='Active'?'#dc2626':'#059669'}">${i.status==='Active'?'Suspend':'Activate'}</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function openInstModal(instData = null) {
  const i = typeof instData === 'string' ? JSON.parse(instData) : instData;
  const isEdit = !!i?.id;
  document.getElementById('instModalTitle').textContent = isEdit ? 'Edit Institution' : 'Add Institution';
  document.getElementById('instSubmitBtn').textContent = isEdit ? 'Save Changes' : 'Create Institution';
  document.getElementById('instId').value = i?.id || '';
  document.getElementById('instLogoFile').value = '';
  setInstLogoPreview(i?.logo_url || null);
  document.getElementById('instName').value = i?.name || '';
  document.getElementById('instCode').value = i?.code || '';
  document.getElementById('instCode').disabled = isEdit;
  document.getElementById('instPlan').value = i?.plan || 'starter';
  document.getElementById('instMaxEmp').value = i?.max_employees || 50;
  document.getElementById('instContactName').value = i?.contact_name || '';
  document.getElementById('instContactEmail').value = i?.contact_email || '';
  document.getElementById('instPhone').value = i?.phone || '';
  document.getElementById('instAddress').value = i?.address || '';
  document.getElementById('instAdminSection').classList.toggle('hidden', isEdit);
  ['instAdminUser','instAdminName','instAdminPass','instAdminEmail'].forEach(id=>{
    const el = document.getElementById(id);
    el.required = !isEdit && id !== 'instAdminEmail';
    el.value = '';
  });
  document.getElementById('instFormErr').classList.add('hidden');
  document.getElementById('instModal').classList.remove('hidden');
}

function closeInstModal() { document.getElementById('instModal').classList.add('hidden'); }

async function submitInstForm(e) {
  e.preventDefault();
  const instId = document.getElementById('instId').value;
  const isEdit = !!instId;
  const err = document.getElementById('instFormErr');
  err.classList.add('hidden');
  const body = {
    name: document.getElementById('instName').value.trim(),
    code: document.getElementById('instCode').value.trim().toUpperCase(),
    logo_url: instLogoDataUrl,
    contact_name: document.getElementById('instContactName').value.trim() || null,
    contact_email: document.getElementById('instContactEmail').value.trim(),
    phone: document.getElementById('instPhone').value.trim() || null,
    address: document.getElementById('instAddress').value.trim() || null,
    plan: document.getElementById('instPlan').value,
    max_employees: parseInt(document.getElementById('instMaxEmp').value) || 50,
  };
  if (!isEdit) {
    body.admin_username = document.getElementById('instAdminUser').value.trim();
    body.admin_full_name = document.getElementById('instAdminName').value.trim();
    body.admin_password = document.getElementById('instAdminPass').value;
    body.admin_email = document.getElementById('instAdminEmail').value.trim() || null;
  }
  const res = await api(
    isEdit ? `/api/institutions/${instId}` : '/api/institutions',
    {method: isEdit ? 'PUT' : 'POST', body: JSON.stringify(body)}
  );
  if (!res) return;
  if (!res.ok) {
    const d = await res.json();
    err.textContent = d.detail || 'Failed to save institution';
    err.classList.remove('hidden'); return;
  }
  closeInstModal();
  await loadInstitutions();
  renderInstTable();
}

async function toggleInstStatus(id, newStatus) {
  const res = await api(`/api/institutions/${id}/status`, {method:'PATCH', body:JSON.stringify({status:newStatus})});
  if (res?.ok) { await loadInstitutions(); renderInstTable(); }
}

// ---------------------------------------------------------------------------

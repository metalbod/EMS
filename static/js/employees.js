// Employees
// ---------------------------------------------------------------------------
async function loadEmployees() {
  const res = await api('/api/employees');
  if (!res || !res.ok) return;
  employees = await res.json();
}

// Years lapsed since start_date, as a float (for sorting) — e.g. 3.33 for 3y4m.
function yearsOfServiceValue(e) {
  if (!e.start_date) return -1;
  const start = new Date(e.start_date);
  if (isNaN(start)) return -1;
  return (Date.now() - start.getTime()) / (1000*60*60*24*365.25);
}

function yearsOfServiceLabel(e) {
  const v = yearsOfServiceValue(e);
  if (v < 0) return '—';
  const years = Math.floor(v);
  const months = Math.round((v - years) * 12);
  if (years === 0) return `${months} mo${months===1?'':'s'}`;
  return months ? `${years}y ${months}m` : `${years}y`;
}

const empList = createListState({
  sortKey: 'full_name',
  sortValue: (e, key) => key === 'years_of_service' ? yearsOfServiceValue(e) : e[key],
});
let empFilteredData = [];

// ---------------------------------------------------------------------------
// Employee List — optional columns
// ---------------------------------------------------------------------------
// The Name column (avatar + name) and the trailing chevron are always
// shown; every other column is opt-in via the Columns picker, remembered
// per-browser in localStorage. "Pay Grade" only appears for roles that can
// already see compensation data elsewhere (Compensation module's own
// gate — see dashboard.js's canCompensation) — it's filtered out of the
// picker AND never rendered for anyone else, even if a stale preference
// from a different user/role is sitting in this browser's storage.
const EMP_COLUMNS = [
  { key:'employee_id', label:'ID', sortKey:'employee_id', default:false, render:e=>esc(e.employee_id) },
  { key:'email', label:'Email', sortKey:'work_email', default:false, render:e=>esc(e.work_email||'—') },
  { key:'phone', label:'Mobile No', sortKey:'phone', default:false, render:e=>esc(e.phone||'—') },
  { key:'designation', label:'Job Title', sortKey:'designation', default:true, render:e=>esc(e.designation||'—') },
  { key:'department', label:'Department', sortKey:'department', default:true, render:e=>esc(e.department||'—') },
  { key:'manager', label:'Manager', sortKey:'manager_name', default:true, render:e=>e.manager_name?esc(displayName(e.manager_name,e.manager_preferred_name)):'—' },
  { key:'location', label:'Location', sortKey:'location_name', default:true, render:e=>esc(e.location_name||'—') },
  { key:'start_date', label:'Join Date', sortKey:'start_date', default:false, render:e=>fmtDate(e.start_date) },
  { key:'probation_end_date', label:'Confirm Date', sortKey:'probation_end_date', default:false, render:e=>fmtDate(e.probation_end_date) },
  { key:'resign_date', label:'Resign Date', sortKey:'resign_date', default:false, render:e=>fmtDate(e.resign_date) },
  { key:'last_working_day', label:'Last Working Day', sortKey:'last_working_day', default:false, render:e=>fmtDate(e.last_working_day) },
  { key:'date_of_birth', label:'Date of Birth', sortKey:'date_of_birth', default:false, render:e=>fmtDate(e.date_of_birth) },
  { key:'gender', label:'Gender', sortKey:'gender', default:false, render:e=>esc(e.gender||'—') },
  { key:'race', label:'Race', sortKey:'race', default:false, render:e=>esc(e.race||'—') },
  { key:'employment_type', label:'Employee Type', sortKey:'employment_type', default:true, render:e=>esc(e.employment_type||'—') },
  { key:'years_of_service', label:'Years of Service', sortKey:'years_of_service', default:true, render:e=>yearsOfServiceLabel(e) },
  { key:'status', label:'Status', sortKey:'status', default:true, render:e=>`<span class="badge ${e.status==='Active'?'bg-emerald-100 text-emerald-700':'bg-slate-100 text-slate-500'}">${e.status}</span>` },
  { key:'pay_grade', label:'Pay Grade', sortKey:'pay_grade_name', default:false, roles:COMPENSATION_STAFF_ROLES, render:e=>esc(e.pay_grade_name||'—') },
];
const EMP_COLUMNS_STORAGE_KEY = 'empListColumns';

function empAvailableColumns() {
  return EMP_COLUMNS.filter(c => !c.roles || c.roles.includes(currentUser?.role));
}

function loadEmpColumnPrefs() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(EMP_COLUMNS_STORAGE_KEY) || 'null'); } catch { /* ignore malformed value */ }
  const available = new Set(empAvailableColumns().map(c => c.key));
  if (Array.isArray(saved)) return new Set(saved.filter(k => available.has(k)));
  return new Set(EMP_COLUMNS.filter(c => c.default).map(c => c.key));
}
// Loaded lazily (not at script-parse time) since it depends on
// currentUser.role for the roles-gated columns, and currentUser isn't set
// yet until login completes — see empAvailableColumns.
let empVisibleColumns = null;
function ensureEmpColumnPrefsLoaded() { if (empVisibleColumns === null) empVisibleColumns = loadEmpColumnPrefs(); }

function saveEmpColumnPrefs() { localStorage.setItem(EMP_COLUMNS_STORAGE_KEY, JSON.stringify([...empVisibleColumns])); }

function toggleEmpColumn(key) {
  if (empVisibleColumns.has(key)) empVisibleColumns.delete(key); else empVisibleColumns.add(key);
  saveEmpColumnPrefs();
  renderEmpColumnsPicker();
  renderEmpTable();
}

function resetEmpColumns() {
  empVisibleColumns = new Set(EMP_COLUMNS.filter(c => c.default).map(c => c.key));
  saveEmpColumnPrefs();
  renderEmpColumnsPicker();
  renderEmpTable();
}

function toggleEmpColumnPicker() {
  const panel = document.getElementById('empColumnsPanel');
  const opening = panel.classList.contains('hidden');
  if (opening) renderEmpColumnsPicker();
  panel.classList.toggle('hidden');
}
document.addEventListener('click', e => {
  if (!document.getElementById('empColumnsBtn')?.contains(e.target) && !document.getElementById('empColumnsPanel')?.contains(e.target)) {
    document.getElementById('empColumnsPanel')?.classList.add('hidden');
  }
});

function renderEmpColumnsPicker() {
  ensureEmpColumnPrefsLoaded();
  document.getElementById('empColumnsList').innerHTML = empAvailableColumns().map(c => `
    <label class="flex items-center gap-2 text-sm text-slate-700 cursor-pointer py-0.5">
      <input type="checkbox" class="rounded" ${empVisibleColumns.has(c.key)?'checked':''} onchange="toggleEmpColumn('${c.key}')"/>
      ${esc(c.label)}
    </label>`).join('');
}

function setEmpSort(key) { empList.setSort(key); renderEmpTable(); }
function setEmpPageSize(size) { empList.setPageSize(size); renderEmpTable(); }
function empPagePrev() { empList.prevPage(); renderEmpTable(); }
function empPageNext() { empList.nextPage(empFilteredData.length); renderEmpTable(); }

function filterEmployees() {
  const q = document.getElementById('empSearch').value.toLowerCase();
  const s = document.getElementById('empStatusFilter').value;
  empFilteredData = employees.filter(e => {
    const mQ = !q || [e.full_name,e.preferred_name,e.employee_id,e.ic_number,e.designation,e.department].some(v=>v?.toLowerCase().includes(q));
    const mS = !s || e.status === s;
    return mQ && mS;
  });
  empList.resetPage();
  renderEmpTable();
}

function renderEmpTableHead() {
  ensureEmpColumnPrefsLoaded();
  const cols = empAvailableColumns().filter(c => empVisibleColumns.has(c.key));
  document.getElementById('empTableHeadRow').innerHTML = `
    <th class="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase cursor-pointer select-none whitespace-nowrap" onclick="setEmpSort('full_name')">Name<span class="emp-sort-arrow" data-sort-key="full_name"></span></th>
    ${cols.map(c => `<th class="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase cursor-pointer select-none whitespace-nowrap" onclick="setEmpSort('${c.sortKey}')">${esc(c.label)}<span class="emp-sort-arrow" data-sort-key="${c.sortKey}"></span></th>`).join('')}
    <th class="px-4 py-3"></th>
  `;
}

function renderEmpTable() {
  const tbody = document.getElementById('empTableBody');
  const empty = document.getElementById('empEmpty');
  const pagination = document.getElementById('empPagination');
  renderEmpTableHead();
  empList.updateSortArrows('.emp-sort-arrow');
  if (!empFilteredData.length) { tbody.innerHTML=''; empty.classList.remove('hidden'); pagination.classList.add('hidden'); return; }
  empty.classList.add('hidden');
  pagination.classList.remove('hidden');
  document.getElementById('empPageSize').value = String(empList.pageSize);

  const { pageItems, start, total } = empList.view(empFilteredData);
  document.getElementById('empPageInfo').textContent =
    `${start + 1}-${Math.min(start + empList.pageSize, total)} of ${total}`;

  const cols = empAvailableColumns().filter(c => empVisibleColumns.has(c.key));
  tbody.innerHTML = pageItems.map(e=>`
    <tr class="hover:bg-slate-50 transition cursor-pointer" onclick="viewEmployee('${esc(e.employee_id)}')">
      <td class="px-4 py-3">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 text-xs font-bold flex-shrink-0">${e.full_name.split(' ').slice(0,2).map(w=>w[0]||'').join('').toUpperCase()}</div>
          <p class="font-medium whitespace-nowrap">${esc(combinedName(e.full_name, e.preferred_name))}</p>
        </div>
      </td>
      ${cols.map(c => `<td class="px-4 py-3 text-sm text-slate-600 whitespace-nowrap">${c.render(e)}</td>`).join('')}
      <td class="px-4 py-3 text-right">
        <svg class="w-4 h-4 text-slate-300 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      </td>
    </tr>
  `).join('');
}

// ---------------------------------------------------------------------------
// Employee View Modal
// ---------------------------------------------------------------------------
function viewEmployee(id) {
  const e = employees.find(em=>em.employee_id===id); if(!e) return;
  viewingId = id;
  const role = currentUser.role;
  const canWrite  = HR_MANAGE_ROLES.includes(role);
  const canToggle = HR_MANAGER_ONLY_ROLES.includes(role);
  const canNotes  = HR_MANAGE_ROLES.includes(role);
  document.getElementById('viewName').textContent = e.full_name;
  document.getElementById('viewMeta').textContent = `${e.employee_id} · ${e.designation} · ${e.department}`;
  const badge = document.getElementById('viewBadge');
  badge.textContent = e.status;
  badge.className = `badge ${e.status==='Active'?'bg-emerald-100 text-emerald-700':'bg-slate-100 text-slate-500'}`;
  document.getElementById('vt-notes-btn').classList.toggle('hidden', !canNotes);
  // Employee document compliance tracking is HR-only end to end (matches
  // routers/employee_documents.py's require_roles("hr_manager","hr_admin")
  // — narrower than canWrite, which also allows superadmin).
  document.getElementById('vt-documents-btn').classList.toggle('hidden', !HR_STAFF_ROLES.includes(role));
  document.getElementById('noteForm').classList.toggle('hidden', !canNotes);
  document.getElementById('viewEditBtn').classList.toggle('hidden', !canWrite);
  document.getElementById('viewToggleBtn').classList.toggle('hidden', !canToggle);
  document.getElementById('viewFileResignBtn').classList.toggle('hidden', !canWrite || e.status !== 'Active');
  const tb = document.getElementById('viewToggleBtn');
  tb.textContent = e.status==='Active' ? 'Deactivate' : 'Activate';
  tb.style.color = e.status==='Active' ? '#dc2626' : '#059669';
  const reportsToEmp = e.reports_to ? (employees||[]).find(x=>x.employee_id===e.reports_to) : null;
  const rt = e.reports_to===e.employee_id ? '⭐ CEO / Top of Org'
    : (e.reports_to ? `${reportsToEmp?displayName(reportsToEmp.full_name,reportsToEmp.preferred_name):e.reports_to} (${e.reports_to})` : '—');
  document.getElementById('vt-personal').innerHTML = vgrid([
    ['Full Name',e.full_name,false,true],['Preferred Name',e.preferred_name||'—'],
    ['IC Number',e.ic_number,true],['Passport No.',e.passport_number||'—'],
    ['Nationality',e.nationality],['Race',e.race],['Religion',e.religion],['Gender',e.gender],
    ['Date of Birth',fmtDate(e.date_of_birth)],['Marital Status',e.marital_status],
    ['Personal Email',e.personal_email||'—'],['Phone',e.phone],
    ['Address',e.address||'—',false,true],
  ]);
  document.getElementById('vt-employment').innerHTML = vgrid([
    ['Department',e.department],['Designation',e.designation],
    ['Employment Type',e.employment_type],['Start Date',fmtDate(e.start_date)],
    ['Probation End',fmtDate(e.probation_end_date)],['Contract End',fmtDate(e.contract_end_date)],
    ['Resign Date',fmtDate(e.resign_date)],['Last Working Day',fmtDate(e.last_working_day)],
    ['Work Email',e.work_email||'—'],['Reports To',rt],
  ]) + `<div id="relatedContracts" class="mt-6"></div>`;
  loadRelatedContracts(e.employee_id);
  document.getElementById('vt-statutory').innerHTML = vgrid([
    ['EPF Number',e.epf_number||'—',true],['SOCSO Number',e.socso_number||'—',true],
    ['Income Tax No.',e.income_tax_number||'—',true],
    ['Basic Salary',e.basic_salary?fmtCurrency(e.basic_salary):'—'],
    ['Bank Name',e.bank_name||'—'],['Bank Account',e.bank_account||'—',true],
  ]);
  loadEmployeeLocations(id);
  loadEmployeeCompensationTab(id);
  switchViewTab('vt-personal');
  document.getElementById('viewModal').classList.remove('hidden');
}

function vgrid(fields) {
  return `<div class="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">${
    fields.map(([label,value,mono,wide])=>`
      <div class="${wide?'col-span-2 md:col-span-3':''}">
        <p class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">${label}</p>
        <p class="text-sm text-slate-800 ${mono?'font-mono':''}">${esc(String(value??'—'))}</p>
      </div>`).join('')
  }</div>`;
}

function switchViewTab(name) {
  VIEW_TABS.forEach(t=>{
    document.getElementById(t)?.classList.toggle('hidden',t!==name);
    const btn=document.querySelector(`[data-vtab="${t}"]`);
    if(btn){btn.classList.toggle('view-tab-active',t===name);btn.classList.toggle('text-slate-500',t!==name);}
  });
  if(name==='vt-notes') loadNotes();
  if(name==='vt-documents') loadEmployeeDocuments(viewingId);
}

function closeViewModal() { closeModal('viewModal', () => viewingId=null); }

async function loadEmployeeLocations(empId) {
  const el = document.getElementById('vt-locations');
  if (!el) return;
  try {
    const res = await api(`/api/employees/${empId}/locations`);
    if (!res || !res.ok) {
      el.innerHTML = '<p class="text-slate-500">No locations assigned</p>';
      return;
    }
    const data = await res.json();
    if (!data.locations || data.locations.length === 0) {
      el.innerHTML = '<p class="text-slate-500">No locations assigned</p>';
      return;
    }
    el.innerHTML = `
      <div class="space-y-4">
        <h3 class="font-medium text-slate-800">Location Assignments</h3>
        <div class="grid gap-3">
          ${data.locations.map(loc => `
            <div class="border border-slate-200 rounded-lg p-4 hover:bg-slate-50 transition">
              <div class="flex items-start justify-between">
                <div>
                  <p class="font-medium text-slate-800">${esc(loc.name)}</p>
                  <p class="text-xs text-slate-500 mt-1">
                    <span class="inline-block mr-3">📍 ${esc(loc.city)}</span>
                    <span class="inline-block">${esc(loc.state)}</span>
                  </p>
                  <div class="mt-2 space-y-1 text-sm text-slate-600">
                    <p><strong>Type:</strong> ${esc(loc.assignment_type)}</p>
                    <p><strong>Start:</strong> ${fmtDate(loc.start_date)}</p>
                    ${loc.end_date ? `<p><strong>End:</strong> ${fmtDate(loc.end_date)}</p>` : ''}
                    <p><strong>Status:</strong> <span class="badge ${loc.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}">${loc.is_active ? 'Active' : 'Inactive'}</span></p>
                  </div>
                </div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  } catch (err) {
    console.error('Error loading locations:', err);
    el.innerHTML = '<p class="text-red-600">Error loading locations</p>';
  }
}

async function loadRelatedContracts(empId) {
  const el=document.getElementById('relatedContracts');
  if(!el) return;
  const canRehire=HR_MANAGE_ROLES.includes(currentUser?.role);
  try {
    const r=await api(`/api/employees/${empId}/related-contracts`);
    if(!r.ok){el.innerHTML='';return;}
    const contracts=await r.json();
    const STATUS_COLOR={'Active':'bg-green-100 text-green-700','Inactive':'bg-slate-100 text-slate-500'};
    const TYPE_COLOR={'Permanent':'bg-blue-100 text-blue-700','Contract':'bg-orange-100 text-orange-700','Part-Time':'bg-purple-100 text-purple-700','Internship':'bg-yellow-100 text-yellow-700'};
    el.innerHTML=`
      <div class="border-t border-slate-200 pt-5">
        <div class="flex items-center justify-between mb-3">
          <p class="text-xs font-semibold text-slate-400 uppercase tracking-wide">Other Contracts — Same Person</p>
          ${canRehire?`<button onclick="startRehire('${empId}')" class="btn-primary text-xs px-3 py-1.5">+ Rehire</button>`:''}
        </div>
        ${contracts.length?`<div class="space-y-2">${contracts.map(c=>`
          <div class="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 px-4 py-3 cursor-pointer hover:bg-slate-100 transition" onclick="closeViewModal();viewEmployee('${c.employee_id}')">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-medium text-slate-700">${esc(c.employee_id)}</span>
                <span class="badge text-xs ${TYPE_COLOR[c.employment_type]||'bg-slate-100 text-slate-600'}">${esc(c.employment_type)}</span>
                <span class="badge text-xs ${STATUS_COLOR[c.status]||'bg-slate-100 text-slate-600'}">${esc(c.status)}</span>
              </div>
              <p class="text-xs text-slate-500 mt-0.5">${esc(c.designation)} · ${esc(c.department)}</p>
              <p class="text-xs text-slate-400 mt-0.5">${fmtDate(c.start_date)}${c.contract_end_date?' → '+fmtDate(c.contract_end_date):' → present'}</p>
            </div>
            <svg class="w-4 h-4 text-slate-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
          </div>`).join('')}</div>`
        :`<p class="text-xs text-slate-400">No other contracts on record for this person.</p>${canRehire?'':`<p class="text-xs text-slate-400 mt-1">Contact HR to process a rehire.</p>`}`}
      </div>`;
  } catch(e){ el.innerHTML=''; }
}

async function startRehire(fromEmpId) {
  const r=await api(`/api/employees/${fromEmpId}/rehire-prefill`);
  if(!r.ok) return;
  const pre=await r.json();
  // Open modal first, then close view so re-renders don't dismiss it
  openAddModal();
  document.getElementById('viewModal').classList.add('hidden'); viewingId=null;
  // Fill personal fields after modal opens
  await new Promise(res=>setTimeout(res,50));
  const fields={
    fFullName:pre.full_name, fPreferredName:pre.preferred_name||'',
    fIcNumber:pre.ic_number, fPassportNumber:pre.passport_number||'',
    fNationality:pre.nationality||'Malaysian',
    fPersonalEmail:pre.personal_email||'', fPhone:pre.phone||'',
    fAddress:pre.address||''
  };
  Object.entries(fields).forEach(([id,val])=>{
    const el=document.getElementById(id);
    if(el) el.value=val||'';
  });
  // Set select fields
  ['fGender','fRace','fReligion','fMaritalStatus'].forEach(id=>{
    const el=document.getElementById(id);
    const val={fGender:pre.gender,fRace:pre.race,fReligion:pre.religion,fMaritalStatus:pre.marital_status}[id];
    if(el&&val) el.value=val;
  });
  if(pre.date_of_birth) document.getElementById('fDateOfBirth').value=pre.date_of_birth;
  // Switch to personal tab so user sees the prefilled data
  switchTab('personal');
  // Add a banner so user knows this is a rehire
  const form=document.getElementById('empForm');
  if(form&&!document.getElementById('rehireBanner')){
    const banner=document.createElement('div');
    banner.id='rehireBanner';
    banner.className='mx-6 mt-4 px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700';
    banner.innerHTML=`<strong>Rehire:</strong> Personal details pre-filled from ${esc(fromEmpId)}. Assign a new Employee ID and update contract details.`;
    form.prepend(banner);
  }
}

function editFromView() {
  const e=employees.find(em=>em.employee_id===viewingId); if(!e) return;
  closeViewModal(); openEditModal(e);
}

async function toggleStatusFromView() {
  const e=employees.find(em=>em.employee_id===viewingId); if(!e) return;
  const newStatus=e.status==='Active'?'Inactive':'Active';
  const res=await api(`/api/employees/${viewingId}/status`,{method:'PATCH',body:JSON.stringify({status:newStatus})});
  if(res?.ok){
    const updated=await res.json();
    const idx=employees.findIndex(em=>em.employee_id===viewingId);
    if(idx>=0) employees[idx]=updated;
    closeViewModal(); filterEmployees(); renderDashboard();
  }
}

// ---------------------------------------------------------------------------
// HR Notes
// ---------------------------------------------------------------------------
async function loadNotes() {
  if(!viewingId) return;
  const [notesRes, obRes] = await Promise.all([
    api(`/api/employees/${viewingId}/notes`),
    api(`/api/employees/${viewingId}/ob-history`).catch(()=>null)
  ]);
  if(!notesRes||!notesRes.ok) return;
  const notes=await notesRes.json();
  const obLogs=obRes?.ok ? await obRes.json() : [];
  const canDelete=HR_MANAGER_ONLY_ROLES.includes(currentUser.role);

  const notesHtml=notes.length?notes.map(n=>`
    <div class="rounded-xl border border-slate-200 p-4 bg-white">
      <div class="flex items-start justify-between gap-2 mb-2">
        <span class="badge note-type-${n.note_type}">${n.note_type.charAt(0).toUpperCase()+n.note_type.slice(1)}</span>
        ${canDelete?`<button onclick="deleteNote('${viewingId}',${n.id})" class="text-slate-300 hover:text-red-500 transition">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
        </button>`:''}
      </div>
      <p class="text-sm text-slate-700 whitespace-pre-wrap">${esc(n.body)}</p>
      <p class="text-xs text-slate-400 mt-2">${esc(n.created_by)} · ${fmtDateTime(n.created_at, true)}</p>
    </div>
  `).join(''):'<p class="text-sm text-slate-400 text-center py-4">No notes yet.</p>';

  const OB_ROLE_COLORS_MAP={'employee':'bg-purple-100 text-purple-700','manager':'bg-yellow-100 text-yellow-700','hr_admin':'bg-cyan-100 text-cyan-700','hr_manager':'bg-green-100 text-green-700','superadmin':'bg-red-100 text-red-700'};
  const OB_ROLE_LABELS_MAP={'employee':'Employee','manager':'Manager','hr_admin':'HR Admin','hr_manager':'HR Manager','superadmin':'Platform Admin'};
  const OB_TYPE_COLORS={'onboarding':'bg-blue-100 text-blue-700','offboarding':'bg-orange-100 text-orange-700'};
  const obHtml=obLogs.length?`
    <div class="mt-6">
      <p class="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Onboarding / Offboarding History</p>
      <div class="space-y-2">
        ${obLogs.map(e=>`
          <div class="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
            <div class="flex items-center justify-between flex-wrap gap-1 mb-1">
              <div class="flex items-center gap-2">
                <span class="badge text-xs ${statusColor(OB_TYPE_COLORS, e.ob_type)}">${e.ob_type.charAt(0).toUpperCase()+e.ob_type.slice(1)}</span>
                <span class="text-sm font-medium text-slate-700">${esc(e.action)}</span>
              </div>
              <span class="text-xs text-slate-400">${fmtDateTime(e.created_at)}</span>
            </div>
            <p class="text-xs text-slate-600">${esc(e.detail||'')}</p>
            <div class="flex items-center gap-2 mt-1">
              <span class="text-xs text-slate-500">${esc(e.performed_by)}</span>
              <span class="badge text-xs ${OB_ROLE_COLORS_MAP[e.performer_role]||'bg-slate-100 text-slate-600'}">${OB_ROLE_LABELS_MAP[e.performer_role]||e.performer_role}</span>
            </div>
          </div>`).join('')}
      </div>
    </div>`:'';

  document.getElementById('notesList').innerHTML=notesHtml+obHtml;
}

const submitNote = guardAsync(async function() {
  const body=document.getElementById('noteBody').value.trim();
  const type=document.getElementById('noteType').value;
  const err=document.getElementById('noteError');
  if(!body){err.textContent='Note cannot be empty';err.classList.remove('hidden');return;}
  err.classList.add('hidden');
  const res=await api(`/api/employees/${viewingId}/notes`,{method:'POST',body:JSON.stringify({note_type:type,body})});
  if(res?.ok){document.getElementById('noteBody').value='';loadNotes();}
});

async function deleteNote(empId,noteId) {
  if(!confirm('Delete this note?')) return;
  const res=await api(`/api/employees/${empId}/notes/${noteId}`,{method:'DELETE'});
  if(res?.ok||res?.status===204) loadNotes();
}

// ---------------------------------------------------------------------------
// Add/Edit Employee Modal
// ---------------------------------------------------------------------------
function populateMetaSelects() {
  const sel=(id,items)=>{
    const el=document.getElementById(id); if(!el) return;
    const cur=el.value;
    Array.from(el.options).filter(o=>o.value&&o.value!=='SELF').forEach(o=>o.remove());
    items.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o);});
    if(cur) el.value=cur;
  };
  sel('fRace',meta.races||[]); sel('fReligion',meta.religions||[]);
  sel('fMaritalStatus',meta.marital_statuses||[]); sel('fEmploymentType',meta.employment_types||[]);
  const bk=document.getElementById('fBankName');
  if(bk){while(bk.options.length>1)bk.remove(1);(meta.banks||[]).forEach(b=>{const o=document.createElement('option');o.value=b;o.textContent=b;bk.appendChild(o);});}
  // User roles — checkboxes + primary dropdown. Superadmin (creating other
  // platform-level accounts) still sees the static meta.roles list; every
  // other institution's role picker is now built-ins + that institution's
  // custom_roles (rolesCache, see routers/roles.py / Settings > Roles).
  const roleList=currentUser?.role==='superadmin'
    ? (meta.roles||[]).map(r=>({role_key:r, display_name:meta.role_labels?.[r]||r}))
    : rolesCache;
  const rolesWrap=document.getElementById('uRolesWrap');
  if(rolesWrap){
    rolesWrap.innerHTML=roleList.map(r=>`
      <label class="flex items-center gap-1.5 text-sm cursor-pointer">
        <input type="checkbox" class="uRoleCheck w-4 h-4" value="${r.role_key}" onchange="syncRolePrimary()"/>
        ${esc(r.display_name)}
      </label>`).join('');
  }
  const roleEl=document.getElementById('uRole');
  if(roleEl){
    roleEl.innerHTML='';
    roleList.forEach(r=>{const o=document.createElement('option');o.value=r.role_key;o.textContent=r.display_name;roleEl.appendChild(o);});
  }
}

function syncRolePrimary() {
  const checked=[...document.querySelectorAll('.uRoleCheck:checked')].map(c=>c.value);
  const roleEl=document.getElementById('uRole');
  const cur=roleEl.value;
  Array.from(roleEl.options).forEach(o=>o.disabled=!checked.includes(o.value));
  if(!checked.includes(cur)&&checked.length) roleEl.value=checked[0];
}

function applyEmployeeIdEditability() {
  const canEditId=currentUser?.role==='hr_manager';
  const input=document.getElementById('fEmployeeId');
  input.readOnly=!canEditId;
  input.classList.toggle('bg-slate-50', !canEditId);
  document.getElementById('fEmployeeIdHint').classList.toggle('hidden', !canEditId);
}

function toggleSalaryTypeFields() {
  const isHourly=document.getElementById('fSalaryType').value==='Hourly';
  document.getElementById('fBasicSalaryWrap').classList.toggle('hidden', isHourly);
  document.getElementById('fHourlyRateWrap').classList.toggle('hidden', !isHourly);
}

function openAddModal() {
  currentEmpId=null;
  document.getElementById('empModalTitle').textContent='Add Employee';
  document.getElementById('empForm').reset();
  applyEmployeeIdEditability();
  toggleSalaryTypeFields();
  const rt=document.getElementById('fReportsTo');
  while(rt.options.length>2) rt.remove(2);
  employees.filter(e=>e.status==='Active').forEach(e=>{const o=document.createElement('option');o.value=e.employee_id;o.textContent=`${e.employee_id} — ${displayName(e.full_name,e.preferred_name)}`;rt.appendChild(o);});
  initEmployeeSearchSelect('fReportsTo', 'Search employee…');
  loadLocationDropdown();
  document.getElementById('empDependentsTabBtn').classList.add('hidden'); // dependents need an existing employee_id
  currentTab='personal'; switchTab('personal');
  document.getElementById('empModal').classList.remove('hidden');
}

async function openEditModal(e) {
  currentEmpId=e.employee_id;
  document.getElementById('empModalTitle').textContent=`Edit — ${e.full_name}`;
  const f=id=>document.getElementById(id);
  f('fEmployeeId').value=e.employee_id||''; applyEmployeeIdEditability();
  f('fFullName').value=e.full_name||''; f('fPreferredName').value=e.preferred_name||'';
  f('fIcNumber').value=e.ic_number||''; f('fPassportNumber').value=e.passport_number||'';
  f('fNationality').value=e.nationality||'Malaysian'; f('fRace').value=e.race||'';
  f('fReligion').value=e.religion||''; f('fGender').value=e.gender||'';
  f('fDateOfBirth').value=e.date_of_birth||''; f('fMaritalStatus').value=e.marital_status||'';
  f('fPersonalEmail').value=e.personal_email||''; f('fPhone').value=e.phone||'';
  f('fAddress').value=e.address||''; f('fDepartment').value=e.department||'';
  f('fDesignation').value=e.designation||''; f('fEmploymentType').value=e.employment_type||'';
  f('fStartDate').value=e.start_date||''; f('fProbationEndDate').value=e.probation_end_date||'';
  f('fContractEndDate').value=e.contract_end_date||''; f('fResignDate').value=e.resign_date||'';
  f('fLastWorkingDay').value=e.last_working_day||'';
  f('fWorkEmail').value=e.work_email||'';
  f('fEpfNumber').value=e.epf_number||''; f('fSocsoNumber').value=e.socso_number||'';
  f('fIncomeTaxNumber').value=e.income_tax_number||''; f('fBankName').value=e.bank_name||'';
  f('fBankAccount').value=e.bank_account||''; f('fBasicSalary').value=e.basic_salary||0;
  f('fNumChildren').value=e.num_children||0;
  f('fSalaryType').value=e.salary_type||'Monthly'; f('fHourlyRate').value=e.hourly_rate||0;
  toggleSalaryTypeFields();
  const rt=f('fReportsTo');
  while(rt.options.length>2) rt.remove(2);
  employees.filter(em=>em.status==='Active'&&em.employee_id!==e.employee_id).forEach(em=>{const o=document.createElement('option');o.value=em.employee_id;o.textContent=`${em.employee_id} — ${displayName(em.full_name,em.preferred_name)}`;rt.appendChild(o);});
  rt.value=e.reports_to===e.employee_id?'SELF':(e.reports_to||'');
  initEmployeeSearchSelect('fReportsTo', 'Search employee…');
  await loadLocationDropdown();
  f('fDefaultLocation').value=e.default_location_id||'';
  document.getElementById('empDependentsTabBtn').classList.remove('hidden');
  currentTab='personal'; switchTab('personal');
  document.getElementById('empModal').classList.remove('hidden');
}

function closeEmpModal() { closeModal('empModal', () => currentEmpId=null); }

function activeTabs(){ return currentEmpId ? TABS : TABS.filter(t=>t!=='dependents'); }

function switchTab(name) {
  TABS.forEach(t=>{
    document.getElementById(`tab-${t}`)?.classList.toggle('hidden',t!==name);
    const btn=document.querySelector(`[data-tab="${t}"]`);
    if(btn){btn.classList.toggle('tab-active',t===name);btn.classList.toggle('text-slate-500',t!==name);}
  });
  currentTab=name;
  const tabs=activeTabs();
  const idx=tabs.indexOf(name);
  document.getElementById('prevTabBtn').classList.toggle('hidden',idx===0);
  document.getElementById('nextTabBtn').classList.toggle('hidden',idx===tabs.length-1);
  document.getElementById('empSubmitBtn').classList.toggle('hidden',idx!==tabs.length-1);
  if(name==='dependents') loadEmpDependentsTab();
}
function nextTab(){const tabs=activeTabs();const i=tabs.indexOf(currentTab);if(i<tabs.length-1)switchTab(tabs[i+1]);}
function prevTab(){const tabs=activeTabs();const i=tabs.indexOf(currentTab);if(i>0)switchTab(tabs[i-1]);}

async function submitEmpForm(e) {
  e.preventDefault();
  const err=document.getElementById('empFormErr');
  err.classList.add('hidden');
  const g=id=>document.getElementById(id).value;
  const body={
    employee_id:(currentUser?.role==='hr_manager' && g('fEmployeeId').trim())?g('fEmployeeId').trim():null,
    full_name:g('fFullName').trim(),preferred_name:g('fPreferredName').trim()||null,
    ic_number:g('fIcNumber').trim(),passport_number:g('fPassportNumber').trim()||null,
    nationality:g('fNationality').trim()||'Malaysian',race:g('fRace'),religion:g('fReligion'),
    gender:g('fGender'),date_of_birth:g('fDateOfBirth'),marital_status:g('fMaritalStatus'),
    personal_email:g('fPersonalEmail').trim()||null,phone:g('fPhone').trim(),
    address:g('fAddress').trim()||null,department:g('fDepartment').trim(),
    designation:g('fDesignation').trim(),employment_type:g('fEmploymentType'),
    start_date:g('fStartDate'),probation_end_date:g('fProbationEndDate')||null,
    contract_end_date:g('fContractEndDate')||null,resign_date:g('fResignDate')||null,
    last_working_day:g('fLastWorkingDay')||null,
    work_email:g('fWorkEmail').trim()||null,
    epf_number:g('fEpfNumber').trim()||null,socso_number:g('fSocsoNumber').trim()||null,
    income_tax_number:g('fIncomeTaxNumber').trim()||null,bank_name:g('fBankName')||null,
    bank_account:g('fBankAccount').trim()||null,
    basic_salary:parseFloat(g('fBasicSalary'))||0,
    num_children:parseInt(g('fNumChildren'))||0,
    salary_type:g('fSalaryType'),
    hourly_rate:parseFloat(g('fHourlyRate'))||0,
    reports_to:g('fReportsTo')||null,
    default_location_id:parseInt(g('fDefaultLocation'))||null,
  };
  const url=currentEmpId?`/api/employees/${currentEmpId}`:'/api/employees';
  const res=await api(url,{method:currentEmpId?'PUT':'POST',body:JSON.stringify(body)});
  if(!res) return;
  if(!res.ok){const d=await res.json();err.textContent=d.detail||'Failed';err.classList.remove('hidden');return;}
  const saved=await res.json();
  if(currentEmpId){const idx=employees.findIndex(em=>em.employee_id===currentEmpId);if(idx>=0)employees[idx]=saved;}
  else employees.unshift(saved);
  closeEmpModal(); filterEmployees(); renderDashboard();
  if(saved.pay_grade_warning) alert(saved.pay_grade_warning);
}

// ---------------------------------------------------------------------------

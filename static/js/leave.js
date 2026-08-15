// Leave / Holiday Manager
// ---------------------------------------------------------------------------
let leaveTypesCache=[], leaveFilter='', leaveApprovalFilter='Pending Approval', leaveHolidaysCache=[];
const LEAVE_STATUS_COLORS={'Pending Approval':'bg-amber-100 text-amber-700','Approved':'bg-green-100 text-green-700','Rejected':'bg-red-100 text-red-700','Cancelled':'bg-slate-100 text-slate-500'};

function isLeaveManager() {
  return ['superadmin','hr_manager','hr_admin'].includes(currentUser?.role);
}
function canApproveLeave() {
  return ['superadmin','hr_manager','hr_admin','manager'].includes(currentUser?.role);
}

// ---------------------------------------------------------------------------
// My Leave
// ---------------------------------------------------------------------------
async function loadLeaveTypesCache() {
  const res=await api('/api/leave/types');
  leaveTypesCache=res?.ok?await res.json():[];
}

async function loadLeavePage() {
  await loadLeaveTypesCache();
  await loadHolidaysCacheForYear(new Date().getFullYear());
  await renderLeaveBalanceCards();
  await loadLeaveApplications();
}

async function renderLeaveBalanceCards() {
  const wrap=document.getElementById('leaveBalanceCards');
  const empId=currentUser?.employee_id;
  if(!empId){ wrap.innerHTML=''; return; }
  const res=await api(`/api/leave/balances?year=${new Date().getFullYear()}`);
  if(!res?.ok){ wrap.innerHTML=''; return; }
  const balances=await res.json();
  wrap.innerHTML=balances.map(b=>{
    const entitled=b.accrued_days ?? b.entitled_days;
    const available=entitled+b.carried_forward_days-b.used_days;
    return `<div class="bg-white border border-slate-200 rounded-xl p-4">
      <p class="text-xs text-slate-400 uppercase tracking-wide mb-1">${esc(b.leave_type_name)}</p>
      <p class="text-2xl font-semibold text-slate-800">${available}</p>
      <p class="text-xs text-slate-400 mt-1">of ${entitled+b.carried_forward_days} day(s) left</p>
    </div>`;
  }).join('');
}

async function loadLeaveApplications() {
  const listEl=document.getElementById('leaveAppList');
  const emptyEl=document.getElementById('leaveAppEmpty');
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  let url='/api/leave/applications';
  if(leaveFilter) url+=`?status=${encodeURIComponent(leaveFilter)}`;
  const res=await api(url);
  if(!res?.ok){ listEl.innerHTML=''; return; }
  const rows=await res.json();
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(a=>`
    <div class="bg-white border border-slate-200 rounded-xl p-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-0.5 flex-wrap">
            <p class="font-medium text-slate-800">${esc(a.leave_type_name)}</p>
            <span class="badge ${LEAVE_STATUS_COLORS[a.status]||'bg-slate-100 text-slate-600'} text-xs">${a.status}</span>
          </div>
          <p class="text-xs text-slate-500">${fmtDate(a.start_date)} → ${fmtDate(a.end_date)} · ${a.days_count} working day(s)</p>
          ${a.reason?`<p class="text-xs text-slate-400 italic mt-1">${esc(a.reason)}</p>`:''}
          ${a.notes?`<p class="text-xs text-slate-500 mt-1">Note: ${esc(a.notes)}</p>`:''}
          ${a.attachment?`<a href="${a.attachment}" target="_blank" class="text-xs text-blue-600 hover:underline mt-1 inline-block">View attachment</a>`:''}
        </div>
        ${(a.status==='Pending Approval'||a.status==='Approved')?`<button onclick="cancelLeaveApplication(${a.id})" class="text-xs text-red-600 hover:text-red-700 flex-shrink-0">Cancel</button>`:''}
      </div>
      <p class="text-xs text-slate-400 mt-2">Applied ${fmtDate(a.created_at)}</p>
    </div>`).join('');
}

function setLeaveFilter(status) {
  leaveFilter=status;
  document.querySelectorAll('.leave-filter-btn').forEach(b=>b.classList.remove('leave-filter-active'));
  event?.target?.classList?.add('leave-filter-active');
  loadLeaveApplications();
}

async function cancelLeaveApplication(appId) {
  if(!confirm('Cancel this leave application?')) return;
  const res=await api(`/api/leave/applications/${appId}/status`,{method:'PATCH',body:JSON.stringify({status:'Cancelled'})});
  if(res?.ok){ loadLeaveApplications(); renderLeaveBalanceCards(); }
  else { const d=await res.json(); alert(d.detail||'Failed to cancel'); }
}

// ---------------------------------------------------------------------------
// Apply for Leave
// ---------------------------------------------------------------------------
let leaveApplyAttachment=null;
let leaveApplyBalancesCache=[];

async function openLeaveApplyModal() {
  document.getElementById('leaveApplyErr').classList.add('hidden');
  document.getElementById('leaveApplyReason').value='';
  document.getElementById('leaveApplyStart').value='';
  document.getElementById('leaveApplyEnd').value='';
  document.getElementById('leaveApplyAttachFile').value='';
  leaveApplyAttachment=null;

  const empWrap=document.getElementById('leaveApplyEmpWrap');
  if(isLeaveManager()||currentUser?.role==='manager'){
    empWrap.classList.remove('hidden');
    const sel=document.getElementById('leaveApplyEmpId');
    sel.innerHTML=employees.filter(e=>e.status==='Active').map(e=>`<option value="${e.employee_id}">${e.employee_id} — ${esc(e.full_name)}</option>`).join('');
    if(currentUser?.employee_id) sel.value=currentUser.employee_id;
  } else {
    empWrap.classList.add('hidden');
  }

  const typeSel=document.getElementById('leaveApplyTypeId');
  typeSel.innerHTML=leaveTypesCache.map(t=>{
    const shared=t.shares_entitlement_with_id?leaveTypesCache.find(x=>x.id===t.shares_entitlement_with_id):null;
    const label=shared?`${esc(t.name)} (shares with ${esc(shared.name)})`:`${esc(t.name)} (${t.annual_entitlement}/yr)`;
    return `<option value="${t.id}">${label}</option>`;
  }).join('');

  const empId=(isLeaveManager()||currentUser?.role==='manager')?document.getElementById('leaveApplyEmpId').value:currentUser?.employee_id;
  const res=await api(`/api/leave/balances?year=${new Date().getFullYear()}${empId?`&employee_id=${empId}`:''}`);
  leaveApplyBalancesCache=res?.ok?await res.json():[];

  updateLeaveApplyBalanceNote();
  document.getElementById('leaveApplyDaysPreview').textContent='';
  await populateLeaveApplyProjectField();
  document.getElementById('leaveApplyModal').classList.remove('hidden');
}

async function populateLeaveApplyProjectField() {
  const wrap=document.getElementById('leaveApplyProjectWrap');
  const sel=document.getElementById('leaveApplyProjectId');
  wrap.classList.add('hidden');
  sel.innerHTML='';
  const needed=await moduleHasProjectManagerStep('leave');
  if(!needed) return;
  const res=await api('/api/projects/mine');
  const myProjects=res?.ok?await res.json():[];
  if(!myProjects.length) return;  // no project to pick — step auto-skips
  sel.innerHTML=myProjects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');
  wrap.classList.remove('hidden');
}

function updateLeaveApplyBalanceNote() {
  const typeId=parseInt(document.getElementById('leaveApplyTypeId').value);
  const type=leaveTypesCache.find(t=>t.id===typeId);
  // A type that shares entitlement with another never has its own balance
  // row — its pool lives under the shared type's id.
  const balanceTypeId=type?.shares_entitlement_with_id||typeId;
  const sharedType=type?.shares_entitlement_with_id?leaveTypesCache.find(t=>t.id===type.shares_entitlement_with_id):null;
  const bal=leaveApplyBalancesCache.find(b=>b.leave_type_id===balanceTypeId);
  const note=document.getElementById('leaveApplyBalanceNote');
  const attachWrap=document.getElementById('leaveApplyAttachWrap');
  attachWrap.classList.toggle('hidden', !type?.requires_attachment);
  document.getElementById('leaveApplyAttachFile').required=!!type?.requires_attachment;
  const sharedSuffix=sharedType?` (shared with ${esc(sharedType.name)})`:'';
  const isMonthly=(sharedType||type)?.accrual_mode==='monthly';
  const period=isMonthly?'accrued so far':'this year';
  if(bal){
    // accrued_days already resolves to the full annual figure for
    // full_year types, and to the pro-rated earned-so-far figure for
    // monthly ones — see _accrued_days in routers/leave.py.
    const available=bal.accrued_days+bal.carried_forward_days-bal.used_days;
    note.textContent=`${available} day(s) available ${period}${sharedSuffix}`;
  } else if(sharedType){
    note.textContent=`${sharedType.annual_entitlement} day(s) available this year (new balance)${sharedSuffix}`;
  } else if(type){
    note.textContent=`${type.annual_entitlement} day(s) available this year (new balance)`;
  } else {
    note.textContent='';
  }
}

function ldLeaveComputeWorkdays(startStr, endStr) {
  if(!startStr||!endStr) return 0;
  const start=new Date(startStr+'T00:00:00'), end=new Date(endStr+'T00:00:00');
  if(end<start) return 0;
  const holidaySet=new Set(leaveHolidaysCache.map(h=>h.date));
  let count=0;
  const d=new Date(start);
  while(d<=end){
    const dow=d.getDay();
    const ds=d.toISOString().slice(0,10);
    if(dow!==0 && dow!==6 && !holidaySet.has(ds)) count++;
    d.setDate(d.getDate()+1);
  }
  return count;
}

function ldLeaveComputeCalendarDays(startStr, endStr) {
  if(!startStr||!endStr) return 0;
  const start=new Date(startStr+'T00:00:00'), end=new Date(endStr+'T00:00:00');
  if(end<start) return 0;
  return Math.round((end-start)/86400000)+1;
}

function updateLeaveApplyDaysPreview() {
  const start=document.getElementById('leaveApplyStart').value;
  const end=document.getElementById('leaveApplyEnd').value;
  const preview=document.getElementById('leaveApplyDaysPreview');
  if(!start||!end){ preview.textContent=''; return; }
  const typeId=parseInt(document.getElementById('leaveApplyTypeId').value);
  const type=leaveTypesCache.find(t=>t.id===typeId);
  if(type?.count_calendar_days){
    const days=ldLeaveComputeCalendarDays(start,end);
    preview.textContent=`≈ ${days} calendar day(s) will be deducted (weekends & public holidays included)`;
  } else {
    const days=ldLeaveComputeWorkdays(start,end);
    preview.textContent=`≈ ${days} working day(s) will be deducted (weekends & public holidays excluded)`;
  }
}

function handleLeaveAttachFile(e) {
  const file=e.target.files?.[0];
  if(!file) return;
  if(file.size>500*1024){ alert('File is too large. Please choose a file under ~500KB.'); e.target.value=''; return; }
  const reader=new FileReader();
  reader.onload=()=>{ leaveApplyAttachment=reader.result; };
  reader.readAsDataURL(file);
}

function closeLeaveApplyModal() {
  document.getElementById('leaveApplyModal').classList.add('hidden');
}

async function submitLeaveApplication(e) {
  e.preventDefault();
  const err=document.getElementById('leaveApplyErr');
  err.classList.add('hidden');
  const empId=(isLeaveManager()||currentUser?.role==='manager')?document.getElementById('leaveApplyEmpId').value:currentUser?.employee_id;
  const projectWrap=document.getElementById('leaveApplyProjectWrap');
  const body={
    employee_id: empId,
    leave_type_id: parseInt(document.getElementById('leaveApplyTypeId').value),
    start_date: document.getElementById('leaveApplyStart').value,
    end_date: document.getElementById('leaveApplyEnd').value,
    reason: document.getElementById('leaveApplyReason').value.trim()||null,
    attachment: leaveApplyAttachment,
    project_id: !projectWrap.classList.contains('hidden') && document.getElementById('leaveApplyProjectId').value
      ? parseInt(document.getElementById('leaveApplyProjectId').value) : null,
  };
  const res=await api('/api/leave/applications',{method:'POST',body:JSON.stringify(body)});
  if(res?.ok){
    closeLeaveApplyModal();
    showPage('leave-my');
  } else {
    const d=await res.json();
    err.textContent=d.detail||'Failed to submit application';
    err.classList.remove('hidden');
  }
}

// ---------------------------------------------------------------------------
// Leave Approvals (manager / HR)
// ---------------------------------------------------------------------------
async function loadLeaveApprovals() {
  const listEl=document.getElementById('leaveApprovalList');
  const emptyEl=document.getElementById('leaveApprovalEmpty');
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  let url='/api/leave/applications';
  if(leaveApprovalFilter) url+=`?status=${encodeURIComponent(leaveApprovalFilter)}`;
  const res=await api(url);
  if(!res?.ok){ listEl.innerHTML=''; return; }
  const rows=await res.json();
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(a=>`
    <div class="bg-white border border-slate-200 rounded-xl p-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-0.5 flex-wrap">
            <p class="font-medium text-slate-800">${esc(a.employee_name)}</p>
            <span class="badge ${LEAVE_STATUS_COLORS[a.status]||'bg-slate-100 text-slate-600'} text-xs">${a.status}</span>
          </div>
          <p class="text-xs text-slate-500">${esc(a.leave_type_name)} · ${fmtDate(a.start_date)} → ${fmtDate(a.end_date)} · ${a.days_count} day(s)</p>
          <p class="text-xs text-slate-400">${esc(a.department||'')}${a.designation?' · '+esc(a.designation):''}</p>
          ${a.reason?`<p class="text-xs text-slate-400 italic mt-1">${esc(a.reason)}</p>`:''}
          ${a.attachment?`<a href="${a.attachment}" target="_blank" class="text-xs text-blue-600 hover:underline mt-1 inline-block">View attachment</a>`:''}
        </div>
      </div>
      ${a.status==='Pending Approval'?`<div class="mt-3 flex gap-2">
        <button onclick="reviewLeaveApplication(${a.id},'Approved')" class="btn-primary text-xs px-3 py-1.5">Approve</button>
        <button onclick="reviewLeaveApplication(${a.id},'Rejected')" class="btn-ghost text-xs px-3 py-1.5 text-red-600">Reject</button>
      </div>`:''}
      <p class="text-xs text-slate-400 mt-2">Applied ${fmtDate(a.created_at)}</p>
    </div>`).join('');
}

function setLeaveApprovalFilter(status) {
  leaveApprovalFilter=status;
  document.querySelectorAll('.leave-appr-filter-btn').forEach(b=>b.classList.remove('leave-appr-filter-active'));
  event?.target?.classList?.add('leave-appr-filter-active');
  loadLeaveApprovals();
}

async function reviewLeaveApplication(appId, status) {
  const res=await api(`/api/leave/applications/${appId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  if(res?.ok) loadLeaveApprovals();
  else { const d=await res.json(); alert(d.detail||'Failed to update'); }
}

// ---------------------------------------------------------------------------
// Holiday Manager
// ---------------------------------------------------------------------------
async function loadHolidaysCacheForYear(year) {
  const res=await api(`/api/holidays?year=${year}`);
  leaveHolidaysCache=res?.ok?await res.json():[];
}

let hmLeaveTypesLoaded=false;

async function loadLeaveHolidaysPage() {
  const yearSel=document.getElementById('holidayYearSelect');
  const curYear=new Date().getFullYear();
  if(!yearSel.options.length){
    yearSel.innerHTML=[curYear-1,curYear,curYear+1,curYear+2].map(y=>`<option value="${y}">${y}</option>`).join('');
    yearSel.value=curYear;
  }
  hmLeaveTypesLoaded=false;
  switchHolidayManagerTab('holidays');
}

function switchHolidayManagerTab(tab) {
  document.getElementById('hmSubTab_holidays').classList.toggle('view-tab-active', tab==='holidays');
  document.getElementById('hmSubTab_leavetypes').classList.toggle('view-tab-active', tab==='leavetypes');
  document.getElementById('hmSubPanel_holidays').classList.toggle('hidden', tab!=='holidays');
  document.getElementById('hmSubPanel_leavetypes').classList.toggle('hidden', tab!=='leavetypes');
  if(tab==='holidays') loadHolidays();
  else if(tab==='leavetypes' && !hmLeaveTypesLoaded){
    hmLeaveTypesLoaded=true;
    loadLeaveTypesForManage();
  }
}

async function loadHolidays() {
  const year=document.getElementById('holidayYearSelect').value;
  await loadHolidaysCacheForYear(year);
  const tbody=document.getElementById('holidayTableBody');
  const emptyEl=document.getElementById('holidayEmpty');
  if(!leaveHolidaysCache.length){
    tbody.innerHTML='';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');
  const dayNames=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  tbody.innerHTML=leaveHolidaysCache.map(h=>{
    const d=new Date(h.date+'T00:00:00');
    return `<tr class="border-t border-slate-100">
      <td class="px-4 py-2">${fmtDate(h.date)}</td>
      <td class="px-4 py-2 text-slate-500">${dayNames[d.getDay()]}</td>
      <td class="px-4 py-2">${esc(h.name)}</td>
      <td class="px-4 py-2 text-right"><button onclick="deleteHoliday(${h.id})" class="text-slate-300 hover:text-red-500"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button></td>
    </tr>`;
  }).join('');
}

function openHolidayModal() {
  document.getElementById('holidayName').value='';
  document.getElementById('holidayDate').value='';
  document.getElementById('holidayModal').classList.remove('hidden');
}
function closeHolidayModal() { document.getElementById('holidayModal').classList.add('hidden'); }

async function submitHoliday(e) {
  e.preventDefault();
  const date=document.getElementById('holidayDate').value;
  const body={ name:document.getElementById('holidayName').value.trim(), date, year:parseInt(date.slice(0,4)) };
  const res=await api('/api/holidays',{method:'POST',body:JSON.stringify(body)});
  if(res?.ok){
    closeHolidayModal();
    document.getElementById('holidayYearSelect').value=body.year;
    loadHolidays();
  } else {
    const d=await res.json(); alert(d.detail||'Failed to add holiday');
  }
}

async function deleteHoliday(id) {
  if(!confirm('Remove this holiday?')) return;
  await api(`/api/holidays/${id}`,{method:'DELETE'});
  loadHolidays();
}

// ---------------------------------------------------------------------------
// Leave Types (management, shown under Holiday Manager page)
// ---------------------------------------------------------------------------
async function loadLeaveTypesForManage() {
  await loadLeaveTypesCache();
  const wrap=document.getElementById('leaveTypeList');
  wrap.innerHTML=leaveTypesCache.length?leaveTypesCache.map(t=>{
    const sharedType=t.shares_entitlement_with_id?leaveTypesCache.find(x=>x.id===t.shares_entitlement_with_id):null;
    return `
    <div class="flex items-center gap-2 py-2 border-b border-slate-100">
      <span class="flex-1 text-sm text-slate-700">${esc(t.name)}</span>
      ${sharedType
        ?`<span class="badge text-xs bg-amber-100 text-amber-700">Shares with ${esc(sharedType.name)}</span>`
        :`<span class="text-xs text-slate-400">${t.annual_entitlement} days/yr</span>`}
      ${t.count_calendar_days?'<span class="badge text-xs bg-slate-100 text-slate-600">Calendar days</span>':''}
      ${t.accrual_mode==='monthly'?'<span class="badge text-xs bg-teal-100 text-teal-700">Accrues monthly</span>':''}
      ${t.max_days_per_application?`<span class="badge text-xs bg-slate-100 text-slate-600">Max ${t.max_days_per_application}/app</span>`:''}
      ${t.max_days_per_month?`<span class="badge text-xs bg-slate-100 text-slate-600">Max ${t.max_days_per_month}/mo</span>`:''}
      ${t.requires_approval?'<span class="badge text-xs bg-blue-100 text-blue-700">Approval</span>':''}
      ${t.requires_attachment?'<span class="badge text-xs bg-purple-100 text-purple-700">Doc required</span>':''}
      ${t.carry_forward_enabled?`<span class="badge text-xs bg-amber-100 text-amber-700" title="${t.carry_forward_max_days?`Max ${t.carry_forward_max_days} days`:''}${t.carry_forward_max_days&&t.carry_forward_max_percent?' or ':''}${t.carry_forward_max_percent?`Max ${t.carry_forward_max_percent}% of balance`:''}${t.carry_forward_expiry_days?`, expires ${t.carry_forward_expiry_days}d into new year`:''}">Carries forward</span>`:''}
      <button onclick="openLeaveTypeModal(${t.id})" class="text-slate-300 hover:text-blue-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
      <button onclick="deleteLeaveType(${t.id})" class="text-slate-300 hover:text-red-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>`;
  }).join(''):'<p class="text-sm text-slate-400 text-center py-4">No leave types yet.</p>';
}

function openLeaveTypeModal(typeId) {
  document.getElementById('leaveTypeId').value=typeId||'';
  document.getElementById('leaveTypeModalTitle').textContent=typeId?'Edit Leave Type':'Add Leave Type';

  // Share-with options: any other active leave type that isn't itself
  // sharing with something (one level deep only — matches backend validation
  // in _validate_shares_entitlement), excluding this type itself.
  const sharesSel=document.getElementById('leaveTypeSharesWith');
  const options=leaveTypesCache.filter(t=>t.id!==typeId&&!t.shares_entitlement_with_id);
  sharesSel.innerHTML='<option value="">— No, tracks its own balance —</option>'
    +options.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('');

  if(typeId){
    const t=leaveTypesCache.find(x=>x.id===typeId);
    document.getElementById('leaveTypeName').value=t?.name||'';
    document.getElementById('leaveTypeEntitlement').value=t?.annual_entitlement||14;
    document.getElementById('leaveTypeCountMode').value=t?.count_calendar_days?'calendar':'working';
    document.getElementById('leaveTypeAccrualMode').value=t?.accrual_mode||'full_year';
    document.getElementById('leaveTypeMaxPerApp').value=t?.max_days_per_application||0;
    document.getElementById('leaveTypeMaxPerMonth').value=t?.max_days_per_month||0;
    document.getElementById('leaveTypeRequiresApproval').checked=!!t?.requires_approval;
    document.getElementById('leaveTypeRequiresAttachment').checked=!!t?.requires_attachment;
    document.getElementById('leaveTypeIsPaid').checked=t?.is_paid===undefined?true:!!t.is_paid;
    sharesSel.value=t?.shares_entitlement_with_id||'';
    document.getElementById('leaveTypeCarryForwardEnabled').checked=!!t?.carry_forward_enabled;
    document.getElementById('leaveTypeCarryMaxDays').value=t?.carry_forward_max_days||0;
    document.getElementById('leaveTypeCarryMaxPercent').value=t?.carry_forward_max_percent||0;
    document.getElementById('leaveTypeCarryExpiryDays').value=t?.carry_forward_expiry_days||0;
  } else {
    document.getElementById('leaveTypeName').value='';
    document.getElementById('leaveTypeEntitlement').value=14;
    document.getElementById('leaveTypeCountMode').value='working';
    document.getElementById('leaveTypeAccrualMode').value='full_year';
    document.getElementById('leaveTypeMaxPerApp').value=0;
    document.getElementById('leaveTypeMaxPerMonth').value=0;
    document.getElementById('leaveTypeRequiresApproval').checked=true;
    document.getElementById('leaveTypeRequiresAttachment').checked=false;
    document.getElementById('leaveTypeIsPaid').checked=true;
    sharesSel.value='';
    document.getElementById('leaveTypeCarryForwardEnabled').checked=false;
    document.getElementById('leaveTypeCarryMaxDays').value=0;
    document.getElementById('leaveTypeCarryMaxPercent').value=0;
    document.getElementById('leaveTypeCarryExpiryDays').value=0;
  }
  onLeaveTypeSharesChange();
  onLeaveTypeCarryForwardChange();
  document.getElementById('leaveTypeModal').classList.remove('hidden');
}
function closeLeaveTypeModal() { document.getElementById('leaveTypeModal').classList.add('hidden'); }

function onLeaveTypeSharesChange() {
  const sharing=!!document.getElementById('leaveTypeSharesWith').value;
  document.getElementById('leaveTypeEntitlementWrap').classList.toggle('hidden', sharing);
  document.getElementById('leaveTypeAccrualWrap').classList.toggle('hidden', sharing);
}

function onLeaveTypeCarryForwardChange() {
  const enabled=document.getElementById('leaveTypeCarryForwardEnabled').checked;
  document.getElementById('leaveTypeCarryForwardWrap').classList.toggle('hidden', !enabled);
}

async function submitLeaveType(e) {
  e.preventDefault();
  const id=document.getElementById('leaveTypeId').value;
  const sharesWith=document.getElementById('leaveTypeSharesWith').value;
  const body={
    name: document.getElementById('leaveTypeName').value.trim(),
    annual_entitlement: parseFloat(document.getElementById('leaveTypeEntitlement').value)||0,
    requires_approval: document.getElementById('leaveTypeRequiresApproval').checked,
    requires_attachment: document.getElementById('leaveTypeRequiresAttachment').checked,
    is_paid: document.getElementById('leaveTypeIsPaid').checked,
    shares_entitlement_with_id: sharesWith?parseInt(sharesWith):null,
    count_calendar_days: document.getElementById('leaveTypeCountMode').value==='calendar',
    accrual_mode: document.getElementById('leaveTypeAccrualMode').value,
    max_days_per_application: parseFloat(document.getElementById('leaveTypeMaxPerApp').value)||0,
    max_days_per_month: parseFloat(document.getElementById('leaveTypeMaxPerMonth').value)||0,
    carry_forward_enabled: document.getElementById('leaveTypeCarryForwardEnabled').checked,
    carry_forward_max_days: parseFloat(document.getElementById('leaveTypeCarryMaxDays').value)||0,
    carry_forward_max_percent: parseFloat(document.getElementById('leaveTypeCarryMaxPercent').value)||0,
    carry_forward_expiry_days: parseInt(document.getElementById('leaveTypeCarryExpiryDays').value)||0,
  };
  const url=id?`/api/leave/types/${id}`:'/api/leave/types';
  const res=await api(url,{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res?.ok){ closeLeaveTypeModal(); loadLeaveTypesForManage(); }
  else if(res){ const d=await res.json().catch(()=>({})); alert(d.detail||'Failed to save leave type'); }
}

async function deleteLeaveType(id) {
  if(!confirm('Remove this leave type?')) return;
  await api(`/api/leave/types/${id}`,{method:'DELETE'});
  loadLeaveTypesForManage();
}

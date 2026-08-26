// Recruitment — helpers
// ---------------------------------------------------------------------------
let recruitMeta = {};
let recruitCandidates = []; // cached for selects
let viewingReqId = null, viewingCandId = null, viewingIntId = null, viewingOfferId = null;
let viewingCandData = null; // full candidate object currently open in detail modal
let candExistingDocs = [];  // documents already saved for the candidate being edited
let candPendingFiles = [];  // {file_name,mime_type,data_url} selected but not yet uploaded
const CAND_FILE_MAX_BYTES = 6 * 1024 * 1024;
let candSortBy = 'created_at', candSortDir = 'desc';
const CAND_SORT_FIELDS = ['full_name','requisition_title','source','created_at','experience_years','last_interview_date','stage'];

function stageBadgeClass(stage) {
  const m = {New:'bg-slate-100 text-slate-600',Screening:'bg-blue-100 text-blue-700',
    Interview:'bg-purple-100 text-purple-700','Pending Checks':'bg-orange-100 text-orange-700',
    Offer:'bg-yellow-100 text-yellow-700',
    Hired:'bg-green-100 text-green-700','Rejected by Candidate':'bg-red-100 text-red-600',
    'Rejected by Company':'bg-red-100 text-red-600',
    Withdrawn:'bg-slate-100 text-slate-500'};
  return m[stage]||'bg-slate-100 text-slate-600';
}
function reqStatusBadge(s) {
  const m = {Draft:'bg-slate-100 text-slate-600','Pending Approval':'bg-yellow-100 text-yellow-700',
    Approved:'bg-green-100 text-green-700',Rejected:'bg-red-100 text-red-600',
    Closed:'bg-slate-200 text-slate-500',Filled:'bg-blue-100 text-blue-700'};
  return m[s]||'bg-slate-100 text-slate-600';
}
function offerStatusBadge(s) {
  const m = {Draft:'bg-slate-100 text-slate-600',Sent:'bg-blue-100 text-blue-700',
    Accepted:'bg-green-100 text-green-700',Rejected:'bg-red-100 text-red-600',
    Withdrawn:'bg-slate-200 text-slate-500'};
  return m[s]||'bg-slate-100 text-slate-600';
}
function priorityBadge(p) {
  const m = {Low:'bg-slate-100 text-slate-500',Normal:'bg-blue-50 text-blue-600',
    High:'bg-orange-100 text-orange-700',Urgent:'bg-red-100 text-red-700'};
  return m[p]||'bg-slate-100 text-slate-500';
}
async function loadRecruitMeta() {
  if(recruitMeta.stages) return;
  const res=await api('/api/recruitment/meta');
  if(res&&res.ok) recruitMeta=await res.json();
}

// ---------------------------------------------------------------------------
// Recruitment — Job Requisitions
// ---------------------------------------------------------------------------
async function loadRequisitions() {
  await loadRecruitMeta();
  const status=document.getElementById('reqStatusFilter')?.value||'';
  const res=await api('/api/recruitment/requisitions'+(status?`?status=${encodeURIComponent(status)}`:''));
  if(!res||!res.ok) return;
  const rows=await res.json();
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  document.getElementById('addReqBtn')?.classList.toggle('hidden',!canManage);
  const body=document.getElementById('reqTableBody');
  const empty=document.getElementById('reqEmpty');
  if(!rows.length){body.innerHTML='';empty?.classList.remove('hidden');return;}
  empty?.classList.add('hidden');
  body.innerHTML=rows.map(r=>`
    <tr class="hover:bg-slate-50 cursor-pointer" onclick="openReqDetail(${r.id})">
      <td class="px-4 py-3 font-medium text-slate-800">${esc(r.title)}</td>
      <td class="px-4 py-3 text-slate-600 hidden md:table-cell">${esc(r.department)}</td>
      <td class="px-4 py-3 hidden lg:table-cell"><span class="badge ${priorityBadge(r.priority)}">${esc(r.priority)}</span></td>
      <td class="px-4 py-3 text-center text-slate-700 hidden sm:table-cell">${r.headcount}</td>
      <td class="px-4 py-3 text-center text-slate-700 hidden sm:table-cell">${r.candidate_count||0}</td>
      <td class="px-4 py-3 text-center text-slate-700">${r.shortlisted_count||0}</td>
      <td class="px-4 py-3 text-center text-slate-700">${r.interviewed_count||0}</td>
      <td class="px-4 py-3 text-center text-slate-700">${r.offer_count||0}</td>
      <td class="px-4 py-3"><span class="badge ${reqStatusBadge(r.status)}">${esc(r.status)}</span></td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        ${r.status==='Approved'?`<button class="btn-ghost text-xs" onclick="event.stopPropagation();openCandModal(null,${r.id})">Add Candidate</button>`:''}
        <button class="btn-ghost text-xs" onclick="event.stopPropagation();openReqDetail(${r.id})">View</button>
      </td>
    </tr>`).join('');
}

function openReqModal(reqData=null) {
  const r=typeof reqData==='string'?JSON.parse(reqData):reqData;
  document.getElementById('reqModalTitle').textContent=r?'Edit Requisition':'New Job Requisition';
  document.getElementById('reqId').value=r?.id||'';
  document.getElementById('reqTitle').value=r?.title||'';
  document.getElementById('reqDept').value=r?.department||'';
  document.getElementById('reqHeadcount').value=r?.headcount||1;
  const et=document.getElementById('reqEmpType');
  et.innerHTML=(recruitMeta.employment_types||['Permanent','Contract','Internship','Part-Time']).map(t=>`<option${r?.employment_type===t?' selected':''}>${esc(t)}</option>`).join('');
  document.getElementById('reqPriority').value=r?.priority||'Normal';
  document.getElementById('reqSalMin').value=r?.salary_min||'';
  document.getElementById('reqSalMax').value=r?.salary_max||'';
  document.getElementById('reqDescription').value=r?.description||'';
  document.getElementById('reqRequirements').value=r?.requirements||'';
  document.getElementById('reqFormErr').classList.add('hidden');
  document.getElementById('reqModal').classList.remove('hidden');
}
function closeReqModal(){closeModal('reqModal');}

async function submitReqForm(e) {
  e.preventDefault();
  const err=document.getElementById('reqFormErr');
  err.classList.add('hidden');
  const id=document.getElementById('reqId').value;
  const body={
    title:document.getElementById('reqTitle').value.trim(),
    department:document.getElementById('reqDept').value.trim(),
    headcount:parseInt(document.getElementById('reqHeadcount').value)||1,
    employment_type:document.getElementById('reqEmpType').value,
    priority:document.getElementById('reqPriority').value,
    salary_min:parseFloat(document.getElementById('reqSalMin').value)||null,
    salary_max:parseFloat(document.getElementById('reqSalMax').value)||null,
    description:document.getElementById('reqDescription').value||null,
    requirements:document.getElementById('reqRequirements').value||null,
  };
  const res=await api(id?`/api/recruitment/requisitions/${id}`:`/api/recruitment/requisitions`,
    {method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();err.textContent=d?.detail||'Failed';err.classList.remove('hidden');return;}
  closeReqModal(); loadRequisitions();
}

async function openReqDetail(reqId) {
  viewingReqId=reqId;
  const res=await api(`/api/recruitment/requisitions/${reqId}`);
  if(!res||!res.ok) return;
  const r=await res.json();
  document.getElementById('rdTitle').textContent=r.title;
  document.getElementById('rdMeta').textContent=`${r.department} · ${r.employment_type} · HC: ${r.headcount} · By ${r.created_by}`;
  const badge=document.getElementById('rdBadge');
  badge.textContent=r.status; badge.className=`badge ${reqStatusBadge(r.status)}`;
  const sal=r.salary_min||r.salary_max?`${fmtCurrency(r.salary_min||0)} – ${fmtCurrency(r.salary_max||0)}`:'Not specified';
  document.getElementById('rdBody').innerHTML=`
    <div class="grid grid-cols-2 gap-4">
      <div><p class="text-xs text-slate-400 mb-1">Priority</p><span class="badge ${priorityBadge(r.priority)}">${esc(r.priority)}</span></div>
      <div><p class="text-xs text-slate-400 mb-1">Salary Range</p><p class="font-medium">${sal}</p></div>
      ${r.description?`<div class="col-span-2"><p class="text-xs text-slate-400 mb-1">Job Description</p><p class="whitespace-pre-wrap">${esc(r.description)}</p></div>`:''}
      ${r.requirements?`<div class="col-span-2"><p class="text-xs text-slate-400 mb-1">Requirements</p><p class="whitespace-pre-wrap">${esc(r.requirements)}</p></div>`:''}
      ${r.approved_by?`<div class="col-span-2"><p class="text-xs text-slate-400 mb-1">Approved By</p><p>${esc(r.approved_by)} ${r.approval_comments?'— '+esc(r.approval_comments):''}</p></div>`:''}
      <div class="col-span-2"><p class="text-xs text-slate-400 mb-1">Candidates (${(r.candidates||[]).length})</p>
        ${(r.candidates||[]).map(c=>`<div class="flex items-center gap-2 py-1 border-b border-slate-100"><span class="flex-1">${esc(c.full_name)}</span><span class="badge ${stageBadgeClass(c.stage)}">${esc(c.stage)}</span><button onclick="closeBothReq();openCandDetail(${c.id})" class="text-xs text-blue-600 hover:underline">View</button></div>`).join('')||'<p class="text-slate-400">No candidates yet.</p>'}
      </div>
    </div>`;
  const canApprove=HR_MANAGER_ONLY_ROLES.includes(currentUser?.role);
  const appSection=document.getElementById('rdApprovalSection');
  appSection.classList.toggle('hidden',!(r.status==='Pending Approval'&&canApprove));
  document.getElementById('rdEditBtn').classList.toggle('hidden',r.status!=='Draft');
  document.getElementById('rdSubmitBtn').classList.toggle('hidden',r.status!=='Draft');
  document.getElementById('rdCloseBtn').classList.toggle('hidden',!['Approved'].includes(r.status));
  document.getElementById('reqDetailModal').classList.remove('hidden');
}
function closeReqDetailModal(){closeModal('reqDetailModal', () => viewingReqId=null);}
function closeBothReq(){closeReqDetailModal();}
async function editReqFromDetail(){
  if(!viewingReqId) return;
  const res=await api(`/api/recruitment/requisitions/${viewingReqId}`);
  if(!res||!res.ok) return;
  const r=await res.json();
  closeReqDetailModal();
  openReqModal(r);
}

const submitReqForApproval = guardAsync(async function() {
  if(!viewingReqId) return;
  const res=await api(`/api/recruitment/requisitions/${viewingReqId}/submit`,{method:'PATCH',body:JSON.stringify({})});
  if(!res||!res.ok) return;
  closeReqDetailModal(); loadRequisitions();
});
async function approveReq(action) {
  if(!viewingReqId) return;
  const comments=document.getElementById('rdComments').value;
  const res=await api(`/api/recruitment/requisitions/${viewingReqId}/approve`,
    {method:'PATCH',body:JSON.stringify({action,comments})});
  if(!res||!res.ok) return;
  closeReqDetailModal(); loadRequisitions();
}
async function closeReqAction() {
  if(!viewingReqId||!confirm('Close this requisition?')) return;
  const res=await api(`/api/recruitment/requisitions/${viewingReqId}/close`,{method:'PATCH',body:JSON.stringify({})});
  if(!res||!res.ok) return;
  closeReqDetailModal(); loadRequisitions();
}

// ---------------------------------------------------------------------------
// Recruitment — Candidates
// ---------------------------------------------------------------------------
function toggleAllCandStages(checked) {
  document.querySelectorAll('.cand-stage-cb').forEach(cb=>cb.checked=checked);
  loadCandidates();
}
function onCandStageCbChange() {
  const boxes=[...document.querySelectorAll('.cand-stage-cb')];
  document.getElementById('candStageAll').checked = boxes.every(cb=>cb.checked);
  loadCandidates();
}
function setCandSort(field) {
  if (candSortBy === field) { candSortDir = candSortDir==='asc' ? 'desc' : 'asc'; }
  else { candSortBy = field; candSortDir = 'asc'; }
  loadCandidates();
}
function updateCandSortIcons() {
  CAND_SORT_FIELDS.forEach(f=>{
    const el=document.getElementById('sortIcon-'+f);
    if(!el) return;
    el.textContent = f===candSortBy ? (candSortDir==='asc'?'▲':'▼') : '';
  });
}
function fmtDateOnly(s) { return fmtDate(s); }

async function loadCandidates() {
  await loadRecruitMeta();
  const q=document.getElementById('candSearch')?.value||'';
  const stages=[...document.querySelectorAll('.cand-stage-cb:checked')].map(cb=>cb.value);
  const allStages=[...document.querySelectorAll('.cand-stage-cb')].map(cb=>cb.value);
  let url='/api/recruitment/candidates?x=1';
  if(q) url+=`&search=${encodeURIComponent(q)}`;
  if(stages.length < allStages.length) {
    if(!stages.length) url+=`&stage=__none__`; // empty selection: force zero results
    else stages.forEach(s=>{ url+=`&stage=${encodeURIComponent(s)}`; });
  }
  url+=`&sort_by=${candSortBy}&sort_dir=${candSortDir}`;
  updateCandSortIcons();
  const res=await api(url);
  if(!res||!res.ok) return;
  const rows=await res.json();
  recruitCandidates=rows;
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  document.getElementById('addCandBtn')?.classList.toggle('hidden',!canManage);
  const body=document.getElementById('candTableBody');
  const empty=document.getElementById('candEmpty');
  if(!rows.length){body.innerHTML='';empty?.classList.remove('hidden');return;}
  empty?.classList.add('hidden');
  body.innerHTML=rows.map(c=>`
    <tr class="hover:bg-slate-50 cursor-pointer" onclick="openCandDetail(${c.id})">
      <td class="px-4 py-3">
        <p class="font-medium text-slate-800">${esc(c.full_name)}</p>
        <p class="text-xs text-slate-400">${esc(c.email||'')} ${c.phone?'· '+esc(c.phone):''}</p>
      </td>
      <td class="px-4 py-3 text-slate-600 hidden md:table-cell">${esc(c.requisition_title||'—')}</td>
      <td class="px-4 py-3 hidden lg:table-cell text-slate-500 text-xs">${esc(c.source||'')}</td>
      <td class="px-4 py-3 text-slate-500 text-xs">${fmtDateOnly(c.created_at)}</td>
      <td class="px-4 py-3 text-center text-slate-700">${c.experience_years||0}</td>
      <td class="px-4 py-3 text-slate-500 text-xs">${fmtDateOnly(c.last_interview_date)}</td>
      <td class="px-4 py-3"><span class="badge ${stageBadgeClass(c.stage)}">${esc(c.stage)}</span></td>
      <td class="px-4 py-3 text-right"><button class="btn-ghost text-xs" onclick="event.stopPropagation();openCandDetail(${c.id})">View</button></td>
    </tr>`).join('');
}

function switchCandFormTab(tab) {
  ['cm-personal','cm-employment','cm-education','cm-others'].forEach(t=>{
    document.getElementById(t)?.classList.toggle('hidden', t!==tab);
  });
  document.querySelectorAll('.cand-form-tab').forEach(b=>{
    const active=b.dataset.cmtab===tab;
    b.classList.toggle('view-tab-active',active);
    b.classList.toggle('border-blue-600',active);
    b.classList.toggle('text-blue-600',active);
    b.classList.toggle('text-slate-500',!active);
    b.classList.toggle('border-transparent',!active);
  });
}

function openCandModal(candData=null, presetReqId=null) {
  const c=typeof candData==='string'?JSON.parse(candData):candData;
  document.getElementById('candModalTitle').textContent=c?.id?'Edit Candidate':'Add Candidate';
  document.getElementById('candId').value=c?.id||'';
  // Personal Info
  document.getElementById('candFullName').value=c?.full_name||'';
  document.getElementById('candEmail').value=c?.email||'';
  document.getElementById('candPhone').value=c?.phone||'';
  document.getElementById('candIc').value=c?.ic_number||'';
  document.getElementById('candNationality').value=c?.nationality||'Malaysian';
  document.getElementById('candGender').value=c?.gender||'';
  document.getElementById('candDob').value=c?.date_of_birth||'';
  document.getElementById('candAddress').value=c?.address||'';
  // Employment
  document.getElementById('candPosition').value=c?.current_position||'';
  document.getElementById('candCompany').value=c?.current_company||'';
  document.getElementById('candExp').value=c?.experience_years||0;
  document.getElementById('candSkills').value=c?.skills||'';
  document.getElementById('candEmpHistory').value=c?.employment_history||'';
  const ss=document.getElementById('candSource');
  ss.innerHTML=(recruitMeta.sources||['Direct','JobStreet','LinkedIn','Referral','Agency','Other']).map(s=>`<option${c?.source===s?' selected':''}>${esc(s)}</option>`).join('');
  const rsel=document.getElementById('candReqId');
  rsel.innerHTML='<option value="">General / No specific requisition</option>';
  api('/api/recruitment/requisitions?status=Approved').then(async r=>{
    if(!r||!r.ok) return;
    const reqs=await r.json();
    const selectedReqId=c?.requisition_id||presetReqId;
    reqs.forEach(req=>{const o=document.createElement('option');o.value=req.id;o.textContent=`${esc(req.title)} (${esc(req.department)})`;if(selectedReqId===req.id)o.selected=true;rsel.appendChild(o);});
  });
  // Education
  const qs=document.getElementById('candQual');
  qs.innerHTML='<option value="">Select</option>'+(recruitMeta.qualifications||[]).map(q=>`<option${c?.highest_qualification===q?' selected':''}>${esc(q)}</option>`).join('');
  document.getElementById('candField').value=c?.field_of_study||'';
  document.getElementById('candInstitution').value=c?.institution_name||'';
  document.getElementById('candGradYear').value=c?.graduation_year||'';
  document.getElementById('candCerts').value=c?.certifications||'';
  document.getElementById('candResume').value=c?.resume_text||'';
  // Others
  document.getElementById('candExpSalary').value=c?.expected_salary||'';
  document.getElementById('candNotice').value=c?.notice_period||'';
  document.getElementById('candLinkedin').value=c?.linkedin_url||'';
  document.getElementById('candReferral').value=c?.referral_by||'';
  document.getElementById('candNotes').value=c?.notes||'';
  document.getElementById('candFormErr').classList.add('hidden');
  candExistingDocs=c?.documents||[];
  candPendingFiles=[];
  document.getElementById('candFilesInput').value='';
  renderCandFileList();
  switchCandFormTab('cm-personal');
  document.getElementById('candModal').classList.remove('hidden');
}
function closeCandModal(){closeModal('candModal');}

function renderCandFileList() {
  const el=document.getElementById('candFileList');
  const existingHtml=candExistingDocs.map(d=>`
    <div class="flex items-center justify-between text-sm bg-slate-50 rounded-lg px-3 py-1.5">
      <a href="${d.data_url}" download="${esc(d.file_name)}" target="_blank" class="text-blue-600 hover:underline truncate flex-1">${esc(d.file_name)}</a>
      <button type="button" onclick="removeCandExistingDoc(${d.id})" class="text-slate-400 hover:text-red-600 ml-2">✕</button>
    </div>`).join('');
  const pendingHtml=candPendingFiles.map((f,i)=>`
    <div class="flex items-center justify-between text-sm bg-blue-50 rounded-lg px-3 py-1.5">
      <span class="text-slate-700 truncate flex-1">${esc(f.file_name)} <span class="text-xs text-blue-500">(pending)</span></span>
      <button type="button" onclick="removeCandPendingFile(${i})" class="text-slate-400 hover:text-red-600 ml-2">✕</button>
    </div>`).join('');
  el.innerHTML=existingHtml+pendingHtml;
}

function handleCandFilesSelected(e) {
  const files=[...(e.target.files||[])];
  e.target.value='';
  for (const file of files) {
    if (file.size > CAND_FILE_MAX_BYTES) {
      alert(`"${file.name}" is too large. Please choose a file under ~6MB.`);
      continue;
    }
    const reader=new FileReader();
    reader.onload=() => {
      candPendingFiles.push({file_name:file.name, mime_type:file.type||'application/octet-stream', data_url:reader.result});
      renderCandFileList();
    };
    reader.readAsDataURL(file);
  }
}

function removeCandPendingFile(idx) {
  candPendingFiles.splice(idx,1);
  renderCandFileList();
}

async function removeCandExistingDoc(docId) {
  const id=document.getElementById('candId').value;
  if(!id) return;
  const res=await api(`/api/recruitment/candidates/${id}/documents/${docId}`, {method:'DELETE'});
  if(!res||!res.ok) return;
  candExistingDocs=candExistingDocs.filter(d=>d.id!==docId);
  renderCandFileList();
}

async function submitCandForm(e) {
  e.preventDefault();
  const err=document.getElementById('candFormErr');
  err.classList.add('hidden');
  const id=document.getElementById('candId').value;
  const body={
    full_name:document.getElementById('candFullName').value.trim(),
    email:document.getElementById('candEmail').value||null,
    phone:document.getElementById('candPhone').value||null,
    ic_number:document.getElementById('candIc').value||null,
    nationality:document.getElementById('candNationality').value||'Malaysian',
    gender:document.getElementById('candGender').value||null,
    date_of_birth:document.getElementById('candDob').value||null,
    address:document.getElementById('candAddress').value||null,
    current_position:document.getElementById('candPosition').value||null,
    current_company:document.getElementById('candCompany').value||null,
    experience_years:parseInt(document.getElementById('candExp').value)||0,
    skills:document.getElementById('candSkills').value||null,
    employment_history:document.getElementById('candEmpHistory').value||null,
    source:document.getElementById('candSource').value||'Direct',
    requisition_id:parseInt(document.getElementById('candReqId').value)||null,
    highest_qualification:document.getElementById('candQual').value||null,
    field_of_study:document.getElementById('candField').value||null,
    institution_name:document.getElementById('candInstitution').value||null,
    graduation_year:parseInt(document.getElementById('candGradYear').value)||null,
    certifications:document.getElementById('candCerts').value||null,
    resume_text:document.getElementById('candResume').value||null,
    expected_salary:parseFloat(document.getElementById('candExpSalary').value)||null,
    notice_period:document.getElementById('candNotice').value||null,
    linkedin_url:document.getElementById('candLinkedin').value||null,
    referral_by:document.getElementById('candReferral').value||null,
    notes:document.getElementById('candNotes').value||null,
  };
  const res=await api(id?`/api/recruitment/candidates/${id}`:`/api/recruitment/candidates`,
    {method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();err.textContent=d?.detail||'Failed';err.classList.remove('hidden');return;}
  const saved=await res.json();
  if(candPendingFiles.length){
    const docRes=await api(`/api/recruitment/candidates/${saved.id}/documents`,
      {method:'POST',body:JSON.stringify(candPendingFiles.map(({file_name,mime_type,data_url})=>({file_name,mime_type,data_url})))});
    if(!docRes||!docRes.ok){const d=await docRes?.json();err.textContent=d?.detail||'Candidate saved, but file upload failed';err.classList.remove('hidden');return;}
  }
  candPendingFiles=[];
  closeCandModal(); loadCandidates();
}

async function openCandDetail(candId) {
  viewingCandId=candId;
  viewingCandData=null;
  const res=await api(`/api/recruitment/candidates/${candId}`);
  if(!res||!res.ok) return;
  const c=await res.json();
  viewingCandData=c;
  document.getElementById('cdName').textContent=c.full_name;
  document.getElementById('cdMeta').textContent=`${c.email||''}${c.phone?' · '+c.phone:''} · ${c.source||''}`;
  const badge=document.getElementById('cdStageBadge');
  badge.textContent=c.stage; badge.className=`badge ${stageBadgeClass(c.stage)}`;
  // Profile tab
  document.getElementById('cdt-profile').innerHTML=`
    <div class="grid grid-cols-2 gap-4 text-sm">
      <div><p class="text-xs text-slate-400 mb-1">IC Number</p><p>${esc(c.ic_number||'—')}</p></div>
      <div><p class="text-xs text-slate-400 mb-1">Nationality</p><p>${esc(c.nationality||'—')}</p></div>
      <div><p class="text-xs text-slate-400 mb-1">Current Position</p><p>${esc(c.current_position||'—')}</p></div>
      <div><p class="text-xs text-slate-400 mb-1">Current Company</p><p>${esc(c.current_company||'—')}</p></div>
      <div><p class="text-xs text-slate-400 mb-1">Experience</p><p>${c.experience_years||0} years</p></div>
      <div><p class="text-xs text-slate-400 mb-1">Qualification</p><p>${esc(c.highest_qualification||'—')}</p></div>
      <div class="col-span-2"><p class="text-xs text-slate-400 mb-1">Skills</p><p>${esc(c.skills||'—')}</p></div>
      ${c.requisition?`<div class="col-span-2"><p class="text-xs text-slate-400 mb-1">Applying For</p><p class="font-medium">${esc(c.requisition.title)} — ${esc(c.requisition.department)}</p></div>`:''}
      ${c.notes?`<div class="col-span-2"><p class="text-xs text-slate-400 mb-1">Notes</p><p class="whitespace-pre-wrap text-slate-600">${esc(c.notes)}</p></div>`:''}
    </div>`;
  // Interviews tab
  const intHtml=(c.interviews||[]).map(i=>`
    <div class="border border-slate-200 rounded-xl p-4 mb-3">
      <div class="flex items-center justify-between mb-2">
        <div><p class="font-medium text-sm">${esc(i.interview_type)} Interview</p><p class="text-xs text-slate-500">${fmtDate(i.scheduled_date)} at ${esc(i.scheduled_time)} · ${i.duration_mins}min</p></div>
        <span class="badge ${i.status==='Completed'?'bg-green-100 text-green-700':i.status==='Cancelled'?'bg-red-100 text-red-600':'bg-blue-100 text-blue-700'}">${esc(i.status)}</span>
      </div>
      ${i.interviewers?`<p class="text-xs text-slate-500 mb-2">Interviewers: ${esc(i.interviewers)}</p>`:''}
      <div class="flex gap-2 mb-3">
        ${i.status==='Scheduled'?`<button onclick="markIntStatus(${i.id},'Completed')" class="btn-primary text-xs" style="font-size:.75rem;padding:.2rem .6rem">Mark Completed</button>`:''}
        <button onclick="openScoreModal(${i.id},'${esc(fmtDate(i.scheduled_date))} ${esc(i.interview_type)}')" class="btn-ghost text-xs" style="font-size:.75rem;padding:.2rem .6rem">Score</button>
      </div>
      ${(i.scores&&i.scores.length)?`
        <div class="border-t border-slate-100 pt-2">
          <p class="text-xs font-medium text-slate-500 mb-1">Scorecard (${i.scores.length} scorer${i.scores.length>1?'s':''}${i.avg_score!=null?' · Avg '+parseFloat(i.avg_score).toFixed(1)+'/5':''})</p>
          <table class="w-full text-xs text-slate-600">
            <thead><tr class="text-slate-400"><th class="text-left pb-1 font-normal">Scorer</th><th class="pb-1 font-normal">Tech</th><th class="pb-1 font-normal">Comm</th><th class="pb-1 font-normal">Attitude</th><th class="pb-1 font-normal">Culture</th><th class="pb-1 font-normal">Overall</th><th class="text-left pb-1 font-normal">Rec</th></tr></thead>
            <tbody>${i.scores.map(s=>`<tr class="border-t border-slate-100">
              <td class="py-1 pr-2 font-medium">${esc(s.scored_by)}</td>
              <td class="text-center py-1">${s.technical_score??'—'}</td>
              <td class="text-center py-1">${s.communication_score??'—'}</td>
              <td class="text-center py-1">${s.attitude_score??'—'}</td>
              <td class="text-center py-1">${s.culture_fit_score??'—'}</td>
              <td class="text-center py-1 font-semibold">${s.overall_score??'—'}</td>
              <td class="py-1 pl-2">${esc(s.recommendation||'—')}</td>
            </tr>${s.comments?`<tr><td colspan="7" class="pb-1 text-slate-400 italic">${esc(s.comments)}</td></tr>`:''}`).join('')}</tbody>
          </table>
        </div>`:''}
    </div>`).join('')||'<p class="text-slate-400 text-sm">No interviews scheduled yet.</p>';
  document.getElementById('cdt-interviews').innerHTML=intHtml;
  // Resume tab
  const docsHtml=(c.documents||[]).map(d=>`
    <div class="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 mb-2">
      <a href="${d.data_url}" download="${esc(d.file_name)}" target="_blank" class="text-sm text-blue-600 hover:underline truncate flex-1">${esc(d.file_name)}</a>
      <span class="text-xs text-slate-400 ml-2">${fmtDate(d.created_at)}</span>
    </div>`).join('');
  document.getElementById('cdt-resume').innerHTML=`
    ${docsHtml||'<p class="text-slate-400 text-sm mb-3">No files uploaded.</p>'}
    ${c.resume_text?`<pre class="text-xs whitespace-pre-wrap text-slate-700 mt-3">${esc(c.resume_text)}</pre>`:''}`;
  // Stage select
  const ss=document.getElementById('cdStageSelect');
  ss.innerHTML=(recruitMeta.stages||[]).map(s=>`<option${s===c.stage?' selected':''}>${esc(s)}</option>`).join('');
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  document.getElementById('cdScheduleBtn').classList.toggle('hidden',!canManage);
  document.getElementById('cdOfferBtn').classList.toggle('hidden',!canManage);
  const showConvert=canManage&&['Offer','Hired'].includes(c.stage)&&(c.offers||[]).some(o=>o.status==='Accepted'&&o.offer_type==='Offer');
  document.getElementById('cdConvertBtn').classList.toggle('hidden',!showConvert);
  // History tab visible to HR roles only
  const canViewHistory=HR_MANAGE_ROLES.includes(currentUser?.role);
  document.getElementById('cdHistoryTab').classList.toggle('hidden',!canViewHistory);
  // Time in Stage tab visible to HR roles + manager (matches the
  // Recruitment dashboard tab's own canRecruit visibility, dashboard.js)
  const canViewStageTime=HR_AND_MANAGER_ROLES.includes(currentUser?.role);
  document.getElementById('cdStageTimeTab').classList.toggle('hidden',!canViewStageTime);
  switchCandTab('cdt-profile');
  document.getElementById('candDetailModal').classList.remove('hidden');
}
function closeCandDetailModal(){closeModal('candDetailModal', () => viewingCandId=null);}
async function loadCandHistory() {
  if(!viewingCandId) return;
  const el=document.getElementById('cdt-history');
  el.innerHTML='<p class="text-slate-400 text-sm">Loading…</p>';
  const res=await api(`/api/recruitment/candidates/${viewingCandId}/audit-log`);
  if(!res||!res.ok){el.innerHTML='<p class="text-red-500 text-sm">Failed to load history.</p>';return;}
  const rows=await res.json();
  if(!rows.length){el.innerHTML='<p class="text-slate-400 text-sm">No history recorded yet.</p>';return;}
  const actionIcon={
    'Created':'🟢','Updated':'✏️','Stage Changed':'🔀',
    'Interview Scheduled':'📅','Offer Letter Generated':'📄',
    'Decline Letter Generated':'📄','Offer Status Updated':'📬',
  };
  el.innerHTML=`<div class="relative pl-6 border-l-2 border-slate-200 space-y-5">
    ${rows.map(r=>`
      <div class="relative">
        <span class="absolute -left-[1.65rem] top-0.5 text-base">${actionIcon[r.action]||'•'}</span>
        <p class="text-sm font-medium text-slate-800">${esc(r.action)}</p>
        ${r.detail?`<p class="text-xs text-slate-500 mt-0.5">${esc(r.detail)}</p>`:''}
        <p class="text-xs text-slate-400 mt-1">${esc(r.performed_by)} · ${fmtDateTime(r.created_at)}</p>
      </div>`).join('')}
  </div>`;
}

async function loadCandStageTime() {
  if(!viewingCandId) return;
  const el=document.getElementById('cdt-stagetime');
  el.innerHTML='<p class="text-slate-400 text-sm">Loading…</p>';
  const res=await api(`/api/recruitment/candidates/${viewingCandId}/stage-history`);
  if(!res||!res.ok){el.innerHTML='<p class="text-red-500 text-sm">Failed to load stage history.</p>';return;}
  const rows=await res.json();
  if(!rows.length){el.innerHTML='<p class="text-slate-400 text-sm">No stage history recorded yet.</p>';return;}
  el.innerHTML=`<div class="space-y-3">
    ${rows.map(r=>`
      <div class="flex items-center justify-between border border-slate-200 rounded-xl px-4 py-3">
        <div>
          <span class="badge text-xs ${stageBadgeClass(r.stage)}">${esc(r.stage)}</span>
          <p class="text-xs text-slate-500 mt-1">${fmtDateTime(r.entered_at)} → ${r.exited_at?fmtDateTime(r.exited_at):'Current'}</p>
        </div>
        <p class="text-sm font-medium text-slate-700">${fmtDuration(r.duration_seconds)}</p>
      </div>`).join('')}
  </div>`;
}

function switchCandTab(tab){
  ['cdt-profile','cdt-interviews','cdt-resume','cdt-stagetime','cdt-history'].forEach(t=>{
    document.getElementById(t).classList.toggle('hidden',t!==tab);
  });
  document.querySelectorAll('[data-cdtab]').forEach(b=>{
    b.classList.toggle('view-tab-active',b.dataset.cdtab===tab);
    b.classList.toggle('text-slate-500',b.dataset.cdtab!==tab);
  });
  if(tab==='cdt-history') loadCandHistory();
  if(tab==='cdt-stagetime') loadCandStageTime();
}
async function moveCandStage() {
  if(!viewingCandId) return;
  const stage=document.getElementById('cdStageSelect').value;
  const res=await api(`/api/recruitment/candidates/${viewingCandId}/stage`,
    {method:'PATCH',body:JSON.stringify({stage})});
  if(!res||!res.ok) return;
  const badge=document.getElementById('cdStageBadge');
  badge.textContent=stage; badge.className=`badge ${stageBadgeClass(stage)}`;
  loadCandidates();
}
function editCand() {
  const c=viewingCandData||recruitCandidates.find(x=>x.id===viewingCandId)||{id:viewingCandId};
  closeCandDetailModal();
  openCandModal(c);
}
async function convertToEmployee() {
  if(!viewingCandId) return;
  const res=await api(`/api/recruitment/candidates/${viewingCandId}/convert-prefill`);
  if(!res||!res.ok) return;
  const pf=await res.json();
  closeCandDetailModal();
  // Pre-fill the add employee form
  document.getElementById('fFullName').value=pf.full_name||'';
  document.getElementById('fIcNumber').value=pf.ic_number||'';
  document.getElementById('fNationality').value=pf.nationality||'Malaysian';
  document.getElementById('fPersonalEmail').value=pf.personal_email||'';
  document.getElementById('fPhone').value=pf.phone||'';
  document.getElementById('fDepartment').value=pf.department||'';
  document.getElementById('fDesignation').value=pf.designation||'';
  document.getElementById('fEmploymentType').value=pf.employment_type||'Permanent';
  document.getElementById('fBasicSalary').value=pf.basic_salary||0;
  document.getElementById('fStartDate').value=pf.start_date||'';
  // Update offer/convert on hired
  api(`/api/recruitment/candidates/${viewingCandId}/stage`,{method:'PATCH',body:JSON.stringify({stage:'Hired',notes:'Converted to employee'})});
  currentEmpId=null; currentTab='personal'; switchTab('personal');
  document.getElementById('empModalTitle').textContent='New Employee (from candidate)';
  document.getElementById('empModal').classList.remove('hidden');
  showPage('employees');
}

// ---------------------------------------------------------------------------
// Recruitment — Interviews
// ---------------------------------------------------------------------------
async function loadInterviews() {
  await loadRecruitMeta();
  const status=document.getElementById('intStatusFilter')?.value||'';
  const res=await api('/api/recruitment/interviews'+(status?`?status=${encodeURIComponent(status)}`:''));
  if(!res||!res.ok) return;
  const rows=await res.json();
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  document.getElementById('addIntBtn')?.classList.toggle('hidden',!canManage);
  const body=document.getElementById('intTableBody');
  const empty=document.getElementById('intEmpty');
  if(!rows.length){body.innerHTML='';empty?.classList.remove('hidden');return;}
  empty?.classList.add('hidden');
  body.innerHTML=rows.map(i=>`
    <tr class="hover:bg-slate-50">
      <td class="px-4 py-3">
        <p class="font-medium text-slate-800">${esc(i.candidate_name)}</p>
        <p class="text-xs text-slate-400">${esc(i.requisition_title||'—')}</p>
      </td>
      <td class="px-4 py-3 text-slate-600 hidden md:table-cell">${esc(i.interview_type)}</td>
      <td class="px-4 py-3 text-slate-700">${fmtDate(i.scheduled_date)} ${esc(i.scheduled_time)}</td>
      <td class="px-4 py-3 text-slate-500 text-xs hidden lg:table-cell">${esc(i.interviewers||'—')}</td>
      <td class="px-4 py-3 text-center text-slate-700 hidden sm:table-cell">${i.avg_score!=null?parseFloat(i.avg_score).toFixed(1)+'/5':'—'}</td>
      <td class="px-4 py-3"><span class="badge ${i.status==='Completed'?'bg-green-100 text-green-700':i.status==='Cancelled'?'bg-red-100 text-red-600':i.status==='No-Show'?'bg-slate-200 text-slate-500':'bg-blue-100 text-blue-700'}">${esc(i.status)}</span></td>
      <td class="px-4 py-3 text-right flex gap-1 justify-end">
        ${i.status==='Scheduled'?`<button class="btn-ghost text-xs" onclick="markIntStatus(${i.id},'Completed')">Done</button>`:''}
        <button class="btn-ghost text-xs" onclick="openScoreModal(${i.id},'${esc(fmtDate(i.scheduled_date))} — ${esc(i.interview_type)}')">Score</button>
      </td>
    </tr>`).join('');
}

async function openIntModal(candId=null) {
  await loadRecruitMeta();
  document.getElementById('intId').value='';
  const it=document.getElementById('intType');
  it.innerHTML=(recruitMeta.interview_types||['Phone','Video','In-Person','Technical','Panel']).map(t=>`<option>${esc(t)}</option>`).join('');
  // populate candidate select
  const cs=document.getElementById('intCandId');
  cs.innerHTML='<option value="">Select candidate…</option>';
  let cands=recruitCandidates;
  if(!cands.length){const r=await api('/api/recruitment/candidates');if(r&&r.ok){cands=await r.json();recruitCandidates=cands;}}
  cands.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=`${esc(c.full_name)} [${esc(c.stage)}]`;if(candId&&c.id===candId)o.selected=true;cs.appendChild(o);});
  document.getElementById('intDate').value='';
  document.getElementById('intTime').value='';
  document.getElementById('intDuration').value=60;
  document.getElementById('intLocation').value='';
  document.getElementById('intInterviewers').value='';
  document.getElementById('intNotes').value='';
  document.getElementById('intFormErr').classList.add('hidden');
  document.getElementById('intModal').classList.remove('hidden');
}
function closeIntModal(){closeModal('intModal');}

async function submitIntForm(e) {
  e.preventDefault();
  const err=document.getElementById('intFormErr');
  err.classList.add('hidden');
  const body={
    candidate_id:parseInt(document.getElementById('intCandId').value),
    interview_type:document.getElementById('intType').value,
    scheduled_date:document.getElementById('intDate').value,
    scheduled_time:document.getElementById('intTime').value,
    duration_mins:parseInt(document.getElementById('intDuration').value)||60,
    location:document.getElementById('intLocation').value||null,
    interviewers:document.getElementById('intInterviewers').value||null,
    notes:document.getElementById('intNotes').value||null,
  };
  const res=await api('/api/recruitment/interviews',{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();err.textContent=d?.detail||'Failed';err.classList.remove('hidden');return;}
  closeIntModal(); loadInterviews();
}

async function markIntStatus(intId,status) {
  await api(`/api/recruitment/interviews/${intId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  if(viewingCandId) await openCandDetail(viewingCandId);
  loadInterviews();
}

// Score Modal
async function openScoreModal(intId,meta) {
  viewingIntId=intId;
  document.getElementById('scoreIntId').value=intId;
  document.getElementById('scoreInterviewMeta').textContent=meta;
  ['scoreTech','scoreComm','scoreAttr','scoreCult','scoreOverall'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('scoreRec').value='Maybe';
  document.getElementById('scoreComments').value='';
  document.getElementById('scoreFormErr').classList.add('hidden');
  document.getElementById('scoreModal').classList.remove('hidden');
  // Load this user's own existing score if any
  const res=await api(`/api/recruitment/interviews/${intId}/scores`);
  if(res&&res.ok){
    const rows=await res.json();
    const mine=rows.find(r=>r.scored_by===currentUser?.username);
    if(mine){
      if(mine.technical_score!=null) document.getElementById('scoreTech').value=mine.technical_score;
      if(mine.communication_score!=null) document.getElementById('scoreComm').value=mine.communication_score;
      if(mine.attitude_score!=null) document.getElementById('scoreAttr').value=mine.attitude_score;
      if(mine.culture_fit_score!=null) document.getElementById('scoreCult').value=mine.culture_fit_score;
      if(mine.overall_score!=null) document.getElementById('scoreOverall').value=mine.overall_score;
      if(mine.recommendation) document.getElementById('scoreRec').value=mine.recommendation;
      if(mine.comments) document.getElementById('scoreComments').value=mine.comments;
    }
  }
}
function closeScoreModal(){closeModal('scoreModal', () => viewingIntId=null);}
async function submitScore(e) {
  e.preventDefault();
  const err=document.getElementById('scoreFormErr');
  err.classList.add('hidden');
  const intId=document.getElementById('scoreIntId').value;
  const v=id=>parseInt(document.getElementById(id).value)||null;
  const body={
    technical_score:v('scoreTech'),communication_score:v('scoreComm'),
    attitude_score:v('scoreAttr'),culture_fit_score:v('scoreCult'),
    overall_score:v('scoreOverall'),recommendation:document.getElementById('scoreRec').value,
    comments:document.getElementById('scoreComments').value||null,
  };
  const res=await api(`/api/recruitment/interviews/${intId}/scores`,{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();err.textContent=d?.detail||'Failed';err.classList.remove('hidden');return;}
  closeScoreModal();
  // Refresh whatever is currently visible
  if(viewingCandId) await openCandDetail(viewingCandId);
  loadInterviews();
}

// ---------------------------------------------------------------------------
// Recruitment — Offers & Letters
// ---------------------------------------------------------------------------
async function loadOffers() {
  await loadRecruitMeta();
  const res=await api('/api/recruitment/offers');
  if(!res||!res.ok) return;
  const rows=await res.json();
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  document.getElementById('addOfferBtn')?.classList.toggle('hidden',!canManage);
  const body=document.getElementById('offerTableBody');
  const empty=document.getElementById('offerEmpty');
  if(!rows.length){body.innerHTML='';empty?.classList.remove('hidden');return;}
  empty?.classList.add('hidden');
  body.innerHTML=rows.map(o=>`
    <tr class="hover:bg-slate-50 cursor-pointer" onclick="openOfferView(${o.id})">
      <td class="px-4 py-3 font-medium text-slate-800">${esc(o.candidate_name)}</td>
      <td class="px-4 py-3 text-slate-600 hidden md:table-cell">${esc(o.requisition_title||'—')}</td>
      <td class="px-4 py-3"><span class="badge ${o.offer_type==='Offer'?'bg-green-100 text-green-700':'bg-red-100 text-red-600'}">${esc(o.offer_type)}</span></td>
      <td class="px-4 py-3 text-slate-700 hidden lg:table-cell">${fmtCurrency(o.salary_offered)}</td>
      <td class="px-4 py-3"><span class="badge ${offerStatusBadge(o.status)}">${esc(o.status)}</span></td>
      <td class="px-4 py-3 text-right"><button class="btn-ghost text-xs" onclick="event.stopPropagation();openOfferView(${o.id})">View</button></td>
    </tr>`).join('');
}

async function openOfferModal(offerId=null, preCandId=null) {
  await loadRecruitMeta();
  document.getElementById('offerId').value=offerId||'';
  let cands=recruitCandidates;
  if(!cands.length){const r=await api('/api/recruitment/candidates');if(r&&r.ok){cands=await r.json();recruitCandidates=cands;}}
  const cs=document.getElementById('offerCandId');
  cs.innerHTML='<option value="">Select candidate…</option>';
  cands.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=`${esc(c.full_name)} [${esc(c.stage)}]`;if(preCandId&&c.id===preCandId)o.selected=true;cs.appendChild(o);});
  // Populate reqs
  const rs=document.getElementById('offerReqId');
  rs.innerHTML='<option value="">None</option>';
  const rr=await api('/api/recruitment/requisitions?status=Approved');
  if(rr&&rr.ok){const reqs=await rr.json();reqs.forEach(r=>{const o=document.createElement('option');o.value=r.id;o.textContent=`${esc(r.title)}`;rs.appendChild(o);});}
  document.getElementById('offerType').value='Offer';
  document.getElementById('offerSalary').value='';
  document.getElementById('offerStart').value='';
  document.getElementById('offerExpiry').value='';
  document.getElementById('offerLetterContent').value='';
  toggleOfferFields();
  document.getElementById('offerFormErr').classList.add('hidden');
  document.getElementById('offerModal').classList.remove('hidden');
}
function closeOfferModal(){closeModal('offerModal');}
function toggleOfferFields() {
  const isOffer=document.getElementById('offerType').value==='Offer';
  ['offerSalaryWrap','offerStartWrap','offerExpiryWrap'].forEach(id=>document.getElementById(id).classList.toggle('hidden',!isOffer));
}
async function previewLetter() {
  const candId=parseInt(document.getElementById('offerCandId').value);
  const offerType=document.getElementById('offerType').value;
  const reqId=parseInt(document.getElementById('offerReqId').value)||null;
  const salary=parseFloat(document.getElementById('offerSalary').value)||null;
  const start=document.getElementById('offerStart').value||null;
  const expiry=document.getElementById('offerExpiry').value||null;
  if(!candId){alert('Select a candidate first');return;}
  const body={candidate_id:candId,offer_type:offerType,requisition_id:reqId,
    salary_offered:salary,start_date:start,expiry_date:expiry,letter_content:''};
  const res=await api('/api/recruitment/offers',{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();alert(d?.detail||'Failed to generate letter');return;}
  const offer=await res.json();
  document.getElementById('offerLetterContent').value=offer.letter_content||'';
  // Update the hidden offerId so submitOfferForm doesn't create another
  document.getElementById('offerId').value=offer.id;
  loadOffers();
}
async function submitOfferForm(e) {
  e.preventDefault();
  const err=document.getElementById('offerFormErr');
  err.classList.add('hidden');
  const existingId=document.getElementById('offerId').value;
  // If already saved via preview, just close
  if(existingId){closeOfferModal();loadOffers();return;}
  const body={
    candidate_id:parseInt(document.getElementById('offerCandId').value),
    offer_type:document.getElementById('offerType').value,
    requisition_id:parseInt(document.getElementById('offerReqId').value)||null,
    salary_offered:parseFloat(document.getElementById('offerSalary').value)||null,
    start_date:document.getElementById('offerStart').value||null,
    expiry_date:document.getElementById('offerExpiry').value||null,
    letter_content:document.getElementById('offerLetterContent').value||'',
  };
  if(!body.candidate_id){err.textContent='Select a candidate';err.classList.remove('hidden');return;}
  const res=await api('/api/recruitment/offers',{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();err.textContent=d?.detail||'Failed';err.classList.remove('hidden');return;}
  closeOfferModal(); loadOffers();
}

async function openOfferView(offerId) {
  viewingOfferId=offerId;
  const res=await api(`/api/recruitment/offers/${offerId}`);
  if(!res||!res.ok) return;
  const o=await res.json();
  document.getElementById('ovTitle').textContent=`${o.offer_type} Letter — ${o.candidate_name}`;
  document.getElementById('ovMeta').textContent=fmtDateTime(o.created_at, true);
  const badge=document.getElementById('ovBadge');
  badge.textContent=o.status; badge.className=`badge ${offerStatusBadge(o.status)}`;
  document.getElementById('ovContent').textContent=o.letter_content||'(no letter content)';
  document.getElementById('ovStatusSelect').value=o.status;
  document.getElementById('offerViewModal').classList.remove('hidden');
}
function closeOfferViewModal(){closeModal('offerViewModal', () => viewingOfferId=null);}
async function updateOfferStatus() {
  if(!viewingOfferId) return;
  const status=document.getElementById('ovStatusSelect').value;
  await api(`/api/recruitment/offers/${viewingOfferId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  const badge=document.getElementById('ovBadge');
  badge.textContent=status; badge.className=`badge ${offerStatusBadge(status)}`;
  loadOffers();
}
function printLetter() {
  const content=document.getElementById('ovContent').textContent;
  const w=window.open('','_blank');
  w.document.write(`<pre style="font-family:monospace;white-space:pre-wrap;padding:2rem;max-width:70ch;margin:auto">${content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</pre>`);
  w.print();
}
function onOfferCandChange() {} // placeholder for future filtering


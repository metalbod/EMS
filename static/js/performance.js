// Performance (Phase 1) — Cycles, Goals (KPI/OKR), Appraisal workflow
// ---------------------------------------------------------------------------
let perfCyclesCache=[];
let currentGoalForForm=null; // full goal object (incl. key_results) when editing an existing goal

const PERF_STATUS_COLORS={'Draft':'bg-slate-100 text-slate-600','Active':'bg-blue-100 text-blue-700','Calibration':'bg-amber-100 text-amber-700','Closed':'bg-green-100 text-green-700'};
const APPR_STATUS_COLORS={'SelfReview':'bg-amber-100 text-amber-700','ManagerReview':'bg-blue-100 text-blue-700','Calibration':'bg-purple-100 text-purple-700','Finalized':'bg-green-100 text-green-700'};

async function loadPerfCyclesCache() {
  const res=await api('/api/performance/cycles');
  perfCyclesCache=res?.ok?await res.json():[];
  return perfCyclesCache;
}

function populateCycleSelect(selectId, cycles) {
  const sel=document.getElementById(selectId);
  const prev=sel.value;
  sel.innerHTML=cycles.map(c=>`<option value="${c.id}">${esc(c.name)} (${c.status})</option>`).join('')||'<option value="">No cycles yet</option>';
  if(prev && cycles.some(c=>String(c.id)===String(prev))) sel.value=prev;
}

function renderGoalRow(g, editable) {
  const scoreText=g.score!=null?`Score: ${g.score}/5`:'Not yet scored';
  let detail='';
  if(g.goal_type==='KPI'){
    detail=`Target: ${g.target_value??'—'} ${esc(g.unit||'')} · Actual: ${g.actual_value??'—'} ${esc(g.unit||'')}`;
  } else {
    const krs=g.key_results||[];
    detail=krs.length?krs.map(k=>`${esc(k.description)}: ${k.actual_value}/${k.target_value}`).join(' · '):'No key results yet';
  }
  return `<div class="border border-slate-100 rounded-lg p-3">
    <div class="flex items-center justify-between gap-2">
      <div class="min-w-0">
        <span class="badge text-xs ${g.goal_type==='KPI'?'bg-cyan-100 text-cyan-700':'bg-violet-100 text-violet-700'}">${g.goal_type}</span>
        <span class="font-medium text-slate-800 ml-2">${esc(g.title)}</span>
        <span class="text-xs text-slate-400 ml-2">(${g.weight}%)</span>
      </div>
      ${editable?`<div class="flex gap-2 flex-shrink-0">
        <button onclick='openGoalModal(${JSON.stringify(g).replace(/'/g,"&apos;")})' class="text-xs text-blue-600 hover:underline">Edit</button>
        <button onclick="deleteGoal(${g.id})" class="text-xs text-red-600 hover:underline">Delete</button>
      </div>`:''}
    </div>
    ${g.description?`<p class="text-xs text-slate-500 mt-1">${esc(g.description)}</p>`:''}
    <p class="text-xs text-slate-500 mt-1">${detail}</p>
    <p class="text-xs text-slate-400 mt-1">${scoreText}</p>
  </div>`;
}

// ---------------------------------------------------------------------------
// Cycles (hr_manager)
// ---------------------------------------------------------------------------
async function loadPerformanceCycles() {
  const listEl=document.getElementById('perfCycleList');
  const emptyEl=document.getElementById('perfCycleEmpty');
  listEl.innerHTML='<tr><td colspan="4" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  await loadPerfCyclesCache();
  if(!perfCyclesCache.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=perfCyclesCache.map(c=>{
    let actions='';
    if(c.status==='Draft') actions=`<button onclick="activateCycle(${c.id})" class="text-xs text-blue-600 hover:underline">Activate</button>`;
    else if(c.status==='Active') actions=`<button onclick="openCalibration(${c.id})" class="text-xs text-blue-600 hover:underline">Open Calibration</button>`;
    else if(c.status==='Calibration') actions=`<button onclick="closeCycle(${c.id})" class="text-xs text-blue-600 hover:underline">Close Cycle</button>`;
    return `<tr class="border-t border-slate-100">
      <td class="px-4 py-3 font-medium text-slate-800">${esc(c.name)}</td>
      <td class="px-4 py-3 text-slate-500">${c.period_start} → ${c.period_end}</td>
      <td class="px-4 py-3"><span class="badge text-xs ${PERF_STATUS_COLORS[c.status]||''}">${c.status}</span></td>
      <td class="px-4 py-3 text-right">${actions}</td>
    </tr>`;
  }).join('');
}

function openCycleModal() {
  document.getElementById('cycleName').value='';
  document.getElementById('cycleStart').value='';
  document.getElementById('cycleEnd').value='';
  document.getElementById('cycleModal').classList.remove('hidden');
}
function closeCycleModal(){ document.getElementById('cycleModal').classList.add('hidden'); }

async function submitCycle() {
  const name=document.getElementById('cycleName').value.trim();
  const period_start=document.getElementById('cycleStart').value;
  const period_end=document.getElementById('cycleEnd').value;
  if(!name||!period_start||!period_end){ alert('All fields are required'); return; }
  const res=await api('/api/performance/cycles',{method:'POST',body:JSON.stringify({name,period_start,period_end})});
  if(res?.ok){ closeCycleModal(); loadPerformanceCycles(); }
  else { const d=await res.json(); alert(d.detail||'Failed to create cycle'); }
}

async function activateCycle(id) {
  if(!confirm('Activate this cycle? This opens goal-setting and creates a self-review appraisal for every active employee.')) return;
  const res=await api(`/api/performance/cycles/${id}/activate`,{method:'PATCH'});
  if(res?.ok){ loadPerformanceCycles(); } else { const d=await res.json(); alert(d.detail||'Failed to activate'); }
}
async function openCalibration(id) {
  if(!confirm('Open calibration for this cycle?')) return;
  const res=await api(`/api/performance/cycles/${id}/open-calibration`,{method:'PATCH'});
  if(res?.ok){ loadPerformanceCycles(); loadCalibrationPage(); } else { const d=await res.json(); alert(d.detail||'Failed to open calibration'); }
}
async function closeCycle(id) {
  if(!confirm('Close this cycle? All calibrated appraisals will be finalized and locked.')) return;
  const res=await api(`/api/performance/cycles/${id}/close`,{method:'PATCH'});
  if(res?.ok){ loadPerformanceCycles(); loadCalibrationPage(); } else { const d=await res.json(); alert(d.detail||'Failed to close cycle'); }
}

// ---------------------------------------------------------------------------
// My Goals & Appraisal
// ---------------------------------------------------------------------------
async function loadMyPerformancePage() {
  await loadPerfCyclesCache();
  populateCycleSelect('perfMyCycleSelect', perfCyclesCache);
  const cycleId=document.getElementById('perfMyCycleSelect').value;
  const content=document.getElementById('perfMyContent');
  if(!cycleId){ content.innerHTML='<p class="text-slate-400 text-sm text-center py-12">No cycles yet.</p>'; document.getElementById('perfAddGoalBtn').classList.add('hidden'); return; }

  const empId=currentUser?.employee_id;
  if(!empId){ content.innerHTML='<p class="text-slate-400 text-sm text-center py-12">No linked employee record.</p>'; document.getElementById('perfAddGoalBtn').classList.add('hidden'); return; }

  const [goalsRes, apprRes] = await Promise.all([
    api(`/api/performance/goals?cycle_id=${cycleId}&employee_id=${empId}`),
    api(`/api/performance/appraisals?cycle_id=${cycleId}`)
  ]);
  const goals=goalsRes?.ok?await goalsRes.json():[];
  const appraisals=apprRes?.ok?await apprRes.json():[];
  const myAppraisal=appraisals.find(a=>a.employee_id===empId);

  const cycle=perfCyclesCache.find(c=>String(c.id)===String(cycleId));
  const canEditGoals=cycle?.status==='Active';
  document.getElementById('perfAddGoalBtn').classList.toggle('hidden', !canEditGoals);

  const totalWeight=goals.reduce((s,g)=>s+(g.weight||0),0);

  let html=`<div class="bg-white rounded-xl border border-slate-200 p-5 mb-5">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-slate-700">Goals <span class="text-xs font-normal ${totalWeight===100?'text-green-500':'text-amber-500'}">(${totalWeight}% weighted${totalWeight!==100?' — should total 100%':''})</span></h3>
      ${myAppraisal?`<span class="badge text-xs ${APPR_STATUS_COLORS[myAppraisal.status]||''}">${myAppraisal.status}</span>`:''}
    </div>
    <div class="space-y-2">${goals.length?goals.map(g=>renderGoalRow(g, canEditGoals)).join(''):'<p class="text-sm text-slate-400">No goals added yet.</p>'}</div>
  </div>`;

  if(myAppraisal){
    html += `<div class="bg-white rounded-xl border border-slate-200 p-5 mb-5">
      <h3 class="text-sm font-semibold text-slate-700 mb-3">Self-Review</h3>`;
    if(myAppraisal.status==='SelfReview'){
      html += `<textarea id="selfReviewComments" class="inp mb-3" rows="3" placeholder="Self-review comments...">${esc(myAppraisal.self_comments||'')}</textarea>
        <button onclick="submitSelfReview(${myAppraisal.id})" class="btn-primary text-sm">Submit Self-Review</button>`;
    } else {
      html += `<p class="text-sm text-slate-600 mb-2">${esc(myAppraisal.self_comments||'No comments.')}</p>
        <p class="text-xs text-slate-400">Self rating: <span class="font-semibold text-slate-700">${myAppraisal.self_rating??'—'}</span></p>`;
    }
    html += `</div>`;

    if(myAppraisal.manager_rating!=null){
      html += `<div class="bg-white rounded-xl border border-slate-200 p-5 mb-5">
        <h3 class="text-sm font-semibold text-slate-700 mb-2">Manager Review</h3>
        <p class="text-sm text-slate-600 mb-2">${esc(myAppraisal.manager_comments||'—')}</p>
        <p class="text-xs text-slate-400">Manager rating: <span class="font-semibold text-slate-700">${myAppraisal.manager_rating??'—'}</span></p>
      </div>`;
    }

    if(myAppraisal.status==='Finalized'){
      html += `<div class="bg-blue-50 border border-blue-200 rounded-xl p-5">
        <h3 class="text-sm font-semibold text-blue-800 mb-1">Final Rating</h3>
        <p class="text-2xl font-bold text-blue-700">${myAppraisal.final_rating??'—'} / 5</p>
      </div>`;
    }
  }

  content.innerHTML=html;
}

// ---------------------------------------------------------------------------
// Goal modal (KPI / OKR)
// ---------------------------------------------------------------------------
function toggleGoalTypeFields() {
  const isOkr=document.getElementById('goalType').value==='OKR';
  document.getElementById('goalKpiFields').classList.toggle('hidden', isOkr);
  document.getElementById('goalOkrFields').classList.toggle('hidden', !isOkr);
}

function openGoalModal(goal) {
  currentGoalForForm=goal||null;
  document.getElementById('goalModalTitle').textContent=goal?'Edit Goal':'Add Goal';
  document.getElementById('goalId').value=goal?.id||'';
  document.getElementById('goalCycleId').value=document.getElementById('perfMyCycleSelect').value;
  document.getElementById('goalEmployeeId').value=currentUser?.employee_id||'';
  document.getElementById('goalType').value=goal?.goal_type||'KPI';
  document.getElementById('goalType').disabled=!!goal;
  document.getElementById('goalTitle').value=goal?.title||'';
  document.getElementById('goalDescription').value=goal?.description||'';
  document.getElementById('goalWeight').value=goal?.weight||0;
  document.getElementById('goalTarget').value=goal?.target_value??'';
  document.getElementById('goalActual').value=goal?.actual_value??'';
  document.getElementById('goalUnit').value=goal?.unit||'';
  toggleGoalTypeFields();
  renderKeyResultsInForm();
  document.getElementById('goalModal').classList.remove('hidden');
}
function closeGoalModal(){ document.getElementById('goalModal').classList.add('hidden'); currentGoalForForm=null; }

function renderKeyResultsInForm() {
  const wrap=document.getElementById('goalKeyResultsList');
  const addRow=document.querySelector('#goalOkrFields .grid');
  const hint=document.getElementById('goalOkrHint');
  if(!currentGoalForForm){
    wrap.innerHTML='';
    addRow.classList.add('hidden');
    hint.classList.remove('hidden');
    return;
  }
  addRow.classList.remove('hidden');
  hint.classList.add('hidden');
  const krs=currentGoalForForm.key_results||[];
  wrap.innerHTML=krs.length?krs.map(k=>`
    <div class="flex items-center gap-2 text-sm bg-slate-50 rounded-lg px-3 py-2">
      <span class="flex-1">${esc(k.description)}</span>
      <input type="number" step="0.01" value="${k.actual_value}" class="inp text-xs" style="width:80px" onchange="updateKeyResultActual(${k.id}, this.value)"/>
      <span class="text-xs text-slate-400">/ ${k.target_value}</span>
      <button onclick="removeKeyResult(${k.id})" class="text-slate-300 hover:text-red-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>`).join(''):'<p class="text-xs text-slate-400">No key results yet.</p>';
}

async function addKeyResultToForm() {
  if(!currentGoalForForm){ alert('Save the goal first, then add key results.'); return; }
  const description=document.getElementById('newKrDescription').value.trim();
  const target_value=parseFloat(document.getElementById('newKrTarget').value)||100;
  if(!description){ alert('Key result description is required'); return; }
  const res=await api(`/api/performance/goals/${currentGoalForForm.id}/key-results`,{method:'POST',body:JSON.stringify({description,target_value,actual_value:0})});
  if(res?.ok){
    const kr=await res.json();
    currentGoalForForm.key_results=[...(currentGoalForForm.key_results||[]), kr];
    document.getElementById('newKrDescription').value='';
    document.getElementById('newKrTarget').value=100;
    renderKeyResultsInForm();
  }
}
async function updateKeyResultActual(krId, value) {
  const kr=currentGoalForForm.key_results.find(k=>k.id===krId);
  await api(`/api/performance/key-results/${krId}`,{method:'PUT',body:JSON.stringify({description:kr.description,target_value:kr.target_value,actual_value:parseFloat(value)||0})});
}
async function removeKeyResult(krId) {
  await api(`/api/performance/key-results/${krId}`,{method:'DELETE'});
  currentGoalForForm.key_results=currentGoalForForm.key_results.filter(k=>k.id!==krId);
  renderKeyResultsInForm();
}

async function submitGoal() {
  const id=document.getElementById('goalId').value;
  const cycle_id=parseInt(document.getElementById('goalCycleId').value);
  const employee_id=document.getElementById('goalEmployeeId').value;
  const goal_type=document.getElementById('goalType').value;
  const title=document.getElementById('goalTitle').value.trim();
  if(!title){ alert('Title is required'); return; }
  const body={
    cycle_id, employee_id, goal_type, title,
    description: document.getElementById('goalDescription').value.trim()||null,
    weight: parseFloat(document.getElementById('goalWeight').value)||0,
    target_value: document.getElementById('goalTarget').value?parseFloat(document.getElementById('goalTarget').value):null,
    actual_value: document.getElementById('goalActual').value?parseFloat(document.getElementById('goalActual').value):null,
    unit: document.getElementById('goalUnit').value.trim()||null,
  };
  const url=id?`/api/performance/goals/${id}`:'/api/performance/goals';
  const res=await api(url,{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(!res?.ok){ const d=await res.json(); alert(d.detail||'Failed to save goal'); return; }
  const saved=await res.json();
  if(!id && goal_type==='OKR'){
    // Re-open in edit mode so key results can now be attached to the saved goal
    currentGoalForForm={...saved, key_results:[]};
    document.getElementById('goalId').value=saved.id;
    document.getElementById('goalModalTitle').textContent='Edit Goal';
    document.getElementById('goalType').disabled=true;
    renderKeyResultsInForm();
    loadMyPerformancePage();
    return;
  }
  closeGoalModal();
  loadMyPerformancePage();
}

async function deleteGoal(id) {
  if(!confirm('Delete this goal?')) return;
  const res=await api(`/api/performance/goals/${id}`,{method:'DELETE'});
  if(res?.ok||res?.status===204){ loadMyPerformancePage(); }
  else { const d=await res.json(); alert(d.detail||'Failed to delete goal'); }
}

async function submitSelfReview(appraisalId) {
  const self_comments=document.getElementById('selfReviewComments').value.trim();
  if(!confirm('Submit self-review? This moves the appraisal to your manager for review.')) return;
  const res=await api(`/api/performance/appraisals/${appraisalId}/self-review`,{method:'POST',body:JSON.stringify({self_comments})});
  if(res?.ok){ loadMyPerformancePage(); } else { const d=await res.json(); alert(d.detail||'Failed to submit'); }
}

// ---------------------------------------------------------------------------
// Team Appraisals (manager / hr_manager)
// ---------------------------------------------------------------------------
async function loadTeamAppraisalsPage() {
  await loadPerfCyclesCache();
  populateCycleSelect('perfTeamCycleSelect', perfCyclesCache);
  const cycleId=document.getElementById('perfTeamCycleSelect').value;
  const listEl=document.getElementById('perfTeamList');
  const emptyEl=document.getElementById('perfTeamEmpty');
  if(!cycleId){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  listEl.innerHTML='<tr><td colspan="5" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const res=await api(`/api/performance/appraisals?cycle_id=${cycleId}`);
  const rows=res?.ok?await res.json():[];
  const teamRows=rows.filter(a=>a.employee_id!==currentUser?.employee_id);
  if(!teamRows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=teamRows.map(a=>`
    <tr class="border-t border-slate-100 ${a.status==='ManagerReview'?'cursor-pointer hover:bg-slate-50':''}" ${a.status==='ManagerReview'?`onclick="openManagerReview(${a.id})"`:''}>
      <td class="px-4 py-3">
        <p class="font-medium text-slate-800">${esc(a.full_name)}</p>
        <p class="text-xs text-slate-400">${esc(a.department||'')}${a.designation?' · '+esc(a.designation):''}</p>
      </td>
      <td class="px-4 py-3"><span class="badge text-xs ${APPR_STATUS_COLORS[a.status]||''}">${a.status}</span></td>
      <td class="px-4 py-3 text-slate-600">${a.self_rating??'—'}</td>
      <td class="px-4 py-3 text-slate-600">${a.manager_rating??'—'}</td>
      <td class="px-4 py-3 text-right">${a.status==='ManagerReview'?'<span class="text-xs text-blue-600">Review →</span>':''}</td>
    </tr>`).join('');
}

async function openManagerReview(appraisalId) {
  const res=await api(`/api/performance/appraisals/${appraisalId}`);
  if(!res?.ok) return;
  const ap=await res.json();
  document.getElementById('mrAppraisalId').value=ap.id;
  document.getElementById('mrModalTitle').textContent=`Manager Review — ${ap.full_name}`;
  document.getElementById('mrModalMeta').textContent=`${ap.department||''}${ap.designation?' · '+ap.designation:''}`;
  document.getElementById('mrGoalsList').innerHTML=ap.goals.length?ap.goals.map(g=>renderGoalRow(g,false)).join(''):'<p class="text-sm text-slate-400">No goals set.</p>';
  document.getElementById('mrSelfComments').textContent=ap.self_comments?`Self-review: "${ap.self_comments}"`:'No self-review comments.';
  document.getElementById('mrRating').value=ap.live_computed_rating??'';
  document.getElementById('mrComments').value='';
  document.getElementById('managerReviewModal').classList.remove('hidden');
}
function closeManagerReviewModal(){ document.getElementById('managerReviewModal').classList.add('hidden'); }

async function submitManagerReview() {
  const id=document.getElementById('mrAppraisalId').value;
  const manager_rating=document.getElementById('mrRating').value?parseFloat(document.getElementById('mrRating').value):null;
  const manager_comments=document.getElementById('mrComments').value.trim()||null;
  const res=await api(`/api/performance/appraisals/${id}/manager-review`,{method:'POST',body:JSON.stringify({manager_rating,manager_comments})});
  if(res?.ok){ closeManagerReviewModal(); loadTeamAppraisalsPage(); }
  else { const d=await res.json(); alert(d.detail||'Failed to submit'); }
}

// ---------------------------------------------------------------------------
// Calibration (hr_manager)
// ---------------------------------------------------------------------------
async function loadCalibrationPage() {
  await loadPerfCyclesCache();
  populateCycleSelect('perfCalibCycleSelect', perfCyclesCache);
  const cycleId=document.getElementById('perfCalibCycleSelect').value;
  const listEl=document.getElementById('perfCalibList');
  const emptyEl=document.getElementById('perfCalibEmpty');
  const distEl=document.getElementById('perfCalibDistribution');
  const actionsEl=document.getElementById('perfCalibActions');
  if(!cycleId){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); distEl.innerHTML=''; actionsEl.innerHTML=''; return; }
  const cycle=perfCyclesCache.find(c=>String(c.id)===String(cycleId));
  actionsEl.innerHTML='';
  if(cycle?.status==='Active') actionsEl.innerHTML=`<button onclick="openCalibration(${cycleId})" class="btn-primary text-sm">Open Calibration</button>`;
  else if(cycle?.status==='Calibration') actionsEl.innerHTML=`<button onclick="closeCycle(${cycleId})" class="btn-primary text-sm">Close Cycle</button>`;

  listEl.innerHTML='<tr><td colspan="7" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const [res, payoutsRes]=await Promise.all([
    api(`/api/performance/appraisals?cycle_id=${cycleId}`),
    api('/api/performance/payouts')
  ]);
  const rows=res?.ok?await res.json():[];
  const payouts=payoutsRes?.ok?await payoutsRes.json():[];
  const calibRows=rows.filter(a=>['Calibration','Finalized'].includes(a.status));
  const payoutsByAppraisal={};
  payouts.forEach(p=>{ (payoutsByAppraisal[p.appraisal_id]=payoutsByAppraisal[p.appraisal_id]||[]).push(p); });

  const buckets={1:0,2:0,3:0,4:0,5:0};
  calibRows.forEach(a=>{ const r=Math.round(a.calibrated_rating??a.manager_rating??0); if(buckets[r]!==undefined) buckets[r]++; });
  const maxCount=Math.max(1,...Object.values(buckets));
  distEl.innerHTML=`<h3 class="text-sm font-semibold text-slate-700 mb-3">Rating Distribution</h3>
    <div class="space-y-1.5">${[5,4,3,2,1].map(r=>`
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-500 w-16">${r} star${r==1?'':'s'}</span>
        <div class="flex-1 bg-slate-100 rounded-full h-2"><div class="bg-blue-500 h-2 rounded-full" style="width:${(buckets[r]/maxCount*100)}%"></div></div>
        <span class="text-xs text-slate-500 w-6 text-right">${buckets[r]}</span>
      </div>`).join('')}</div>`;

  if(!calibRows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=calibRows.map(a=>`
    <tr class="border-t border-slate-100">
      <td class="px-4 py-3">
        <p class="font-medium text-slate-800">${esc(a.full_name)}</p>
        <p class="text-xs text-slate-400">${esc(a.department||'')}</p>
      </td>
      <td class="px-4 py-3 text-slate-600">${a.self_rating??'—'}</td>
      <td class="px-4 py-3 text-slate-600">${a.manager_rating??'—'}</td>
      <td class="px-4 py-3">${a.status==='Finalized'?(a.final_rating??'—'):`<input type="number" step="0.01" min="1" max="5" class="inp text-xs" style="width:70px" id="calib-rating-${a.id}" value="${a.calibrated_rating??''}" placeholder="${a.manager_rating??''}"/>`}</td>
      <td class="px-4 py-3">${a.status==='Finalized'?esc(a.calibration_notes||''):`<input type="text" class="inp text-xs" id="calib-notes-${a.id}" value="${esc(a.calibration_notes||'')}" placeholder="Notes (required if overriding)"/>`}</td>
      <td class="px-4 py-3">${a.status==='Finalized'?renderPayoutCell(a, payoutsByAppraisal[a.id]||[]):'<span class="text-xs text-slate-300">—</span>'}</td>
      <td class="px-4 py-3 text-right">${a.status==='Calibration'?`<button onclick="saveCalibration(${a.id})" class="text-xs text-blue-600 hover:underline">Save</button>`:'<span class="text-xs text-green-600">Finalized</span>'}</td>
    </tr>`).join('');
}

function renderPayoutCell(a, payouts) {
  const increment=payouts.find(p=>p.payout_type==='MeritIncrement');
  const bonuses=payouts.filter(p=>p.payout_type==='Bonus');
  const bonusTotal=bonuses.reduce((s,p)=>s+p.amount,0);
  const incrementHtml=increment
    ? `<span class="text-xs text-green-600">+${increment.increment_pct}% applied</span>`
    : `<button onclick='openPayoutModal(${a.id},"increment","${esc(a.full_name)}")' class="text-xs text-blue-600 hover:underline">Apply Increment</button>`;
  const bonusHtml=bonuses.length
    ? `<span class="text-xs ${bonuses.some(p=>p.status==='Pending')?'text-amber-600':'text-green-600'}">RM ${bonusTotal.toFixed(2)} ${bonuses.some(p=>p.status==='Pending')?'queued':'paid'}</span> <button onclick='openPayoutModal(${a.id},"bonus","${esc(a.full_name)}")' class="text-xs text-blue-600 hover:underline">+Add</button>`
    : `<button onclick='openPayoutModal(${a.id},"bonus","${esc(a.full_name)}")' class="text-xs text-blue-600 hover:underline">Add Bonus</button>`;
  return `<div class="flex flex-col gap-1">${incrementHtml}${bonusHtml}</div>`;
}

function openPayoutModal(appraisalId, type, employeeName) {
  document.getElementById('payoutAppraisalId').value=appraisalId;
  document.getElementById('payoutAppraisalId').dataset.type=type;
  document.getElementById('payoutModalTitle').textContent=type==='increment'?'Apply Merit Increment':'Add Bonus';
  document.getElementById('payoutModalMeta').textContent=employeeName;
  document.getElementById('payoutIncrementField').classList.toggle('hidden', type!=='increment');
  document.getElementById('payoutBonusField').classList.toggle('hidden', type!=='bonus');
  document.getElementById('payoutIncrementPct').value='';
  document.getElementById('payoutBonusAmount').value='';
  document.getElementById('payoutModal').classList.remove('hidden');
}
function closePayoutModal(){ document.getElementById('payoutModal').classList.add('hidden'); }

async function submitPayout() {
  const appraisalId=document.getElementById('payoutAppraisalId').value;
  const type=document.getElementById('payoutAppraisalId').dataset.type;
  let res;
  if(type==='increment'){
    const increment_pct=parseFloat(document.getElementById('payoutIncrementPct').value);
    if(!increment_pct || increment_pct<=0){ alert('Enter a valid increment percentage'); return; }
    if(!confirm(`Apply a ${increment_pct}% merit increment? This updates the employee's basic salary immediately.`)) return;
    res=await api(`/api/performance/appraisals/${appraisalId}/merit-increment`,{method:'POST',body:JSON.stringify({increment_pct})});
  } else {
    const amount=parseFloat(document.getElementById('payoutBonusAmount').value);
    if(!amount || amount<=0){ alert('Enter a valid bonus amount'); return; }
    res=await api(`/api/performance/appraisals/${appraisalId}/bonus`,{method:'POST',body:JSON.stringify({amount})});
  }
  if(res?.ok){ closePayoutModal(); loadCalibrationPage(); }
  else { const d=await res.json(); alert(d.detail||'Failed to apply payout'); }
}

async function saveCalibration(appraisalId) {
  const ratingInput=document.getElementById(`calib-rating-${appraisalId}`);
  const notesInput=document.getElementById(`calib-notes-${appraisalId}`);
  const calibrated_rating=ratingInput.value?parseFloat(ratingInput.value):null;
  const calibration_notes=notesInput.value.trim()||null;
  const res=await api(`/api/performance/appraisals/${appraisalId}/calibrate`,{method:'POST',body:JSON.stringify({calibrated_rating,calibration_notes})});
  if(res?.ok){ loadCalibrationPage(); } else { const d=await res.json(); alert(d.detail||'Failed to save'); }
}

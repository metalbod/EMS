// Dashboard
// ---------------------------------------------------------------------------
function renderDashboard() {
  checkDashboardSystemNotification();
  checkDashboardNotification();
  loadDashboardTodos();
  if (currentUser.role === 'superadmin' && !currentInstitution) {
    document.getElementById('superadminGlobalDash').classList.remove('hidden');
    document.getElementById('instDash').classList.add('hidden');
    document.getElementById('gStatInst').textContent = institutions.length;
    document.getElementById('gStatEmp').textContent = institutions.reduce((a,i)=>a+i.employee_count,0);
    document.getElementById('gStatUser').textContent = institutions.reduce((a,i)=>a+i.user_count,0);
    document.getElementById('gInstList').innerHTML = institutions.map(i=>`
      <div class="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-0">
        <div class="flex items-center gap-3">
          <span class="badge ${i.status==='Active'?'bg-emerald-100 text-emerald-700':'bg-red-100 text-red-600'}">${i.status}</span>
          <div>
            <p class="text-sm font-medium">${esc(i.name)}</p>
            <p class="text-xs text-slate-400">${esc(i.code)} · ${i.employee_count} employees</p>
          </div>
        </div>
        <button onclick="enterInstitutionContext(this.dataset.inst)" data-inst='${JSON.stringify(i).replace(/'/g,"&apos;")}' class="btn-primary" style="font-size:.75rem;padding:.25rem .75rem">Manage</button>
      </div>
    `).join('') || '<p class="text-slate-400 text-sm">No institutions.</p>';
    return;
  }
  document.getElementById('superadminGlobalDash').classList.add('hidden');
  document.getElementById('instDash').classList.remove('hidden');
  const active = employees.filter(e=>e.status==='Active');
  const depts = [...new Set(employees.map(e=>e.department))];
  document.getElementById('statTotal').textContent = employees.length;
  document.getElementById('statActive').textContent = active.length;
  document.getElementById('statInactive').textContent = employees.length - active.length;
  document.getElementById('statDepts').textContent = depts.length;
  const deptCounts = {};
  employees.forEach(e=>{ deptCounts[e.department]=(deptCounts[e.department]||0)+1; });
  document.getElementById('deptBreakdown').innerHTML = Object.entries(deptCounts)
    .sort((a,b)=>b[1]-a[1]).map(([d,c])=>`
      <div class="flex items-center gap-2">
        <div class="w-28 text-xs text-slate-600 truncate">${esc(d)}</div>
        <div class="flex-1 bg-slate-100 rounded-full h-2">
          <div class="bg-blue-500 h-2 rounded-full" style="width:${Math.round(c/employees.length*100)}%"></div>
        </div>
        <div class="text-xs text-slate-500 w-5 text-right">${c}</div>
      </div>`).join('') || '<p class="text-slate-400 text-sm">No data.</p>';
  const typeCounts = {};
  employees.forEach(e=>{ typeCounts[e.employment_type]=(typeCounts[e.employment_type]||0)+1; });
  document.getElementById('empTypeBreakdown').innerHTML = Object.entries(typeCounts)
    .sort((a,b)=>b[1]-a[1]).map(([t,c])=>`
      <div class="flex items-center gap-2">
        <div class="w-24 text-xs text-slate-600">${esc(t)}</div>
        <div class="flex-1 bg-slate-100 rounded-full h-2">
          <div class="bg-violet-500 h-2 rounded-full" style="width:${Math.round(c/employees.length*100)}%"></div>
        </div>
        <div class="text-xs text-slate-500 w-5 text-right">${c}</div>
      </div>`).join('') || '<p class="text-slate-400 text-sm">No data.</p>';

  // Recruitment stats — visible to HR roles only
  const canRecruit = ['superadmin','hr_manager','hr_admin','manager'].includes(currentUser?.role);
  const recruitSection = document.getElementById('recruitDashSection');
  recruitSection.classList.toggle('hidden', !canRecruit);
  if (canRecruit) {
    api('/api/recruitment/dashboard-stats').then(async res => {
      if (!res || !res.ok) return;
      const s = await res.json();
      document.getElementById('rStatOpenReq').textContent = (s.req_by_status['Approved'] || 0) + (s.req_by_status['Draft'] || 0);
      document.getElementById('rStatPendingApproval').textContent = s.pending_approvals ? `${s.pending_approvals} pending approval` : '';
      document.getElementById('rStatCands').textContent = s.total_candidates;
      document.getElementById('rStatHiredMonth').textContent = s.hired_this_month ? `${s.hired_this_month} hired this month` : '';
      document.getElementById('rStatUpcoming').textContent = s.upcoming_interviews;
      document.getElementById('rStatIntMonth').textContent = `${s.interviews_this_month} this month`;
      document.getElementById('rStatOffers').textContent = s.offers_pending;

      // Candidate pipeline bar chart
      const PIPELINE_STAGES = ['New','Screening','Interview','Offer','Hired','Rejected','Withdrawn'];
      const PIPELINE_COLORS = {New:'bg-slate-400',Screening:'bg-blue-400',Interview:'bg-purple-400',Offer:'bg-yellow-400',Hired:'bg-emerald-500',Rejected:'bg-red-400',Withdrawn:'bg-slate-300'};
      const totalCands = s.total_candidates || 1;
      document.getElementById('rCandPipeline').innerHTML = PIPELINE_STAGES.map(stage => {
        const cnt = s.cand_by_stage[stage] || 0;
        if (!cnt && !['New','Screening','Interview','Offer'].includes(stage)) return '';
        return `<div class="flex items-center gap-2">
          <div class="w-20 text-xs text-slate-600">${stage}</div>
          <div class="flex-1 bg-slate-100 rounded-full h-2">
            <div class="${PIPELINE_COLORS[stage]||'bg-slate-400'} h-2 rounded-full" style="width:${Math.round(cnt/totalCands*100)}%"></div>
          </div>
          <div class="text-xs text-slate-500 w-5 text-right">${cnt}</div>
        </div>`;
      }).join('') || '<p class="text-slate-400 text-sm">No candidates yet.</p>';

      // Requisitions by status
      const REQ_COLORS = {Draft:'bg-slate-300','Pending Approval':'bg-amber-400',Approved:'bg-emerald-400',Rejected:'bg-red-400',Filled:'bg-blue-400',Closed:'bg-slate-200'};
      const totalReqs = s.total_requisitions || 1;
      document.getElementById('rReqStatus').innerHTML = Object.entries(s.req_by_status)
        .sort((a,b)=>b[1]-a[1]).map(([status,cnt])=>`
          <div class="flex items-center gap-2">
            <div class="w-28 text-xs text-slate-600 truncate">${status}</div>
            <div class="flex-1 bg-slate-100 rounded-full h-2">
              <div class="${REQ_COLORS[status]||'bg-slate-400'} h-2 rounded-full" style="width:${Math.round(cnt/totalReqs*100)}%"></div>
            </div>
            <div class="text-xs text-slate-500 w-5 text-right">${cnt}</div>
          </div>`).join('') || '<p class="text-slate-400 text-sm">No requisitions yet.</p>';
    });
  }

  // Project utilization — HR Manager / superadmin only
  const canViewUtil = ['superadmin','hr_manager'].includes(currentUser?.role);
  const utilSection = document.getElementById('utilDashSection');
  utilSection.classList.toggle('hidden', !canViewUtil);
  if (canViewUtil) {
    api('/api/projects/utilization').then(async res => {
      if (!res || !res.ok) return;
      const projects = await res.json();
      const listEl = document.getElementById('utilProjectList');
      const emptyEl = document.getElementById('utilEmpty');
      if (!projects.length) { listEl.innerHTML=''; emptyEl.classList.remove('hidden'); return; }
      emptyEl.classList.add('hidden');
      listEl.innerHTML = projects.map(p => {
        const taskRows = p.tasks.length ? p.tasks.map(t => {
          const pct = t.estimated_hours ? Math.min(100, Math.round(t.logged_hours / t.estimated_hours * 100)) : null;
          const over = t.estimated_hours && t.logged_hours > t.estimated_hours;
          return `<div class="flex items-center gap-2">
            <div class="w-40 text-xs text-slate-600 truncate" title="${esc(t.name)}">${esc(t.name)}</div>
            <div class="flex-1 bg-slate-100 rounded-full h-2">
              <div class="${over?'bg-red-500':'bg-blue-500'} h-2 rounded-full" style="width:${pct===null?(t.logged_hours>0?100:0):pct}%"></div>
            </div>
            <div class="text-xs ${over?'text-red-600 font-medium':'text-slate-500'} w-24 text-right">${t.logged_hours}${t.estimated_hours?` / ${t.estimated_hours}h`:'h'}</div>
          </div>`;
        }).join('') : '<p class="text-xs text-slate-400">No tasks defined yet.</p>';
        return `<div class="bg-white rounded-xl border border-slate-200 p-5">
          <div class="flex items-center justify-between mb-3">
            <h4 class="font-medium text-sm text-slate-800">${esc(p.name)}</h4>
            <span class="text-xs font-semibold text-slate-600">${p.total_hours}h total</span>
          </div>
          <div class="space-y-2">${taskRows}</div>
        </div>`;
      }).join('');
    });
  }
}

// ---------------------------------------------------------------------------
// Dashboard To-Do list — computed server-side from live pending-action state.
// Always visible (per spec) for all roles except superadmin, even when empty.
// ---------------------------------------------------------------------------
async function loadDashboardTodos() {
  const card=document.getElementById('dashboardTodoCard');
  if(!card) return;
  if(currentUser?.role==='superadmin'){ card.classList.add('hidden'); return; }
  card.classList.remove('hidden');
  const listEl=document.getElementById('dashboardTodoList');
  const emptyEl=document.getElementById('dashboardTodoEmpty');
  const res=await api('/api/todos');
  const items=res?.ok?await res.json():[];
  if(!items.length){
    listEl.innerHTML='';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');
  listEl.innerHTML=items.map(t=>`
    <div class="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-50 cursor-pointer transition" onclick="showPage('${t.page}')">
      <span class="text-sm text-slate-700">${esc(t.label)}</span>
      <svg class="w-4 h-4 text-slate-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
    </div>`).join('');
}

// ---------------------------------------------------------------------------

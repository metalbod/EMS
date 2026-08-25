// Dashboard
// ---------------------------------------------------------------------------
// Tabs load lazily (dash-tabs.js loaded flag) — everything past General/
// Workforce used to fire its own API call in parallel on every single
// dashboard visit regardless of which section (if any) the user actually
// looked at. For an HR manager that's 4+ concurrent DB round-trips just to
// land on the page. Now only General (notifications/To-Do) and Workforce
// (which includes Locations Overview) fetch up front, since both are
// reachable with a single click from landing; Recruitment/Timesheet/
// Compensation & Benefits fetch once, on first click, and are cached for
// the rest of the session.
const _dashTabLoaded = { recruitment: false, timesheet: false, compensation: false, leave: false };
let _lastBenefitsDashboard = null;
window.getLastBenefitsDashboard = () => _lastBenefitsDashboard;

function switchDashTab(tabId) {
  document.querySelectorAll('.dash-tab-panel').forEach(el => el.classList.toggle('hidden', el.id !== tabId));
  document.querySelectorAll('[data-dashtab]').forEach(btn => {
    const active = btn.dataset.dashtab === tabId;
    btn.classList.toggle('view-tab-active', active);
    btn.classList.toggle('text-slate-500', !active);
  });
  if (tabId === 'dash-recruitment' && !_dashTabLoaded.recruitment) { _dashTabLoaded.recruitment = true; loadRecruitmentDash(); }
  if (tabId === 'dash-timesheet' && !_dashTabLoaded.timesheet) { _dashTabLoaded.timesheet = true; loadTimesheetDash(); }
  if (tabId === 'dash-compensation' && !_dashTabLoaded.compensation) { _dashTabLoaded.compensation = true; loadCompensationDash(); }
  if (tabId === 'dash-leave' && !_dashTabLoaded.leave) { _dashTabLoaded.leave = true; loadLeaveDash(); }
}

function renderDashboard() {
  checkDashboardSystemNotification();
  checkDashboardNotification();
  loadDashboardTodos();
  document.getElementById('dashboardQuickActions')?.classList.toggle('hidden', currentUser?.role !== 'employee');
  if (currentUser?.role === 'employee') refreshResignButtonState();
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
  const inactive = employees.filter(e=>e.status!=='Active');
  const depts = [...new Set(employees.map(e=>e.department))];
  const total = employees.length || 1;
  document.getElementById('statTotal').textContent = employees.length;
  document.getElementById('statActive').textContent = active.length;
  document.getElementById('statInactive').textContent = inactive.length;
  document.getElementById('statDepts').textContent = depts.length;
  const genderLabel = arr => arr.length
    ? `${arr.filter(e=>e.gender==='Male').length} Male · ${arr.filter(e=>e.gender==='Female').length} Female` : '—';
  document.getElementById('statTotalGender').textContent = genderLabel(employees);
  document.getElementById('statActiveGender').textContent = genderLabel(active);
  document.getElementById('statInactiveGender').textContent = genderLabel(inactive);
  document.getElementById('statActivePct').textContent = `${Math.round(active.length/total*100)}%`;
  document.getElementById('statInactivePct').textContent = `${Math.round(inactive.length/total*100)}%`;
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

  // Workforce Composition — Nationality (Local/Foreigner) and Race, as
  // proportional segmented bars. Nationality is free text in this app (see
  // core/constants.py — there's no NATIONALITIES enum), so "Local" is a
  // nationality==='Malaysian' heuristic, not a validated field; anything
  // else (including typos/inconsistent entries) counts as "Foreigner".
  // Race IS a validated, required 7-value enum (core/constants.py's
  // RACES) — every employee always has one, so there's no "Undefined"
  // bucket to design for, unlike a generic HR system might need.
  const segmentedBar = (containerId, legendId, segments) => {
    const shown = segments.filter(s => s.count > 0);
    document.getElementById(containerId).innerHTML = shown.map(s =>
      `<div class="${s.color}" style="width:${Math.round(s.count/total*100)}%" title="${esc(s.label)}: ${s.count}"></div>`
    ).join('');
    document.getElementById(legendId).innerHTML = shown.map(s =>
      `<span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full ${s.color} inline-block"></span>${esc(s.label)} ${s.count}</span>`
    ).join('') || '<span class="text-slate-400">No data.</span>';
  };
  const localCount = employees.filter(e=>e.nationality==='Malaysian').length;
  segmentedBar('nationalityBar', 'nationalityLegend', [
    { label:'Local', count:localCount, color:'bg-blue-700' },
    { label:'Foreigner', count:employees.length-localCount, color:'bg-blue-300' },
  ]);
  const RACE_COLORS = {
    'Malay':'bg-blue-600', 'Chinese':'bg-emerald-500', 'Indian':'bg-amber-500',
    'Bumiputera Sabah':'bg-rose-500', 'Bumiputera Sarawak':'bg-violet-500',
    'Orang Asli':'bg-cyan-500', 'Others':'bg-slate-400',
  };
  const raceCounts = {};
  employees.forEach(e=>{ raceCounts[e.race]=(raceCounts[e.race]||0)+1; });
  segmentedBar('raceBar', 'raceLegend',
    Object.entries(raceCounts).sort((a,b)=>b[1]-a[1])
      .map(([race,count])=>({ label:race, count, color:RACE_COLORS[race]||'bg-slate-400' })));

  // Locations overview (Workforce tab, HR Manager / HR Admin only) — the one
  // section besides base stats that still fetches immediately, since it's
  // grouped into the always-visible Workforce tab rather than a lazy tab.
  const canViewLoc = ['hr_manager','hr_admin'].includes(currentUser?.role);
  document.getElementById('locDashSection').classList.toggle('hidden', !canViewLoc);
  if (canViewLoc) loadLocationsOverviewDash();

  // Reset per-tab load-once flags and gate tab button visibility for this
  // user/institution context, then always land back on General.
  _dashTabLoaded.recruitment = false;
  _dashTabLoaded.timesheet = false;
  _dashTabLoaded.compensation = false;
  _dashTabLoaded.leave = false;
  const canRecruit = ['superadmin','hr_manager','hr_admin','manager'].includes(currentUser?.role);
  const canViewUtil = ['superadmin','hr_manager'].includes(currentUser?.role);
  const canViewBenefitsDash = ['hr_manager','compensation_manager','manager'].includes(currentUser?.role);
  const hasEmployeeRecord = !!currentUser?.employee_id;
  const canViewLeaveDash = ['hr_manager','hr_admin'].includes(currentUser?.role);
  document.getElementById('dash-tab-recruitment-btn').classList.toggle('hidden', !canRecruit);
  document.getElementById('dash-tab-timesheet-btn').classList.toggle('hidden', !canViewUtil);
  document.getElementById('dash-tab-compensation-btn').classList.toggle('hidden', !(canViewBenefitsDash || hasEmployeeRecord));
  document.getElementById('dash-tab-leave-btn').classList.toggle('hidden', !(canViewLeaveDash || hasEmployeeRecord));
  switchDashTab('dash-general');
}

function loadLocationsOverviewDash() {
  api('/api/institutions/' + currentUser.institution_id + '/location-summary').then(async res => {
    if (!res || !res.ok) return;
    const s = await res.json();

    document.getElementById('locStatTotal').textContent = s.total_locations || 0;

    const avgUtil = s.locations && s.locations.length > 0
      ? Math.round(s.locations.reduce((sum, loc) => sum + (loc.utilization_percent || 0), 0) / s.locations.length)
      : 0;
    document.getElementById('locStatAvgUtil').textContent = avgUtil + '%';

    const totalEmpInLoc = s.locations ? s.locations.reduce((sum, loc) => sum + (loc.employee_count || 0), 0) : 0;
    document.getElementById('locStatEmpCount').textContent = totalEmpInLoc;

    const withManager = s.locations ? s.locations.filter(loc => loc.manager_user_id).length : 0;
    document.getElementById('locStatManaged').textContent = withManager;

    if (s.locations && s.locations.length > 0) {
      const maxEmps = Math.max(...s.locations.map(l => l.employee_count || 0)) || 1;
      document.getElementById('locEmpDistribution').innerHTML = s.locations
        .sort((a, b) => (b.employee_count || 0) - (a.employee_count || 0))
        .map(loc => `
          <div class="flex items-center gap-2">
            <div class="w-32 text-xs text-slate-600 truncate" title="${esc(loc.location_name)}">${esc(loc.location_name)}</div>
            <div class="flex-1 bg-slate-100 rounded-full h-2">
              <div class="bg-blue-500 h-2 rounded-full" style="width:${Math.round((loc.employee_count || 0)/maxEmps*100)}%"></div>
            </div>
            <div class="text-xs text-slate-500 w-6 text-right">${loc.employee_count || 0}</div>
          </div>
        `).join('');
    } else {
      document.getElementById('locEmpDistribution').innerHTML = '<p class="text-slate-400 text-sm">No locations yet.</p>';
    }

    if (s.locations && s.locations.length > 0) {
      const locWithCap = s.locations.filter(l => l.capacity && l.capacity > 0);
      if (locWithCap.length > 0) {
        document.getElementById('locCapacityChart').innerHTML = locWithCap
          .sort((a, b) => (b.utilization_percent || 0) - (a.utilization_percent || 0))
          .map(loc => {
            const util = loc.utilization_percent || 0;
            const color = util > 90 ? 'bg-red-500' : util > 70 ? 'bg-amber-500' : 'bg-emerald-500';
            return `
              <div class="flex items-center gap-2">
                <div class="w-32 text-xs text-slate-600 truncate" title="${esc(loc.location_name)}">${esc(loc.location_name)}</div>
                <div class="flex-1 bg-slate-100 rounded-full h-2">
                  <div class="${color} h-2 rounded-full" style="width:${util}%"></div>
                </div>
                <div class="text-xs text-slate-500 w-10 text-right">${util}%</div>
              </div>
            `;
          }).join('');
      } else {
        document.getElementById('locCapacityChart').innerHTML = '<p class="text-slate-400 text-sm">No capacity data.</p>';
      }
    } else {
      document.getElementById('locCapacityChart').innerHTML = '<p class="text-slate-400 text-sm">No locations yet.</p>';
    }
  });
}

function loadRecruitmentDash() {
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
    const PIPELINE_STAGES = ['New','Screening','Interview','Pending Checks','Offer','Hired','Rejected by Candidate','Rejected by Company','Withdrawn'];
    const PIPELINE_COLORS = {New:'bg-slate-400',Screening:'bg-blue-400',Interview:'bg-purple-400','Pending Checks':'bg-orange-400',Offer:'bg-yellow-400',Hired:'bg-emerald-500','Rejected by Candidate':'bg-red-400','Rejected by Company':'bg-red-400',Withdrawn:'bg-slate-300'};
    const totalCands = s.total_candidates || 1;
    document.getElementById('rCandPipeline').innerHTML = s.total_candidates ? PIPELINE_STAGES.map(stage => {
      const cnt = s.cand_by_stage[stage] || 0;
      return `<div class="flex items-center gap-2">
        <div class="w-20 text-xs text-slate-600">${stage}</div>
        <div class="flex-1 bg-slate-100 rounded-full h-2">
          <div class="${statusColor(PIPELINE_COLORS, stage, 'bg-slate-400')} h-2 rounded-full" style="width:${Math.round(cnt/totalCands*100)}%"></div>
        </div>
        <div class="text-xs text-slate-500 w-5 text-right">${cnt}</div>
      </div>`;
    }).join('') : '<p class="text-slate-400 text-sm">No candidates yet.</p>';

    // Requisitions by status
    const REQ_COLORS = {Draft:'bg-slate-300','Pending Approval':'bg-amber-400',Approved:'bg-emerald-400',Rejected:'bg-red-400',Filled:'bg-blue-400',Closed:'bg-slate-200'};
    const totalReqs = s.total_requisitions || 1;
    document.getElementById('rReqStatus').innerHTML = Object.entries(s.req_by_status)
      .sort((a,b)=>b[1]-a[1]).map(([status,cnt])=>`
        <div class="flex items-center gap-2">
          <div class="w-28 text-xs text-slate-600 truncate">${status}</div>
          <div class="flex-1 bg-slate-100 rounded-full h-2">
            <div class="${statusColor(REQ_COLORS, status, 'bg-slate-400')} h-2 rounded-full" style="width:${Math.round(cnt/totalReqs*100)}%"></div>
          </div>
          <div class="text-xs text-slate-500 w-5 text-right">${cnt}</div>
        </div>`).join('') || '<p class="text-slate-400 text-sm">No requisitions yet.</p>';
  });
}

function loadTimesheetDash() {
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

function loadCompensationDash() {
  // Benefits cost & utilization — HR Manager / Compensation Manager / Manager
  const canViewBenefitsDash = ['hr_manager','compensation_manager','manager'].includes(currentUser?.role);
  document.getElementById('benefitsDashSection')?.classList.toggle('hidden', !canViewBenefitsDash);
  if (canViewBenefitsDash) {
    api('/api/benefits/reports/dashboard').then(async res => {
      if (!res || !res.ok) return;
      const s = await res.json();
      _lastBenefitsDashboard = s;
      document.getElementById('bdActivePlans').textContent = s.total_active_plans;
      document.getElementById('bdEnrolledEmployees').textContent = s.total_enrolled_employees;
      document.getElementById('bdEmployerCost').textContent = fmtCurrency(s.total_monthly_employer_cost);
      document.getElementById('bdClaimsPaid').textContent = fmtCurrency(s.total_claims_paid_ytd);

      const deptEl = document.getElementById('bdDeptCostList');
      document.getElementById('bdDeptCostEmpty')?.classList.toggle('hidden', s.department_costs.length > 0);
      const maxDeptCost = Math.max(...s.department_costs.map(d => d.monthly_employer_cost_total), 1);
      deptEl.innerHTML = s.department_costs.map(d => `
        <div class="flex items-center gap-2">
          <div class="w-28 text-xs text-slate-600 truncate" title="${esc(d.department)}">${esc(d.department)}</div>
          <div class="flex-1 bg-slate-100 rounded-full h-2">
            <div class="bg-blue-500 h-2 rounded-full" style="width:${Math.round(d.monthly_employer_cost_total/maxDeptCost*100)}%"></div>
          </div>
          <div class="text-xs text-slate-500 w-20 text-right">${fmtCurrency(d.monthly_employer_cost_total)}</div>
        </div>`).join('');

      const planEl = document.getElementById('bdPlanUtilList');
      document.getElementById('bdPlanUtilEmpty')?.classList.toggle('hidden', s.plan_utilization.length > 0);
      planEl.innerHTML = s.plan_utilization.map(p => `
        <tr class="border-t border-slate-100">
          <td class="py-1.5 text-xs text-slate-600 truncate max-w-[9rem]" title="${esc(p.plan_name)}">${esc(p.plan_name)}</td>
          <td class="py-1.5 text-xs text-slate-700 text-right">${fmtCurrency(p.claims_claimed_ytd)}</td>
          <td class="py-1.5 text-xs text-slate-700 text-right">${fmtCurrency(p.claims_paid_ytd)}</td>
        </tr>`).join('');
    });
  }

  // My Benefits — anyone with a linked employee record
  const hasEmployeeRecord = !!currentUser?.employee_id;
  document.getElementById('myBenefitsDashSection')?.classList.toggle('hidden', !hasEmployeeRecord);
  if (hasEmployeeRecord) {
    api('/api/benefits/dashboard/mine').then(async res => {
      if (!res || !res.ok) return;
      const s = await res.json();

      const claimsEl = document.getElementById('mdClaimsList');
      document.getElementById('mdClaimsEmpty')?.classList.toggle('hidden', s.recent_claims.length > 0);
      const claimBadge = status => {
        if (status === 'Approved') return 'bg-blue-100 text-blue-700';
        if (status === 'Paid') return 'bg-emerald-100 text-emerald-700';
        if (status === 'Rejected') return 'bg-red-100 text-red-700';
        return 'bg-amber-100 text-amber-700';
      };
      claimsEl.innerHTML = s.recent_claims.map(c => `
        <div class="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0">
          <div>
            <p class="text-sm text-slate-700">${esc(c.plan_name)}</p>
            <p class="text-xs text-slate-400">${fmtDate(c.claim_date)} · ${fmtCurrency(c.amount_claimed)}</p>
          </div>
          <span class="badge ${claimBadge(c.status)}">${esc(c.status)}</span>
        </div>`).join('');

      const balEl = document.getElementById('mdBalancesList');
      document.getElementById('mdBalancesEmpty')?.classList.toggle('hidden', s.balances.length > 0);
      balEl.innerHTML = s.balances.map(b => {
        const pctUsed = b.annual_cap > 0 ? Math.min(100, Math.round(b.used_amount / b.annual_cap * 100)) : 0;
        return `
        <div>
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm text-slate-700">${esc(b.plan_name)}</span>
            <span class="text-xs text-slate-500">${fmtCurrency(b.remaining_amount)} left of ${fmtCurrency(b.annual_cap)}</span>
          </div>
          <div class="bg-slate-100 rounded-full h-2">
            <div class="bg-emerald-500 h-2 rounded-full" style="width:${pctUsed}%"></div>
          </div>
        </div>`;
      }).join('');
    });
  }
}

function exportBenefitsDeptCostCsv() {
  const s = window.getLastBenefitsDashboard?.();
  if (!s) return;
  const rows = [['Department', 'Enrolled Count', 'Monthly Employer Cost', 'Monthly Employee Cost']];
  s.department_costs.forEach(d => rows.push([d.department, d.enrolled_count, d.monthly_employer_cost_total, d.monthly_employee_cost_total]));
  downloadCsv(rows, 'benefits-cost-by-department.csv');
}

function exportBenefitsUtilizationCsv() {
  const s = window.getLastBenefitsDashboard?.();
  if (!s) return;
  const rows = [['Plan', 'Category', 'Enrolled', 'Waived', 'Claims Claimed YTD', 'Claims Paid YTD']];
  s.plan_utilization.forEach(p => rows.push([p.plan_name, p.plan_category, p.enrolled_count, p.waived_count, p.claims_claimed_ytd, p.claims_paid_ytd]));
  downloadCsv(rows, 'benefits-utilization-by-plan.csv');
}

function downloadCsv(rows, filename) {
  const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
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
  listEl.innerHTML=items.map(t=>{
    // A "dash-" page value is a Dashboard sub-tab (e.g. "dash-leave" for
    // the monthly calendar), not a top-level page — showPage() alone
    // lands on the Dashboard's default tab, so it needs switchDashTab()
    // too. No top-level ALL_PAGES entry starts with "dash-", so this
    // prefix check is unambiguous.
    const onclick = t.page.startsWith('dash-')
      ? `showPage('dashboard');switchDashTab('${t.page}')`
      : `showPage('${t.page}')`;
    return `
    <div class="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-50 cursor-pointer transition" onclick="${onclick}">
      <span class="text-sm text-slate-700">${esc(t.label)}</span>
      <svg class="w-4 h-4 text-slate-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
    </div>`;
  }).join('');
}

// Dashboard quick-action shortcuts (employee role only — see
// renderDashboard's dashboardQuickActions toggle). Each jumps to the
// relevant page (for its own nav-active state and title) and pre-loads
// just the one piece of cached state its modal actually reads, rather
// than awaiting that page's whole load function (which showPage's own
// dispatch already fires in the background) — avoids a duplicate
// full-page fetch just to guarantee ordering.
async function dashShortcutApplyLeave() {
  showPage('leave-my');
  await loadLeaveTypesCache();
  openLeaveApplyModal();
}

async function dashShortcutSubmitClaim() {
  showPage('payroll-mybenefits');
  const res = await api('/api/benefits/eligible-plans/mine');
  myEligiblePlans = (res && res.ok) ? await res.json() : [];
  openClaimForm();
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Leave Calendar — visible to anyone with Leave-tab access (see
// loadLeaveDash's canViewLeaveDash/hasEmployeeRecord gate below, which
// already controls whether dash-leave itself is reachable). The endpoint
// itself (not this code) decides whether each entry's leave type is
// visible — see routers/leave.py's get_leave_calendar.
// ---------------------------------------------------------------------------
let leaveCalYear = new Date().getFullYear();
let leaveCalMonth = new Date().getMonth() + 1; // 1-12

function leaveCalPrevMonth() {
  leaveCalMonth--;
  if (leaveCalMonth < 1) { leaveCalMonth = 12; leaveCalYear--; }
  loadLeaveCalendar();
}

function leaveCalNextMonth() {
  leaveCalMonth++;
  if (leaveCalMonth > 12) { leaveCalMonth = 1; leaveCalYear++; }
  loadLeaveCalendar();
}

const LEAVE_CAL_MONTH_NAMES = ['January','February','March','April','May','June','July','August','September','October','November','December'];

function loadLeaveCalendar() {
  document.getElementById('leaveCalMonthLabel').textContent = `${LEAVE_CAL_MONTH_NAMES[leaveCalMonth-1]} ${leaveCalYear}`;
  // Document expiry reminders (work permit renewal, passport expiry, etc)
  // are HR-only — skip the fetch entirely for other roles rather than
  // just discarding an unauthorized response; the endpoint also enforces
  // this server-side (routers/employee_documents.py) as defense in depth.
  const canViewDocExpiry = ['hr_manager','hr_admin'].includes(currentUser?.role);
  Promise.all([
    api(`/api/leave/calendar?year=${leaveCalYear}&month=${leaveCalMonth}`),
    api(`/api/holidays?year=${leaveCalYear}`),
    api(`/api/ob/calendar?year=${leaveCalYear}&month=${leaveCalMonth}`),
    canViewDocExpiry ? api(`/api/employee-documents/calendar?year=${leaveCalYear}&month=${leaveCalMonth}`) : Promise.resolve(null),
  ]).then(async ([leaveRes, holidayRes, obRes, docRes]) => {
    const entries = (leaveRes && leaveRes.ok) ? await leaveRes.json() : [];
    const holidays = (holidayRes && holidayRes.ok) ? await holidayRes.json() : [];
    const obItems = (obRes && obRes.ok) ? await obRes.json() : [];
    const docExpiries = (docRes && docRes.ok) ? await docRes.json() : [];
    renderLeaveCalendarGrid(entries, holidays, obItems, docExpiries);
  });
}

function renderLeaveCalendarGrid(entries, holidays, obItems, docExpiries) {
  const grid = document.getElementById('leaveCalGrid');
  const firstDay = new Date(leaveCalYear, leaveCalMonth - 1, 1);
  const daysInMonth = new Date(leaveCalYear, leaveCalMonth, 0).getDate();
  const startOffset = firstDay.getDay(); // 0=Sun

  // Bucket each entry's days into the calendar cells they span. A
  // half-day period only annotates the specific day it applies to — the
  // start day for start_day_period, the end day for end_day_period, never
  // the full days in between — so each day gets its own shallow copy
  // carrying just that day's period (or null for a full day).
  const byDay = {};
  for (const e of entries) {
    const start = new Date(e.start_date + 'T00:00:00');
    const end = new Date(e.end_date + 'T00:00:00');
    for (let d = new Date(Math.max(start, firstDay)); d <= end && d.getMonth() === leaveCalMonth - 1; d.setDate(d.getDate() + 1)) {
      const day = d.getDate();
      const dStr = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
      const dayPeriod = dStr === e.start_date ? e.start_day_period : (dStr === e.end_date ? e.end_day_period : null);
      (byDay[day] = byDay[day] || []).push({ ...e, _dayPeriod: dayPeriod });
    }
  }
  // Public holidays fall on exactly one day each (unlike leave, which can
  // span a range) — bucket by that day's date string directly, no range walk.
  const holidaysByDay = {};
  for (const h of (holidays || [])) {
    const d = new Date(h.date + 'T00:00:00');
    if (d.getFullYear() === leaveCalYear && d.getMonth() === leaveCalMonth - 1) {
      (holidaysByDay[d.getDate()] = holidaysByDay[d.getDate()] || []).push(h);
    }
  }
  // Onboarding/offboarding action items with a due_date — one day each,
  // same bucketing as holidays. due_date is a plain HR-entered wall-clock
  // value (not a UTC *_at timestamp — see routers/onboarding.py), so its
  // date portion is read literally, no parseUTC/timezone conversion.
  const obByDay = {};
  for (const o of (obItems || [])) {
    if (!o.due_date) continue;
    const d = new Date(o.due_date.slice(0, 10) + 'T00:00:00');
    if (d.getFullYear() === leaveCalYear && d.getMonth() === leaveCalMonth - 1) {
      (obByDay[d.getDate()] = obByDay[d.getDate()] || []).push(o);
    }
  }
  // Employee document expiries (work permit renewal, passport expiry,
  // etc) — one day each like holidays, no range walk needed.
  const docExpiryByDay = {};
  for (const de of (docExpiries || [])) {
    const d = new Date(de.expiry_date + 'T00:00:00');
    if (d.getFullYear() === leaveCalYear && d.getMonth() === leaveCalMonth - 1) {
      (docExpiryByDay[d.getDate()] = docExpiryByDay[d.getDate()] || []).push(de);
    }
  }

  const todayStr = new Date().toISOString().slice(0, 10);
  let cells = '';
  for (let i = 0; i < startOffset; i++) cells += `<div></div>`;
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${leaveCalYear}-${String(leaveCalMonth).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    const isToday = dateStr === todayStr;
    const dayHolidays = holidaysByDay[day] || [];
    const isHoliday = dayHolidays.length > 0;
    // Leave entries and action items share one combined +N-more cap, so a
    // busy day doesn't just show whichever type happened to bucket first.
    const dayItems = [
      ...(byDay[day] || []).map(e => ({ kind: 'leave', e })),
      ...(obByDay[day] || []).map(o => ({ kind: 'ob', o })),
      ...(docExpiryByDay[day] || []).map(de => ({ kind: 'docexpiry', de })),
    ];
    const shown = dayItems.slice(0, 3);
    const rest = dayItems.slice(3);
    const holidayChips = dayHolidays.map(h => `
      <div class="text-xs bg-rose-50 text-rose-700 rounded px-1 py-0.5 truncate font-medium" title="${esc(h.name)}">
        ${esc(h.name)}
      </div>`).join('');
    const chipInner = item => {
      if (item.kind === 'leave') return `${esc(displayName(item.e.full_name,item.e.preferred_name))}${item.e.leave_type_name ? ` (${esc(item.e.leave_type_name)})` : ''}${item.e._dayPeriod ? ` (${item.e._dayPeriod})` : ''}`;
      if (item.kind === 'docexpiry') return `⚠️ ${esc(displayName(item.de.full_name,item.de.preferred_name))} — ${esc(item.de.document_type_name)} expires`;
      return `📌 ${esc(item.o.title)} — ${esc(displayName(item.o.employee_name,item.o.employee_preferred_name))}`;
    };
    const chipTitle = item => {
      if (item.kind === 'leave') return `${esc(displayName(item.e.full_name,item.e.preferred_name))}${item.e.leave_type_name ? ' — ' + esc(item.e.leave_type_name) : ''}${item.e._dayPeriod ? ` (${item.e._dayPeriod})` : ''}`;
      if (item.kind === 'docexpiry') return `${esc(displayName(item.de.full_name,item.de.preferred_name))} — ${esc(item.de.document_type_name)} expires ${fmtDate(item.de.expiry_date)}`;
      return `${esc(item.o.title)} — ${esc(displayName(item.o.employee_name,item.o.employee_preferred_name))}`;
    };
    const chipClass = item => {
      if (item.kind === 'leave') return 'bg-amber-50 text-amber-700';
      if (item.kind === 'ob') return 'bg-indigo-50 text-indigo-700';
      // docexpiry — colored by urgency, same status vocabulary as the
      // Employee Detail Documents tab (routers/employee_documents.py's
      // STATUS_CASE_SQL).
      return item.de.status === 'overdue' ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-800';
    };
    const chips = shown.map(item => `
      <div class="text-xs ${chipClass(item)} rounded px-1 py-0.5 truncate" title="${chipTitle(item)}">
        ${chipInner(item)}
      </div>`).join('');
    const extraLabel = rest.length > 0 ? `
      <div class="relative group">
        <div class="text-xs text-slate-400 cursor-default">+${rest.length} more</div>
        <div class="hidden group-hover:block absolute z-10 left-0 top-full mt-1 bg-white border border-slate-200 rounded-lg shadow-lg p-2 min-w-[160px] max-w-[240px] space-y-0.5">
          ${rest.map(item => `<div class="text-xs text-slate-700 truncate">${chipInner(item)}</div>`).join('')}
        </div>
      </div>` : '';
    cells += `
      <div class="min-h-[70px] border rounded-lg p-1 ${isToday ? 'ring-1 ring-blue-400' : ''} ${isHoliday ? 'bg-rose-50/50 border-rose-100' : 'border-slate-100'}">
        <div class="text-xs ${isToday ? 'font-bold text-blue-600' : (isHoliday ? 'font-semibold text-rose-500' : 'text-slate-400')} mb-0.5">${day}</div>
        <div class="space-y-0.5">${holidayChips}${chips}${extraLabel}</div>
      </div>`;
  }
  grid.innerHTML = cells;
}

// Cache of the last-fetched by-type breakdown (always institution-wide,
// unfiltered) so clicking a row can look its id/name back up without a
// round trip, and the currently selected type (if any) the Top/Bottom 10
// rankings below are narrowed to — see loadLeaveUtilDash.
let leaveDashByTypeCache = [];
let leaveDashTypeFilter = null; // { id, name } | null — null means "all types"

function loadLeaveDash() {
  loadLeaveCalendar();
  const canViewLeaveDash = ['hr_manager','hr_admin'].includes(currentUser?.role);
  document.getElementById('leaveUtilDashSection').classList.toggle('hidden', !canViewLeaveDash);
  if (canViewLeaveDash) {
    leaveDashTypeFilter = null;
    loadLeaveUtilDash();
  }

  const hasEmployeeRecord = !!currentUser?.employee_id;
  document.getElementById('myLeaveDashSection').classList.toggle('hidden', !hasEmployeeRecord);
  if (hasEmployeeRecord) loadMyLeaveDash();
}

function loadLeaveUtilDash() {
  const url = '/api/leave/dashboard/utilization' + (leaveDashTypeFilter ? `?leave_type_id=${leaveDashTypeFilter.id}` : '');
  api(url).then(async res => {
    if (!res || !res.ok) return;
    const s = await res.json();
    leaveDashByTypeCache = s.by_type;

    const byTypeEl = document.getElementById('leaveDashByType');
    document.getElementById('leaveDashByTypeEmpty').classList.toggle('hidden', s.by_type.length > 0);
    byTypeEl.innerHTML = s.by_type.map(t => {
      const active = leaveDashTypeFilter?.id === t.leave_type_id;
      return `
      <div class="flex items-center gap-2 cursor-pointer rounded-lg px-1.5 -mx-1.5 py-0.5 transition ${active ? 'bg-blue-50 ring-1 ring-blue-200' : 'hover:bg-slate-50'}" onclick="setLeaveDashTypeFilter(${t.leave_type_id})" title="Click to rank employees by ${esc(t.leave_type_name)}">
        <div class="w-32 text-xs text-slate-600 truncate" title="${esc(t.leave_type_name)}">${esc(t.leave_type_name)}</div>
        <div class="flex-1 bg-slate-100 rounded-full h-2">
          <div class="bg-blue-500 h-2 rounded-full" style="width:${Math.min(100, t.utilization_percent)}%"></div>
        </div>
        <div class="text-xs text-slate-500 w-32 text-right">${t.total_used}/${t.total_entitled} days (${t.utilization_percent}%)</div>
      </div>`;
    }).join('');

    document.getElementById('leaveDashFilterLabel').textContent = leaveDashTypeFilter ? leaveDashTypeFilter.name : 'All Leave Types';
    document.getElementById('leaveDashClearFilter').classList.toggle('hidden', !leaveDashTypeFilter);

    renderLeaveDashRanking('leaveDashTopHighest', s.top_highest, 'bg-red-500');
    renderLeaveDashRanking('leaveDashTopLowest', s.top_lowest, 'bg-emerald-500');
  });
}

function setLeaveDashTypeFilter(leaveTypeId) {
  if (leaveDashTypeFilter?.id === leaveTypeId) {
    leaveDashTypeFilter = null; // clicking the already-active type toggles back to "all"
  } else {
    const t = leaveDashByTypeCache.find(x => x.leave_type_id === leaveTypeId);
    leaveDashTypeFilter = t ? { id: t.leave_type_id, name: t.leave_type_name } : null;
  }
  loadLeaveUtilDash();
}

function clearLeaveDashTypeFilter() {
  leaveDashTypeFilter = null;
  loadLeaveUtilDash();
}

function loadMyLeaveDash() {
  const year = new Date().getFullYear();
  const empId = currentUser.employee_id;

  api(`/api/leave/balances?year=${year}&employee_id=${empId}`).then(async res => {
    const listEl = document.getElementById('myLeaveBalancesList');
    const emptyEl = document.getElementById('myLeaveBalancesEmpty');
    if (!res || !res.ok) { listEl.innerHTML = ''; emptyEl.classList.remove('hidden'); return; }
    const balances = await res.json();
    if (!balances.length) { listEl.innerHTML = ''; emptyEl.classList.remove('hidden'); return; }
    emptyEl.classList.add('hidden');
    listEl.innerHTML = balances.map(b => {
      // accrued_days equals entitled_days for full_year types (no visual
      // difference) and the pro-rated earn-as-you-work figure for monthly
      // accrual types — Balance/Utilization are based on what's actually
      // usable right now (accrued), not the full annual figure.
      const usable = b.accrued_days + b.carried_forward_days;
      const remaining = usable - b.used_days;
      const pct = usable ? Math.round(b.used_days / usable * 100) : 0;
      return `
      <tr class="border-t border-slate-100">
        <td class="py-1.5 text-sm text-slate-700">${esc(b.leave_type_name)}</td>
        <td class="py-1.5 text-sm text-right">${b.entitled_days}</td>
        <td class="py-1.5 text-sm text-right">${b.accrued_days}</td>
        <td class="py-1.5 text-sm text-right">${b.used_days}</td>
        <td class="py-1.5 text-sm text-right font-medium">${remaining}</td>
        <td class="py-1.5 text-sm text-right">${pct}%</td>
      </tr>`;
    }).join('');
  });

  api('/api/leave/applications').then(async res => {
    const listEl = document.getElementById('myLeaveHistoryList');
    const emptyEl = document.getElementById('myLeaveHistoryEmpty');
    if (!res || !res.ok) { listEl.innerHTML = ''; emptyEl.classList.remove('hidden'); return; }
    const apps = (await res.json()).filter(a => a.employee_id === empId);
    if (!apps.length) { listEl.innerHTML = ''; emptyEl.classList.remove('hidden'); return; }
    emptyEl.classList.add('hidden');
    const statusBadge = status => {
      if (status === 'Approved') return 'bg-emerald-100 text-emerald-700';
      if (status === 'Rejected' || status === 'Cancelled') return 'bg-red-100 text-red-700';
      return 'bg-amber-100 text-amber-700';
    };
    listEl.innerHTML = apps.map(a => `
      <tr class="border-t border-slate-100">
        <td class="py-1.5 text-sm text-slate-700">${esc(a.leave_type_name)}</td>
        <td class="py-1.5 text-sm text-slate-600">${fmtDate(a.start_date)} – ${fmtDate(a.end_date)}</td>
        <td class="py-1.5 text-sm text-right">${a.days_count}</td>
        <td class="py-1.5 text-xs text-slate-500">${fmtDate(a.created_at)}</td>
        <td class="py-1.5 text-xs text-slate-500">${fmtDate(a.approved_at)}</td>
        <td class="py-1.5"><span class="badge ${statusBadge(a.status)}">${esc(a.status)}</span></td>
      </tr>`).join('');
  });
}

function renderLeaveDashRanking(containerId, list, barColor) {
  const el = document.getElementById(containerId);
  document.getElementById(containerId + 'Empty').classList.toggle('hidden', list.length > 0);
  el.innerHTML = list.map((e, i) => `
    <div class="flex items-center gap-2">
      <div class="w-5 text-xs text-slate-400 text-right flex-shrink-0">${i + 1}</div>
      <div class="w-28 text-xs text-slate-700 truncate cursor-default leave-emp-name" title="${esc(displayName(e.full_name,e.preferred_name))}"
           data-breakdown='${JSON.stringify({ name: displayName(e.full_name,e.preferred_name), department: e.department, breakdown: e.breakdown }).replace(/'/g,"&apos;")}'>
        ${esc(displayName(e.full_name,e.preferred_name))}
      </div>
      <div class="flex-1 bg-slate-100 rounded-full h-2">
        <div class="${barColor} h-2 rounded-full" style="width:${Math.min(100, e.utilization_percent)}%"></div>
      </div>
      <div class="text-xs text-slate-500 w-28 text-right">${e.total_used}/${e.total_entitled} days (${e.utilization_percent}%)</div>
    </div>`).join('');
}

// Shared floating tooltip for the Leave dashboard's top/bottom lists — shows
// the hovered employee's own leave-type breakdown, since the ranking bar
// only shows their overall utilization.
document.addEventListener('mouseover', e => {
  const target = e.target.closest('.leave-emp-name');
  if (!target) return;
  const data = JSON.parse(target.dataset.breakdown);
  const tooltip = document.getElementById('leaveEmpTooltip');
  const rows = data.breakdown.map(b =>
    `<div class="flex justify-between gap-3"><span>${esc(b.leave_type_name)}</span><span>${b.used_days}/${b.entitled_days}d (${b.utilization_percent}%)</span></div>`
  ).join('') || '<div class="text-slate-300">No leave type balances.</div>';
  tooltip.innerHTML = `<div class="font-semibold mb-1">${esc(data.name)}${data.department ? ` · ${esc(data.department)}` : ''}</div>${rows}`;
  const rect = target.getBoundingClientRect();
  tooltip.style.left = `${rect.left}px`;
  tooltip.style.top = `${rect.bottom + 6}px`;
  tooltip.classList.remove('hidden');
});
document.addEventListener('mouseout', e => {
  if (e.target.closest('.leave-emp-name')) document.getElementById('leaveEmpTooltip').classList.add('hidden');
});

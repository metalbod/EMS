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
    btn.classList.toggle('pill-tab-active', btn.dataset.dashtab === tabId);
    btn.setAttribute('aria-selected', btn.dataset.dashtab === tabId ? 'true' : 'false');
    // Roving tabindex: one tab stop (the selected tab); arrow keys move between tabs.
    btn.setAttribute('tabindex', btn.dataset.dashtab === tabId ? '0' : '-1');
  });
  if (tabId === 'dash-recruitment' && !_dashTabLoaded.recruitment) { _dashTabLoaded.recruitment = true; loadRecruitmentDash(); }
  if (tabId === 'dash-timesheet' && !_dashTabLoaded.timesheet) { _dashTabLoaded.timesheet = true; loadTimesheetDash(); }
  if (tabId === 'dash-compensation' && !_dashTabLoaded.compensation) { _dashTabLoaded.compensation = true; loadCompensationDash(); }
  if (tabId === 'dash-leave' && !_dashTabLoaded.leave) { _dashTabLoaded.leave = true; loadLeaveDash(); }
}

// ARIA tabs keyboard support on the Home tab bar: Left/Right (wrapping), Home
// and End move focus between the visible tabs; Enter/Space (native button
// behaviour) then activates. Activation is manual on purpose — most tabs fetch
// their data on first open, so arrowing past one shouldn't trigger a load.
function dashTabKeydown(e) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  const tabs = [...e.currentTarget.querySelectorAll('[role="tab"]')].filter(t => !t.classList.contains('hidden'));
  const i = tabs.indexOf(document.activeElement);
  if (i < 0) return;
  const next = e.key === 'Home' ? tabs[0]
    : e.key === 'End' ? tabs[tabs.length - 1]
    : tabs[(i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
  e.preventDefault();
  next.focus();
}

function renderDashboard() {
  checkDashboardSystemNotification();
  checkDashboardNotification();
  loadDashboardTodos();
  const isEmployee = currentUser?.role === 'employee';
  document.getElementById('dashboardQuickActions')?.classList.toggle('hidden', !isEmployee);
  if (isEmployee) { refreshResignButtonState(); refreshDashClockState(); }
  renderDashGreeting();
  if (currentUser.role === 'superadmin' && !currentInstitution) {
    document.getElementById('superadminGlobalDash').classList.remove('hidden');
    document.getElementById('instDash').classList.add('hidden');
    document.getElementById('gStatInst').textContent = institutions.length;
    document.getElementById('gStatEmp').textContent = institutions.reduce((a,i)=>a+i.employee_count,0);
    document.getElementById('gStatUser').textContent = institutions.reduce((a,i)=>a+i.user_count,0);
    document.getElementById('gInstList').innerHTML = institutions.map(i=>`
      <div class="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-0">
        <div class="flex items-center gap-3">
          <span class="badge ${i.status==='Active'?'status-positive':'status-negative'}">${i.status}</span>
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
  // Headcount / pending approvals / payroll cut-off / open roles are
  // management-facing figures — the plain "employee" role doesn't get the
  // row at all (hidden explicitly, not just left unrevealed, since
  // renderDashboard also re-runs on a role switch).
  const showMgmtHome = currentUser?.role !== 'employee';
  document.getElementById('dashKpiRow')?.classList.toggle('hidden', !showMgmtHome);
  if (showMgmtHome) loadDashboardKpis();
  if (showMgmtHome) wireDashboardKpiTiles();
  // The Workforce tab (institution-wide headcount/composition stats) is hidden
  // for the plain employee role, so skip its fetch too.
  if (showMgmtHome) loadWorkforceStats();

  // Locations overview (Workforce tab, HR Manager / HR Admin only) — the one
  // section besides base stats that still fetches immediately, since it's
  // grouped into the always-visible Workforce tab rather than a lazy tab.
  const canViewLoc = HR_STAFF_ROLES.includes(currentUser?.role);
  document.getElementById('locDashSection').classList.toggle('hidden', !canViewLoc);
  if (canViewLoc) loadLocationsOverviewDash();

  // Reset per-tab load-once flags and gate tab button visibility for this
  // user/institution context, then always land back on General.
  _dashTabLoaded.recruitment = false;
  _dashTabLoaded.timesheet = false;
  _dashTabLoaded.compensation = false;
  _dashTabLoaded.leave = false;
  const canRecruit = HR_AND_MANAGER_ROLES.includes(currentUser?.role);
  const canViewUtil = HR_MANAGER_ONLY_ROLES.includes(currentUser?.role);
  const canViewBenefitsDash = BENEFITS_DASHBOARD_ROLES.includes(currentUser?.role);
  const hasEmployeeRecord = !!currentUser?.employee_id;
  const canViewLeaveDash = HR_STAFF_ROLES.includes(currentUser?.role);
  document.getElementById('dash-tab-workforce-btn').classList.toggle('hidden', !showMgmtHome);
  document.getElementById('dash-tab-recruitment-btn').classList.toggle('hidden', !canRecruit);
  document.getElementById('dash-tab-timesheet-btn').classList.toggle('hidden', !canViewUtil);
  document.getElementById('dash-tab-compensation-btn').classList.toggle('hidden', !(canViewBenefitsDash || hasEmployeeRecord));
  document.getElementById('dash-tab-leave-btn').classList.toggle('hidden', !(canViewLeaveDash || hasEmployeeRecord));
  switchDashTab('dash-general');
}

// Home KPI Headcount tile + the whole Workforce tab (Total/Active/
// Inactive/Depts, Nationality/Race composition, Department/Employment
// Type breakdown). Backed by GET /api/employees/workforce-stats —
// aggregate counts only, deliberately NOT the role-scoped `employees[]`
// array (list_employees restricts "employee" to their own record and
// "manager" to their reporting chain, to protect individual PII) — every
// role sees the same institution-wide totals here, since a count is never
// an individual record. Independent of loadDashboardKpis' other tiles
// and fails soft (leaves everything at its default "—"/0) rather than
// blocking the rest of the dashboard.
async function loadWorkforceStats() {
  const res = await api('/api/employees/workforce-stats');
  if (!res?.ok) return;
  const s = await res.json();

  const headcountEl = document.getElementById('kpiHeadcount');
  if (headcountEl) headcountEl.textContent = s.active;

  const total = s.total || 1;
  document.getElementById('statTotal').textContent = s.total;
  document.getElementById('statActive').textContent = s.active;
  document.getElementById('statInactive').textContent = s.inactive;
  document.getElementById('statDepts').textContent = s.departments;
  const genderLabel = g => (g.Male || g.Female) ? `${g.Male || 0} Male · ${g.Female || 0} Female` : '—';
  document.getElementById('statTotalGender').textContent = genderLabel(s.total_gender);
  document.getElementById('statActiveGender').textContent = genderLabel(s.active_gender);
  document.getElementById('statInactiveGender').textContent = genderLabel(s.inactive_gender);
  document.getElementById('statActivePct').textContent = `${Math.round(s.active/total*100)}%`;
  document.getElementById('statInactivePct').textContent = `${Math.round(s.inactive/total*100)}%`;

  document.getElementById('statTurnoverRate').textContent = `${s.turnover_rate_12mo}%`;
  document.getElementById('statSeparations').textContent = `${s.separations_12mo} separation(s)`;
  document.getElementById('statResignations').textContent = s.resignations_12mo;
  document.getElementById('statAvgTenure').textContent = `${s.avg_tenure_years}y`;

  const breakdownBar = (containerId, counts, barColor) => {
    const entries = Object.entries(counts).sort((a,b)=>b[1]-a[1]);
    document.getElementById(containerId).innerHTML = entries.map(([label,c])=>`
      <div class="flex items-center gap-2">
        <div class="w-28 text-xs text-slate-600 truncate">${esc(label)}</div>
        <div class="flex-1 bg-slate-100 rounded-full h-2">
          <div class="${barColor} h-2 rounded-full" style="width:${Math.round(c/total*100)}%"></div>
        </div>
        <div class="text-xs text-slate-500 w-5 text-right">${c}</div>
      </div>`).join('') || '<p class="text-slate-400 text-sm">No data.</p>';
  };
  breakdownBar('deptBreakdown', s.dept_breakdown, 'bg-blue-500');
  breakdownBar('empTypeBreakdown', s.employment_type_breakdown, 'bg-violet-500');

  // Workforce Composition — Nationality (Local/Foreigner) and Race, as
  // proportional segmented bars. Nationality is free text in this app (see
  // core/constants.py — there's no NATIONALITIES enum), so "Local" is a
  // nationality==='Malaysian' heuristic, not a validated field; anything
  // else (including typos/inconsistent entries) counts as "Foreigner" —
  // computed server-side now (see get_workforce_stats), same heuristic.
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
  segmentedBar('nationalityBar', 'nationalityLegend', [
    { label:'Local', count:s.local_count, color:'bg-blue-700' },
    { label:'Foreigner', count:s.foreign_count, color:'bg-blue-300' },
  ]);
  const RACE_COLORS = {
    'Malay':'bg-blue-600', 'Chinese':'bg-emerald-500', 'Indian':'bg-amber-500',
    'Bumiputera Sabah':'bg-rose-500', 'Bumiputera Sarawak':'bg-violet-500',
    'Orang Asli':'bg-cyan-500', 'Others':'bg-slate-400',
  };
  segmentedBar('raceBar', 'raceLegend',
    Object.entries(s.race_breakdown).sort((a,b)=>b[1]-a[1])
      .map(([race,count])=>({ label:race, count, color:RACE_COLORS[race]||'bg-slate-400' })));
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
      const avgSeconds = (s.avg_time_in_stage || {})[stage];
      return `<div class="flex items-center gap-2">
        <div class="w-20 text-xs text-slate-600">${stage}</div>
        <div class="flex-1 bg-slate-100 rounded-full h-2">
          <div class="${statusColor(PIPELINE_COLORS, stage, 'bg-slate-400')} h-2 rounded-full" style="width:${Math.round(cnt/totalCands*100)}%"></div>
        </div>
        <div class="text-xs text-slate-500 w-5 text-right">${cnt}</div>
        <div class="text-xs text-slate-400 w-16 text-right">avg ${fmtDuration(avgSeconds)}</div>
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

// Shared by both the project-level bar and each of its task-level bars —
// green means "on track" (at or under estimate), red means over, grey
// means there's no estimate to compare against at all. The right-hand
// text always spells out hours left/over explicitly rather than making
// someone do that subtraction themselves from a bare "logged/estimate"
// pair.
// Approved clocked hours summary (Home > Timesheet tab) — a 6-month
// column chart of total *approved* hours per calendar month, each
// column split into a billable (bottom) / non-billable (top) stack, plus
// a top-10 ranking of employees by missing hours this month. Same
// hand-rolled div-bar visual language as every other dashboard chart
// (breakdownBar/segmentedBar above, the Leave tab's utilization ranking)
// — no charting library anywhere in this app. Columns use fixed pixel
// heights (not nested percentages) so the billable/non-billable split
// renders correctly regardless of the month's share of the tallest bar.
// Fed by GET /api/projects/timesheet-dashboard (routers/projects.py).
const _tsFmtH = n => (Math.round(n * 10) / 10).toString().replace(/\.0$/, '');
const _TS_BAR_MAX_PX = 140;

function _tsMonthColumn(m, maxHours) {
  const barPx = maxHours > 0 ? Math.round(m.total_hours / maxHours * _TS_BAR_MAX_PX) : 0;
  const billablePx = m.total_hours > 0 ? Math.round(m.billable_hours / m.total_hours * barPx) : 0;
  const nonBillablePx = barPx - billablePx;
  return `<div class="flex-1 flex flex-col items-center gap-1.5 min-w-0">
    <div class="text-xs font-medium text-slate-700 whitespace-nowrap">${_tsFmtH(m.total_hours)}h</div>
    <div class="w-full max-w-[3.25rem] flex flex-col-reverse rounded-md overflow-hidden bg-slate-50" style="height:${_TS_BAR_MAX_PX}px">
      <div class="bg-emerald-500" style="height:${billablePx}px"></div>
      <div class="bg-slate-300" style="height:${nonBillablePx}px"></div>
    </div>
    <div class="text-xs text-slate-400 whitespace-nowrap">${esc(m.label)}</div>
  </div>`;
}

function _tsMissingRow(e, maxMissing) {
  const pct = maxMissing > 0 ? Math.round(e.missing_hours / maxMissing * 100) : 0;
  return `<div class="flex items-center gap-2">
    <div class="w-40 text-xs text-slate-600 truncate shrink-0">${esc(displayName(e.full_name, e.preferred_name) || e.employee_id)}</div>
    <div class="flex-1 bg-slate-100 rounded-full h-2">
      <div class="bg-amber-500 h-2 rounded-full" style="width:${pct}%"></div>
    </div>
    <div class="text-xs text-slate-500 shrink-0 whitespace-nowrap">${_tsFmtH(e.missing_hours)}h</div>
  </div>`;
}

function loadTimesheetDash() {
  api('/api/projects/timesheet-dashboard').then(async res => {
    if (!res || !res.ok) return;
    const data = await res.json();

    const chartEl = document.getElementById('tsMonthlyChart');
    const chartEmptyEl = document.getElementById('tsMonthlyEmpty');
    const anyHours = data.months.some(m => m.total_hours > 0);
    chartEmptyEl.classList.toggle('hidden', anyHours);
    const maxHours = Math.max(...data.months.map(m => m.total_hours), 1);
    chartEl.innerHTML = data.months.map(m => _tsMonthColumn(m, maxHours)).join('');

    document.getElementById('tsMissingMonthLabel').textContent = data.missing_hours_month_label;
    const missingListEl = document.getElementById('tsMissingList');
    const missingEmptyEl = document.getElementById('tsMissingEmpty');
    if (!data.missing_hours_top10.length) { missingListEl.innerHTML = ''; missingEmptyEl.classList.remove('hidden'); return; }
    missingEmptyEl.classList.add('hidden');
    const maxMissing = data.missing_hours_top10[0].missing_hours;
    missingListEl.innerHTML = data.missing_hours_top10.map(e => _tsMissingRow(e, maxMissing)).join('');
  });
}

function loadCompensationDash() {
  // Benefits cost & utilization — HR Manager / Compensation Manager / Manager
  const canViewBenefitsDash = BENEFITS_DASHBOARD_ROLES.includes(currentUser?.role);
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
          <td class="py-1.5 text-xs text-slate-600 truncate max-w-36" title="${esc(p.plan_name)}">${esc(p.plan_name)}</td>
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
        if (status === 'Approved') return 'status-info';
        if (status === 'Paid') return 'status-positive';
        if (status === 'Rejected') return 'status-negative';
        return 'status-pending';
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
function renderDashGreeting() {
  const dateEl = document.getElementById('dashGreetingDate');
  const greetEl = document.getElementById('dashGreeting');
  if (!dateEl || !greetEl) return;
  const now = new Date();
  dateEl.textContent = `${now.toLocaleDateString('en-MY',{weekday:'short'})}, ${fmtDate(now)}`;
  const hour = now.getHours();
  const partOfDay = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
  const firstName = (currentUser?.full_name || currentUser?.username || '').split(' ')[0] || 'there';
  greetEl.textContent = `Good ${partOfDay}, ${firstName}`;
}

// Home KPI tiles: headcount (populated by loadWorkforceStats instead — see
// that function — same figure as Workforce tab's statActive), pending
// approvals (from /api/todos — see loadDashboardTodos, which populates
// this tile itself once it has the data, to avoid a second fetch),
// payroll cut-off (computed client-side from the institution's pay_day,
// no new endpoint), open roles (reuses /api/recruitment/dashboard-stats,
// same figure loadRecruitmentDash's rStatOpenReq shows). Each is
// independent and fails soft (leaves the tile at its default "—") rather
// than blocking the others — a role without recruitment access, for
// instance, just doesn't get an Open Roles number.
async function loadDashboardKpis() {
  const inst = currentUser?.role === 'superadmin' ? currentInstitution : currentUser?.institution;
  const cutoffEl = document.getElementById('kpiPayrollCutoff');
  if (cutoffEl) {
    const payDay = inst?.pay_day || 25;
    const now = new Date();
    let next = new Date(now.getFullYear(), now.getMonth(), payDay);
    if (next < now) next = new Date(now.getFullYear(), now.getMonth() + 1, payDay);
    cutoffEl.textContent = next.toLocaleDateString('en-MY', { day: 'numeric', month: 'short' });
    const daysAway = Math.ceil((next - now) / 86400000);
    const deltaEl = document.getElementById('kpiPayrollCutoffDelta');
    if (deltaEl) deltaEl.textContent = daysAway <= 3 ? `${daysAway}d away` : `in ${daysAway} days`;
  }

  api('/api/recruitment/dashboard-stats').then(async res => {
    const openRolesEl = document.getElementById('kpiOpenRoles');
    if (!openRolesEl) return;
    if (!res?.ok) { openRolesEl.textContent = '—'; return; }
    const s = await res.json();
    // Approved = signed off and still hiring; a Draft isn't open yet.
    openRolesEl.textContent = s.req_by_status['Approved'] || 0;
  }).catch(() => {});
}

// Home KPI tiles double as shortcuts: "Pending approvals" jumps to the
// decisions section on this same page; the others open the page their number
// comes from — but only when this role can actually see that page in the
// sidebar (nav items are hidden per role by applyRoleUI in core.js, and a
// collapsed sidebar group is `.hidden` too, so its own #submenu-* wrapper is
// ignored). A tile whose page the role can't open stays plain, not a dead link.
const _KPI_ARROW = '<svg class="kpi-tile-arrow" width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>';

function _canOpenPage(page) {
  const item = document.querySelector(`[data-page="${page}"]`);
  return !!item && !item.closest('.hidden:not([id^="submenu-"])');
}

function _goToDecisions() {
  switchDashTab('dash-general');
  const target = document.getElementById('todo-decisions') || document.querySelector('#dashboardTodoCard h2');
  if (!target) return;
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  target.focus({ preventScroll: true });
}

function wireDashboardKpiTiles() {
  document.querySelectorAll('#dashKpiRow [data-kpi-target]').forEach(tile => {
    const target = tile.dataset.kpiTarget;
    const linkable = target === 'decisions' || _canOpenPage(target);
    tile._kpiGo = linkable ? (target === 'decisions' ? _goToDecisions : () => showPage(target)) : null;
    tile.classList.toggle('kpi-tile-link', linkable);
    tile.querySelector('.kpi-tile-arrow')?.remove();
    if (linkable) {
      tile.setAttribute('role', 'link');
      tile.setAttribute('tabindex', '0');
      tile.setAttribute('title', tile.dataset.kpiTitle || '');
      tile.insertAdjacentHTML('beforeend', _KPI_ARROW);
    } else {
      ['role', 'tabindex', 'title'].forEach(a => tile.removeAttribute(a));
    }
    if (!tile._kpiWired) { // bind once — renderDashboard re-runs on role switch
      tile._kpiWired = true;
      tile.addEventListener('click', () => tile._kpiGo?.());
      tile.addEventListener('keydown', e => { if (e.key === 'Enter' && tile._kpiGo) { e.preventDefault(); tile._kpiGo(); } });
    }
  });
}

const _OVERDUE_ICON = '<svg class="todo-overdue-icon" width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>';
const _CHEVRON_ICON = '<svg class="todo-chevron" width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>';

function _plural(n, word) { return `${n} ${word}${n === 1 ? '' : 's'}`; }

// The server builds some stage strings with raw ISO dates ("Annual Leave:
// 2026-10-05 to 2026-10-09") and a leading type ("Resignation — last day …")
// that the Type column already says. Show every date the way the rest of Home
// does (fmtDate) and drop the redundant type prefix.
function _fmtIsoDates(text) {
  return String(text ?? '').replace(/\b\d{4}-\d{2}-\d{2}\b/g, d => fmtDate(d));
}
function _todoStageText(t) {
  let s = String(t.stage || t.label || '');
  const prefix = t.stage_type ? `${t.stage_type} — ` : '';
  if (prefix && s.startsWith(prefix) && s.length > prefix.length) {
    s = s.slice(prefix.length);
    s = s.charAt(0).toUpperCase() + s.slice(1);
  }
  return _fmtIsoDates(s);
}

// A "dash-" page value is a Dashboard sub-tab (e.g. "dash-leave" for the
// monthly calendar), not a top-level page — showPage() alone lands on the
// Dashboard's default tab, so it needs switchDashTab() too. No top-level
// ALL_PAGES entry starts with "dash-", so this prefix check is unambiguous.
//
// `focus` (the item's focus_id from /api/todos) deep-links to that exact
// record — the destination opens it or highlights its row (deep-link.js).
function _todoNav(page, focus) {
  if (page.startsWith('dash-')) return `showPage('dashboard');switchDashTab('${page}')`;
  const id = focus == null || focus === '' ? NaN : Number(focus);
  return Number.isInteger(id) ? `showPage('${page}',{focus:${id}})` : `showPage('${page}')`;
}

// The timing cell says what its date means in words, never by colour alone:
// a real deadline that has passed reads "Overdue 3 days" (with an icon), an
// upcoming deadline shows the date, and an approval with no deadline of its
// own reads "Waiting 17 days" (from submission — see routers/dashboard.py).
// The exact date behind a relative phrase is in a title (mouse hover) and in
// screen-reader-only text — a title alone is unreachable by keyboard and touch.
function _todoTimingHtml(t) {
  if (t.days_overdue) {
    const due = esc(fmtDate(t.due_date));
    return `<span class="todo-timing todo-overdue" title="Due ${due}">${_OVERDUE_ICON}Overdue ${_plural(t.days_overdue, 'day')}<span class="sr-only-text">, due ${due}</span></span>`;
  }
  if (t.due_date) return `<span>Due ${esc(fmtDate(t.due_date))}</span>`;
  if (t.kind === 'approval' && t.days_waiting != null) {
    const since = esc(fmtDate(t.waiting_since));
    const label = t.days_waiting === 0 ? 'Submitted today' : `Waiting ${_plural(t.days_waiting, 'day')}`;
    return `<span class="todo-timing" title="Submitted ${since}">${label}<span class="sr-only-text">, submitted ${since}</span></span>`;
  }
  return '—';
}

// Every to-do gets a real, focusable control (a <tr onclick> is invisible to
// keyboards and screen readers). Only the single highlighted item gets the
// filled treatment; everything else is outline.
function _todoButtonHtml(verb, nav, isUrgent, ariaLabel) {
  const cls = isUrgent ? 'todo-action todo-action-primary' : 'todo-action pill-btn-outline';
  return `<button type="button" onclick="event.stopPropagation();${nav}" class="pill-btn ${cls}" aria-label="${esc(ariaLabel)}">${verb}</button>`;
}

// "Needs your decision": a request waiting on this user. The Task column
// shows only the stage — the employee and type already have their own
// columns, so repeating them in a label ("… — Yahya (offboarding)") made the
// widest column the least informative one.
function _todoApprovalsHtml(rows, urgent) {
  const body = rows.map(t => {
    const isUrgent = t === urgent;
    const nav = _todoNav(t.page, t.focus_id);
    // Leave and L&D can be decided right here (todo-decisions.js); those rows
    // are not click-through, so an accidental click can't lose a half-typed
    // reject reason. Everything else stays a click-through "Review".
    const inline = todoDecisionSupported(t);
    return `
    <tr role="row" class="${inline ? '' : 'cursor-pointer '}${isUrgent ? 'todo-row-urgent' : 'hover:bg-slate-50'}"${inline ? '' : ` onclick="${nav}"`}>
      <td role="cell" class="px-4 py-3 font-medium text-slate-800 todo-cell-wrap">${esc(_todoStageText(t))}</td>
      <td role="cell" class="px-4 py-3 text-slate-600"><span class="todo-cell-clip" title="${esc(t.employee_name || '')}">${esc(t.employee_name || '—')}</span></td>
      <td role="cell" class="px-4 py-3 text-slate-600 whitespace-nowrap">${esc(t.stage_type || '—')}</td>
      <td role="cell" class="px-4 py-3 text-slate-600 whitespace-nowrap">${_todoTimingHtml(t)}</td>
      <td role="cell" class="px-4 py-3 text-right whitespace-nowrap">${inline
        ? _todoDecisionActionsHtml(t, isUrgent)
        : _todoButtonHtml('Review', nav, isUrgent, `Review ${t.stage_type || 'request'} — ${t.employee_name || 'unknown employee'}: ${_todoStageText(t)}`)}</td>
    </tr>${inline ? _todoDecisionPanelHtml(t) : ''}`;
  }).join('');
  return `<section class="todo-section">
    <h3 class="todo-subheading" id="todo-decisions" tabindex="-1">Needs your decision</h3>
    <div class="todo-block todo-scroll-x">
      <table role="table" class="w-full text-sm" aria-label="Needs your decision">
        <thead role="rowgroup"><tr role="row">
          <th scope="col" role="columnheader" class="text-left px-4 text-xs font-semibold uppercase todo-th">Request</th>
          <th scope="col" role="columnheader" class="text-left px-4 text-xs font-semibold uppercase todo-th">Employee</th>
          <th scope="col" role="columnheader" class="text-left px-4 text-xs font-semibold uppercase todo-th">Type</th>
          <th scope="col" role="columnheader" class="text-left px-4 text-xs font-semibold uppercase todo-th">Timing</th>
          <th scope="col" role="columnheader" class="px-4 todo-th"><span class="sr-only-text">Action</span></th>
        </tr></thead>
        <tbody role="rowgroup" class="divide-y divide-slate-100">${body}</tbody>
      </table>
    </div>
  </section>`;
}

// Checklist items grouped per person's checklist: six "Exit Interview /
// Reference — Yahya" rows for three people become three rows, each stating
// how much of it is left and (offboarding) when the person leaves. The
// person furthest past a deadline, then the one leaving soonest, comes first.
function _todoGroups(tasks) {
  const byKey = new Map();
  for (const t of tasks) {
    const k = t.checklist_id != null ? `c${t.checklist_id}` : `k${t.key}`;
    if (!byKey.has(k)) {
      byKey.set(k, { id: k, checklist_id: t.checklist_id, employee_id: t.employee_id, name: t.employee_name, type: t.stage_type, page: t.page,
        open: t.checklist_open, total: t.checklist_total, event_date: t.event_date, days_until_event: t.days_until_event,
        items: [], overdue: 0, maxOverdue: 0, minDue: null });
    }
    const g = byKey.get(k);
    g.items.push(t);
    if (t.days_overdue) { g.overdue++; g.maxOverdue = Math.max(g.maxOverdue, t.days_overdue); }
    if (t.due_date && (g.minDue === null || t.due_date < g.minDue)) g.minDue = t.due_date;
  }
  const nullsLast = (a, b) => (a === b ? 0 : a === null ? 1 : b === null ? -1 : a < b ? -1 : 1);
  return [...byKey.values()].sort((a, b) =>
    b.maxOverdue - a.maxOverdue
    || nullsLast(a.event_date || null, b.event_date || null)
    || nullsLast(a.minDue, b.minDue));
}

const _todoOpenGroups = new Set(); // group ids left expanded, so a refresh doesn't collapse them

function toggleTodoGroup(btn) {
  const open = btn.getAttribute('aria-expanded') !== 'true';
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  const panel = document.getElementById(btn.getAttribute('aria-controls'));
  if (panel) panel.hidden = !open;
  const id = btn.dataset.group;
  if (open) _todoOpenGroups.add(id); else _todoOpenGroups.delete(id);
}

function _todoGroupHtml(g, isUrgent) {
  const mine = g.employee_id && g.employee_id === currentUser?.employee_id;
  const typeLower = String(g.type || 'checklist').toLowerCase();
  const title = mine ? `Your ${typeLower}` : (g.name || 'Unknown');
  const parts = [];
  if (!mine) parts.push(esc(g.type || ''));
  // Two different scopes, named as such: items assigned to *this user* vs how
  // much of the whole checklist (every role's tasks) is still open.
  parts.push(`${g.items.length} assigned to you`);
  if (g.total) parts.push(`${g.open} of ${g.total} open`);
  let when = '';
  if (g.event_date) {
    const d = g.days_until_event;
    when = d != null && d < 0 ? `Left ${esc(fmtDate(g.event_date))}`
      : `Leaves ${esc(fmtDate(g.event_date))}${d != null ? ` · ${d === 0 ? 'today' : `in ${_plural(d, 'day')}`}` : ''}`;
  }
  const panelId = `todo-group-${g.id}`;
  const open = _todoOpenGroups.has(g.id);
  // An item with no due date shows nothing on the right, not a "—".
  const items = g.items.map(t => {
    const timing = _todoTimingHtml(t);
    return `<li><span>${esc(_todoStageText(t))}</span>${timing === '—' ? '' : `<span class="todo-item-timing">${timing}</span>`}</li>`;
  }).join('');
  return `<li class="todo-group ${isUrgent ? 'todo-row-urgent' : ''}">
    <div class="todo-group-head">
      <button type="button" class="todo-group-toggle" data-group="${g.id}" aria-expanded="${open}" aria-controls="${panelId}" onclick="toggleTodoGroup(this)">
        <span class="todo-group-title">${_CHEVRON_ICON}<span class="todo-group-name">${esc(title)}</span></span>
        <span class="todo-group-meta">${parts.filter(Boolean).join(' · ')}</span>
        ${when ? `<span class="todo-group-meta">${when}</span>` : ''}
        ${g.overdue ? `<span class="todo-overdue">${_OVERDUE_ICON}${g.overdue} overdue</span>` : ''}
      </button>
      ${_todoButtonHtml('Open', _todoNav(g.page, g.checklist_id), isUrgent, `Open ${mine ? `your ${typeLower}` : `${g.name || ''}'s ${typeLower}`} checklist`)}
    </div>
    <ul class="todo-group-items" id="${panelId}" ${open ? '' : 'hidden'}>${items}</ul>
  </li>`;
}

function _todoTasksHtml(groups, urgent) {
  return `<section class="todo-section">
    <h3 class="todo-subheading">Checklist tasks</h3>
    <div class="todo-block"><ul class="todo-groups">${groups.map(g => _todoGroupHtml(g, g === urgent)).join('')}</ul></div>
  </section>`;
}

// Aggregate rows ("3 training courses in progress"): no single employee or
// date to show, so just the sentence and a way in.
function _todoRemindersHtml(rows, urgent) {
  const lis = rows.map(t => {
    const verb = t.action_label || 'Open';
    return `<li>
      <span>${esc(t.label)}</span>
      ${_todoButtonHtml(verb, _todoNav(t.page), t === urgent, `${verb}: ${t.label}`)}
    </li>`;
  }).join('');
  return `<section class="todo-section">
    <h3 class="todo-subheading">Reminders</h3>
    <div class="todo-block"><ul class="todo-reminders">${lis}</ul></div>
  </section>`;
}

// Exactly one highlighted item across the whole card ("Only one row is
// highlighted at a time" in the redesign brief). Whatever is furthest past a
// real deadline wins — a leave request that has already started, or a
// checklist item that is days late — with an approval winning a tie; if
// nothing is late it is the first approval (the server orders those
// longest-waiting first), else the top checklist group, else the first
// reminder. The filled button is the page's one instruction, so it must not
// point at a merely-waiting request while something is overdue.
function _pickUrgent(approvals, groups, reminders) {
  const late = [...approvals, ...groups.flatMap(g => g.items)].filter(t => t.days_overdue);
  if (late.length) {
    return late.reduce((best, t) => (t.days_overdue > best.days_overdue ? t : best));
  }
  return approvals[0] || groups[0]?.items[0] || reminders[0] || null;
}

// Approvals first, then per-person checklist groups, then reminders.
function _todoBodyHtml(items) {
  const approvals = items.filter(t => t.kind === 'approval');
  const groups = _todoGroups(items.filter(t => t.kind === 'task'));
  const reminders = items.filter(t => t.kind === 'reminder');
  const urgent = _pickUrgent(approvals, groups, reminders);
  return [
    approvals.length ? _todoApprovalsHtml(approvals, urgent) : '',
    groups.length ? _todoTasksHtml(groups, groups.find(g => g.items.includes(urgent)) || null) : '',
    reminders.length ? _todoRemindersHtml(reminders, urgent) : '',
  ].join('');
}

const _TODO_SKELETON = '<div class="todo-block todo-skeleton-block" aria-hidden="true">' + '<span class="todo-skeleton"></span>'.repeat(3) + '</div>';

// Which of the card's four mutually exclusive states is showing:
// 'loading' (skeleton, only when there is nothing to show yet), 'error'
// (message + retry), 'empty' ("all caught up") or 'list'.
function _setTodoView(view, errorMsg) {
  const body = document.getElementById('dashboardTodoBody');
  const empty = document.getElementById('dashboardTodoEmpty');
  const error = document.getElementById('dashboardTodoError');
  body?.classList.toggle('hidden', view !== 'list' && view !== 'loading');
  body?.setAttribute('aria-busy', view === 'loading' ? 'true' : 'false');
  empty?.classList.toggle('hidden', view !== 'empty');
  error?.classList.toggle('hidden', view !== 'error');
  if (view === 'error') {
    const msg = document.getElementById('dashboardTodoErrorMsg');
    if (msg) msg.textContent = errorMsg || "Couldn't load your to-do list.";
  }
}

let _todoLoadSeq = 0;
let _todoItems = []; // the last successfully loaded /api/todos list
let _todoResultPending = ''; // outcome of a just-made decision, spoken with the refreshed list (todo-decisions.js)

// Re-renders the card body from the cache (used after a local state change such
// as opening a reject reason) and optionally puts focus back on a selector.
function _renderTodos(focusSelector) {
  const bodyEl = document.getElementById('dashboardTodoBody');
  if (!bodyEl) return;
  bodyEl.innerHTML = _todoBodyHtml(_todoItems);
  if (focusSelector) document.querySelector(focusSelector)?.focus();
}

async function loadDashboardTodos() {
  const card=document.getElementById('dashboardTodoCard');
  if(!card) return;
  if(currentUser?.role==='superadmin'){ card.classList.add('hidden'); return; }
  card.classList.remove('hidden');
  const bodyEl=document.getElementById('dashboardTodoBody');
  const countEl=document.getElementById('dashboardTodoCount');
  const retryBtn=document.getElementById('dashboardTodoRetry');
  const liveEl=document.getElementById('dashboardTodoLive');
  const approvalsEl = document.getElementById('kpiApprovals');
  // Only a later call may overwrite the screen: if the user switches role/
  // institution or hits Retry while a slower request is still in flight, the
  // stale response is dropped instead of clobbering the newer one.
  const seq = ++_todoLoadSeq;
  if (retryBtn) retryBtn.disabled = true;
  if (!bodyEl.children.length) { bodyEl.innerHTML = _TODO_SKELETON; _setTodoView('loading'); }

  let items = null, errorMsg = null;
  try {
    const res = await api('/api/todos');
    if (seq !== _todoLoadSeq) return;
    if (!res) return; // 401: api() has already started the logout flow
    if (res.ok) {
      const body = await res.json();
      if (!Array.isArray(body)) throw new Error('unexpected /api/todos response');
      items = body;
    } else if (res.status === 403) {
      errorMsg = "You don't have access to your to-do list.";
    } else {
      errorMsg = "Couldn't load your to-do list — something went wrong on our side.";
    }
  } catch (e) {
    if (seq !== _todoLoadSeq) return;
    errorMsg = "Couldn't load your to-do list. Check your connection and try again.";
  }
  if (retryBtn) retryBtn.disabled = false;

  // A failed load must never read as "nothing pending": show the error and
  // leave the approvals tile at "—" rather than a confident 0.
  if (items === null) {
    bodyEl.innerHTML = '';
    if (countEl) countEl.textContent = '';
    if (approvalsEl) approvalsEl.textContent = '—';
    _setTodoView('error', errorMsg);
    if (liveEl) liveEl.textContent = '';
    return;
  }

  if (approvalsEl) approvalsEl.textContent = items.filter(t => t.kind === 'approval').length;

  if (countEl) countEl.textContent = items.length ? _plural(items.length, 'item') : '';
  // Announce the result through a persistent live region: un-hiding the
  // empty-state paragraph or the list isn't reliably read out by screen readers.
  const deciding = items.filter(t => t.kind === 'approval').length;
  _todoItems = items;
  // Forget inline-decision state for requests that are no longer in the list
  // (including when the list has just become empty).
  for (const key of [..._todoDecisionUi.keys()]) if (!items.some(t => t.key === key)) _todoDecisionUi.delete(key);
  // A decision just made from this card is spoken first, then the new state of
  // the list — otherwise the refresh would overwrite "Approved …" before a
  // screen reader gets to it.
  const outcome = _todoResultPending ? `${_todoResultPending} ` : '';
  _todoResultPending = '';
  if(!items.length){
    bodyEl.innerHTML='';
    _setTodoView('empty');
    if (liveEl) liveEl.textContent = `${outcome}You're all caught up — nothing pending right now.`;
    return;
  }
  bodyEl.innerHTML = _todoBodyHtml(items);
  _setTodoView('list');
  if (liveEl) liveEl.textContent = `${outcome}${_plural(items.length, 'item')} on your to-do list${deciding ? `, ${deciding} waiting for your decision` : ''}.`;
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

// Clock In/Out shortcut — unlike the two above, this acts immediately in
// place rather than navigating to a page + opening a modal, so it's a
// lightweight standalone version of attendanceClockIn/Out (static/js/
// attendance.js, the page-attendance-clock page) rather than a reuse of
// those functions directly: those read/write DOM elements (geo note,
// history table) that only exist on that page, not Home. attCaptureGeo()
// itself has no such dependency, so it's shared as-is.
async function refreshDashClockState() {
  const btn = document.getElementById('dashClockBtn');
  if (!btn || !currentUser?.employee_id) return;
  const res = await api('/api/attendance/mine?limit=1');
  const rows = (res && res.ok) ? await res.json() : [];
  const open = rows[0] && rows[0].clock_in_at && !rows[0].clock_out_at;
  btn.textContent = open ? 'Clock Out' : 'Clock In';
  btn.setAttribute('onclick', open ? 'dashShortcutClockOut()' : 'dashShortcutClockIn()');
}

const dashShortcutClockIn = guardAsync(async function dashShortcutClockIn() {
  const geo = await attCaptureGeo();
  const res = await api('/api/attendance/clock-in', {
    method: 'POST',
    body: JSON.stringify({ lat: geo?.lat ?? null, lng: geo?.lng ?? null }),
  });
  if (!res || !res.ok) { const d = await res?.json().catch(() => ({})); alert(d?.detail || 'Failed to clock in'); return; }
  await refreshDashClockState();
});

const dashShortcutClockOut = guardAsync(async function dashShortcutClockOut() {
  const geo = await attCaptureGeo();
  const res = await api('/api/attendance/clock-out', {
    method: 'POST',
    body: JSON.stringify({ lat: geo?.lat ?? null, lng: geo?.lng ?? null }),
  });
  if (!res || !res.ok) { const d = await res?.json().catch(() => ({})); alert(d?.detail || 'Failed to clock out'); return; }
  await refreshDashClockState();
});

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
  const canViewDocExpiry = HR_STAFF_ROLES.includes(currentUser?.role);
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

// Full per-day breakdown for the click-to-expand day modal (openLeaveDayDetail)
// — keyed by day-of-month for the currently rendered leaveCalYear/leaveCalMonth,
// rebuilt on every renderLeaveCalendarGrid call. Holds the *un-capped* lists
// (the grid itself only shows the first 3 chips + "N more").
let leaveCalDayDetail = {};

function renderLeaveCalendarGrid(entries, holidays, obItems, docExpiries) {
  leaveCalDayDetail = {};
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
      <div class="text-xs bg-rose-50 text-rose-700 rounded-sm px-1 py-0.5 truncate font-medium" title="${esc(h.name)}">
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
      <div class="text-xs ${chipClass(item)} rounded-sm px-1 py-0.5 truncate" title="${chipTitle(item)}">
        ${chipInner(item)}
      </div>`).join('');
    const extraLabel = rest.length > 0 ? `<div class="text-xs text-slate-400">+${rest.length} more</div>` : '';
    const hasAnything = dayItems.length > 0 || dayHolidays.length > 0;
    if (hasAnything) leaveCalDayDetail[day] = { dateStr, dayHolidays, dayItems };
    cells += `
      <div class="min-h-[70px] border rounded-lg p-1 ${isToday ? 'ring-1 ring-blue-400' : ''} ${isHoliday ? 'bg-rose-50/50 border-rose-100' : 'border-slate-100'} ${hasAnything ? 'cursor-pointer hover:border-blue-300 hover:shadow-sm' : ''}"
           ${hasAnything ? `onclick="openLeaveDayDetail(${day})"` : ''}>
        <div class="text-xs ${isToday ? 'font-bold text-blue-600' : (isHoliday ? 'font-semibold text-rose-500' : 'text-slate-400')} mb-0.5">${day}</div>
        <div class="space-y-0.5">${holidayChips}${chips}${extraLabel}</div>
      </div>`;
  }
  grid.innerHTML = cells;
}

// Day-detail modal — the grid cell only ever shows 3 chips before
// collapsing into "+N more" (a hover tooltip doesn't work on touch
// screens, and even on desktop a cramped tooltip isn't meaningful once a
// day has many rows) — clicking the day instead opens every row: leave,
// holiday, onboarding/offboarding action items and document expiries.
function openLeaveDayDetail(day) {
  const d = leaveCalDayDetail[day];
  if (!d) return;
  const dateObj = new Date(d.dateStr + 'T00:00:00');
  document.getElementById('leaveDayDetailTitle').textContent =
    dateObj.toLocaleDateString('en-MY', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

  const section = (label, rowsHtml) => rowsHtml ? `
    <div>
      <h4 class="text-xs font-semibold text-slate-400 uppercase mb-1.5">${label}</h4>
      <div class="space-y-1.5">${rowsHtml}</div>
    </div>` : '';

  const holidayRows = d.dayHolidays.map(h => `
    <div class="text-sm bg-rose-50 text-rose-700 rounded-lg px-3 py-2 font-medium">${esc(h.name)}</div>`).join('');

  const leaveItems = d.dayItems.filter(i => i.kind === 'leave');
  const leaveRows = leaveItems.map(item => `
    <div class="flex items-center justify-between bg-amber-50 rounded-lg px-3 py-2">
      <span class="text-sm text-amber-800">${esc(displayName(item.e.full_name, item.e.preferred_name))}</span>
      <span class="text-xs text-amber-700">${item.e.leave_type_name ? esc(item.e.leave_type_name) : 'On leave'}${item.e._dayPeriod ? ` · ${item.e._dayPeriod}` : ''}</span>
    </div>`).join('');

  const obRowItems = d.dayItems.filter(i => i.kind === 'ob');
  const obRows = obRowItems.map(item => `
    <div class="flex items-center justify-between bg-indigo-50 rounded-lg px-3 py-2">
      <span class="text-sm text-indigo-800">📌 ${esc(item.o.title)}</span>
      <span class="text-xs text-indigo-700">${esc(displayName(item.o.employee_name, item.o.employee_preferred_name))}</span>
    </div>`).join('');

  const docItems = d.dayItems.filter(i => i.kind === 'docexpiry');
  const docRows = docItems.map(item => `
    <div class="flex items-center justify-between ${item.de.status === 'overdue' ? 'bg-red-50' : 'bg-amber-50'} rounded-lg px-3 py-2">
      <span class="text-sm ${item.de.status === 'overdue' ? 'text-red-800' : 'text-amber-800'}">⚠️ ${esc(displayName(item.de.full_name, item.de.preferred_name))}</span>
      <span class="text-xs ${item.de.status === 'overdue' ? 'text-red-700' : 'text-amber-700'}">${esc(item.de.document_type_name)} expires ${fmtDate(item.de.expiry_date)}</span>
    </div>`).join('');

  document.getElementById('leaveDayDetailBody').innerHTML =
    section('Public Holiday', holidayRows) +
    section(`On Leave (${leaveItems.length})`, leaveRows) +
    section('Onboarding / Offboarding', obRows) +
    section('Document Expiring', docRows) ||
    '<p class="text-slate-400 text-sm">Nothing scheduled.</p>';

  document.getElementById('leaveDayDetailModal').classList.remove('hidden');
}

function closeLeaveDayDetail() { closeModal('leaveDayDetailModal'); }

// Cache of the last-fetched by-type breakdown (always institution-wide,
// unfiltered) so clicking a row can look its id/name back up without a
// round trip, and the currently selected type (if any) the Top/Bottom 10
// rankings below are narrowed to — see loadLeaveUtilDash.
let leaveDashByTypeCache = [];
let leaveDashTypeFilter = null; // { id, name } | null — null means "all types"

function loadLeaveDash() {
  loadLeaveCalendar();
  const canViewLeaveDash = HR_STAFF_ROLES.includes(currentUser?.role);
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
      if (status === 'Approved') return 'status-positive';
      if (status === 'Rejected' || status === 'Cancelled') return 'status-negative';
      return 'status-pending';
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
      <div class="w-5 text-xs text-slate-400 text-right shrink-0">${i + 1}</div>
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

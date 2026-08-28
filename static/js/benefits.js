// ============================================================================
// BENEFITS: PLAN TYPES (benefit plan catalog)
// ============================================================================

let benefitPlans = [];
const benefitPlansList = createListState({ sortKey: 'plan_name' });

async function loadBenefitPlans() {
  const res = await api('/api/benefits/plans');
  if (!res || !res.ok) return;
  benefitPlans = await res.json();
  benefitPlansList.resetPage();
  renderBenefitPlansTable();
}

function setBenefitPlansSort(key) { benefitPlansList.setSort(key); renderBenefitPlansTable(); }
function setBenefitPlansPageSize(size) { benefitPlansList.setPageSize(size); renderBenefitPlansTable(); }
function benefitPlansPagePrev() { benefitPlansList.prevPage(); renderBenefitPlansTable(); }
function benefitPlansPageNext() { benefitPlansList.nextPage(benefitPlans.length); renderBenefitPlansTable(); }

function renderBenefitPlansTable() {
  const tbody = document.getElementById('benefitPlansTableBody');
  if (!tbody) return;
  document.getElementById('benefitPlansEmptyState')?.classList.toggle('hidden', benefitPlans.length > 0);
  benefitPlansList.updateSortArrows('.benefit-plans-sort-arrow');

  const pagination = document.getElementById('benefitPlansPagination');
  if (!benefitPlans.length) { pagination?.classList.add('hidden'); tbody.innerHTML = ''; return; }
  pagination?.classList.remove('hidden');
  const pageSizeEl = document.getElementById('benefitPlansPageSize');
  if (pageSizeEl) pageSizeEl.value = String(benefitPlansList.pageSize);

  const { pageItems, start, total } = benefitPlansList.view(benefitPlans);
  const pageInfoEl = document.getElementById('benefitPlansPageInfo');
  if (pageInfoEl) pageInfoEl.textContent = `${start + 1}-${Math.min(start + benefitPlansList.pageSize, total)} of ${total}`;

  const statusBadge = status => {
    if (status === 'Active') return 'bg-blue-100 text-blue-700';
    if (status === 'Closed') return 'bg-slate-100 text-slate-500';
    return 'bg-amber-100 text-amber-700';
  };
  const categoryBadge = 'bg-purple-100 text-purple-700';

  const fmtCost = (v, type) => {
    if (v == null) return '—';
    if (type === 'Percent of Salary') return `${Number(v)}%`;
    return fmtCurrency(v);
  };

  tbody.innerHTML = pageItems.map(p => `
    <tr class="hover:bg-slate-50 transition cursor-pointer" onclick="openBenefitPlanForm(${p.id})">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(p.plan_name)}</p>
        ${p.plan_year ? `<p class="text-xs text-slate-500">${p.plan_year}</p>` : ''}
        ${p.carrier_name ? `<p class="text-xs text-slate-400">${esc(p.carrier_name)}${p.payroll_sync_enabled ? ' · payroll sync on' : ''}</p>` : ''}
      </td>
      <td class="px-4 py-3"><span class="badge ${categoryBadge}">${esc(p.plan_category)}</span></td>
      <td class="px-4 py-3 text-xs text-slate-500">${esc(p.contribution_type)}</td>
      <td class="px-4 py-3 text-right">${fmtCost(p.employee_cost, p.contribution_type)}</td>
      <td class="px-4 py-3 text-right">${fmtCost(p.employer_cost, p.contribution_type)}</td>
      <td class="px-4 py-3 text-center">
        <span class="badge ${statusBadge(p.status)}">${esc(p.status)}</span>
      </td>
    </tr>
  `).join('');
}

let currentBenefitPlanId = null;

function openBenefitPlanForm(planId) {
  document.getElementById('benefitPlanForm').reset();
  document.getElementById('benPlanId').value = '';
  document.getElementById('benPlanStatusRow').classList.add('hidden');
  document.getElementById('benPlanEligibilitySection').classList.add('hidden');
  document.getElementById('benPlanAutoEnrollSection').classList.add('hidden');
  currentBenefitPlanId = null;

  const plan = planId ? benefitPlans.find(p => p.id === planId) : null;
  if (plan) {
    document.getElementById('benefitPlanModalTitle').textContent = 'Edit Benefit Plan';
    document.getElementById('benPlanId').value = plan.id;
    document.getElementById('benPlanName').value = plan.plan_name;
    document.getElementById('benPlanCategory').value = plan.plan_category;
    document.getElementById('benPlanContributionType').value = plan.contribution_type;
    document.getElementById('benPlanEmployeeCost').value = plan.employee_cost ?? '';
    document.getElementById('benPlanEmployerCost').value = plan.employer_cost ?? '';
    document.getElementById('benPlanYear').value = plan.plan_year ?? '';
    document.getElementById('benPlanEffectiveDate').value = plan.effective_date ?? '';
    document.getElementById('benPlanEndDate').value = plan.end_date ?? '';
    document.getElementById('benPlanDesc').value = plan.description ?? '';
    document.getElementById('benPlanCarrierName').value = plan.carrier_name ?? '';
    document.getElementById('benPlanCarrierPolicy').value = plan.carrier_group_policy_number ?? '';
    document.getElementById('benPlanPayrollSync').checked = !!plan.payroll_sync_enabled;
    document.getElementById('benPlanStatus').value = plan.status;
    document.getElementById('benPlanStatusRow').classList.remove('hidden');
    // Category/contribution type describe the plan's identity, not
    // something you flip after enrollment could reference it — editable
    // only at creation, matching PayGradeUpdate's precedent of only
    // exposing fields that are actually safe to change post-creation.
    document.getElementById('benPlanCategory').disabled = true;
    document.getElementById('benPlanContributionType').disabled = true;

    currentBenefitPlanId = plan.id;
    document.getElementById('benPlanEligibilitySection').classList.remove('hidden');
    initEligibilityEditor(plan.id);
    // Auto-enroll only makes sense once the plan is actually Active — a
    // Draft/Closed plan has no eligible enrollment to bulk-create against.
    document.getElementById('benPlanAutoEnrollSection').classList.toggle('hidden', plan.status !== 'Active');
  } else {
    document.getElementById('benefitPlanModalTitle').textContent = 'New Benefit Plan';
    document.getElementById('benPlanCategory').disabled = false;
    document.getElementById('benPlanContributionType').disabled = false;
  }

  document.getElementById('benefitPlanModal').classList.remove('hidden');
}

async function autoEnrollAllActiveEmployees() {
  if (!currentBenefitPlanId) return;
  if (!confirm('Enroll every active employee into this plan now? Employees already enrolled will be left as-is.')) return;
  const res = await api(`/api/benefits/plans/${currentBenefitPlanId}/auto-enroll-all`, { method: 'POST' });
  if (!res || !res.ok) { alert('Error: ' + (await res.json().catch(()=>({}))).detail || 'Failed to auto-enroll'); return; }
  const data = await res.json();
  alert(`Enrolled ${data.enrolled_count} active employee(s).`);
}

async function initEligibilityEditor(planId) {
  if (!jobLevels || jobLevels.length === 0) await loadJobLevels();
  if (!payGrades || payGrades.length === 0) await loadPayGrades();

  const levelSelect = document.getElementById('benEligJobLevel');
  levelSelect.innerHTML = '<option value="">—</option>' +
    jobLevels.map(l => `<option value="${l.id}">${esc(l.level_name)}</option>`).join('');
  const gradeSelect = document.getElementById('benEligPayGrade');
  gradeSelect.innerHTML = '<option value="">—</option>' +
    payGrades.map(g => `<option value="${g.id}">${esc(g.grade_name)}</option>`).join('');

  await loadEligibilityRules(planId);
}

async function loadEligibilityRules(planId) {
  const res = await api(`/api/benefits/plans/${planId}/eligibility-rules`);
  if (!res || !res.ok) return;
  const rules = await res.json();
  renderEligibilityRules(rules);
}

function renderEligibilityRules(rules) {
  const container = document.getElementById('benEligibilityRulesList');
  if (rules.length === 0) {
    container.innerHTML = '<p class="text-xs text-emerald-700 bg-emerald-50 rounded-lg px-3 py-2">Open to all employees (no rules yet).</p>';
    return;
  }
  container.innerHTML = rules.map(r => `
    <div class="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2">
      <span class="text-sm">${r.job_level_id ? 'Job Level: ' + esc(r.job_level_name) : 'Pay Grade: ' + esc(r.pay_grade_name)}</span>
      <button type="button" onclick="removeEligibilityRule(${r.id})" class="text-xs text-red-700 hover:underline">Remove</button>
    </div>
  `).join('');
}

const addEligibilityRule = guardAsync(async function() {
  const jobLevelId = document.getElementById('benEligJobLevel').value;
  const payGradeId = document.getElementById('benEligPayGrade').value;
  if (!jobLevelId && !payGradeId) {
    alert('Select a job level or pay grade to add.');
    return;
  }
  const res = await api(`/api/benefits/plans/${currentBenefitPlanId}/eligibility-rules`, {
    method: 'POST',
    body: JSON.stringify({
      job_level_id: jobLevelId ? parseInt(jobLevelId) : null,
      pay_grade_id: payGradeId ? parseInt(payGradeId) : null,
    }),
  });
  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }
  document.getElementById('benEligJobLevel').value = '';
  document.getElementById('benEligPayGrade').value = '';
  loadEligibilityRules(currentBenefitPlanId);
});

async function removeEligibilityRule(ruleId) {
  const res = await api(`/api/benefits/plans/${currentBenefitPlanId}/eligibility-rules/${ruleId}`, { method: 'DELETE' });
  if (!res || !res.ok) {
    alert('Error removing eligibility rule');
    return;
  }
  loadEligibilityRules(currentBenefitPlanId);
}

function closeBenefitPlanModal() {
  document.getElementById('benefitPlanModal').classList.add('hidden');
}

async function submitBenefitPlanForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;
  const planId = g('benPlanId');

  if (planId) {
    const body = {
      plan_name: g('benPlanName').trim(),
      status: g('benPlanStatus'),
      employee_cost: g('benPlanEmployeeCost') ? parseFloat(g('benPlanEmployeeCost')) : null,
      employer_cost: g('benPlanEmployerCost') ? parseFloat(g('benPlanEmployerCost')) : null,
      description: g('benPlanDesc').trim() || null,
      carrier_name: g('benPlanCarrierName').trim() || null,
      carrier_group_policy_number: g('benPlanCarrierPolicy').trim() || null,
      payroll_sync_enabled: document.getElementById('benPlanPayrollSync').checked,
    };
    const res = await api(`/api/benefits/plans/${planId}`, { method: 'PUT', body: JSON.stringify(body) });
    if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  } else {
    const body = {
      plan_name: g('benPlanName').trim(),
      plan_category: g('benPlanCategory'),
      contribution_type: g('benPlanContributionType'),
      employee_cost: g('benPlanEmployeeCost') ? parseFloat(g('benPlanEmployeeCost')) : null,
      employer_cost: g('benPlanEmployerCost') ? parseFloat(g('benPlanEmployerCost')) : null,
      plan_year: g('benPlanYear') ? parseInt(g('benPlanYear')) : null,
      effective_date: g('benPlanEffectiveDate') || null,
      end_date: g('benPlanEndDate') || null,
      description: g('benPlanDesc').trim() || null,
      carrier_name: g('benPlanCarrierName').trim() || null,
      carrier_group_policy_number: g('benPlanCarrierPolicy').trim() || null,
      payroll_sync_enabled: document.getElementById('benPlanPayrollSync').checked,
    };
    const res = await api('/api/benefits/plans', { method: 'POST', body: JSON.stringify(body) });
    if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  }

  closeBenefitPlanModal();
  loadBenefitPlans();
}

// ============================================================================
// BENEFITS: ENROLLMENT PERIODS (HR-facing)
// ============================================================================

let enrollmentPeriods = [];
const enrollmentPeriodsList = createListState({ sortKey: 'start_date', sortDir: 'desc' });

async function loadEnrollmentPeriods() {
  const res = await api('/api/benefits/enrollment-periods');
  if (!res || !res.ok) return;
  enrollmentPeriods = await res.json();
  enrollmentPeriodsList.resetPage();
  renderEnrollmentPeriodsTable();
}

function setEnrollmentPeriodsSort(key) { enrollmentPeriodsList.setSort(key); renderEnrollmentPeriodsTable(); }
function setEnrollmentPeriodsPageSize(size) { enrollmentPeriodsList.setPageSize(size); renderEnrollmentPeriodsTable(); }
function enrollmentPeriodsPagePrev() { enrollmentPeriodsList.prevPage(); renderEnrollmentPeriodsTable(); }
function enrollmentPeriodsPageNext() { enrollmentPeriodsList.nextPage(enrollmentPeriods.length); renderEnrollmentPeriodsTable(); }

function renderEnrollmentPeriodsTable() {
  const tbody = document.getElementById('enrollmentPeriodsTableBody');
  if (!tbody) return;
  document.getElementById('enrollmentPeriodsEmptyState')?.classList.toggle('hidden', enrollmentPeriods.length > 0);
  enrollmentPeriodsList.updateSortArrows('.enrollment-periods-sort-arrow');

  const pagination = document.getElementById('enrollmentPeriodsPagination');
  if (!enrollmentPeriods.length) { pagination?.classList.add('hidden'); tbody.innerHTML = ''; return; }
  pagination?.classList.remove('hidden');
  const pageSizeEl = document.getElementById('enrollmentPeriodsPageSize');
  if (pageSizeEl) pageSizeEl.value = String(enrollmentPeriodsList.pageSize);

  const { pageItems, start, total } = enrollmentPeriodsList.view(enrollmentPeriods);
  const pageInfoEl = document.getElementById('enrollmentPeriodsPageInfo');
  if (pageInfoEl) pageInfoEl.textContent = `${start + 1}-${Math.min(start + enrollmentPeriodsList.pageSize, total)} of ${total}`;

  const statusBadge = status => {
    if (status === 'Open') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Closed') return 'bg-slate-100 text-slate-500';
    return 'bg-amber-100 text-amber-700';
  };

  tbody.innerHTML = pageItems.map(p => `
    <tr>
      <td class="px-4 py-3 font-medium">${esc(p.period_name)}</td>
      <td class="px-4 py-3">${p.plan_year}</td>
      <td class="px-4 py-3 text-sm text-slate-500">${fmtDate(p.start_date)} to ${fmtDate(p.end_date)}</td>
      <td class="px-4 py-3 text-center"><span class="badge ${statusBadge(p.status)}">${esc(p.status)}</span></td>
      <td class="px-4 py-3 text-right">
        ${p.status === 'Draft' ? `<button onclick="changeEnrollmentPeriodStatus(${p.id}, 'Open')" class="text-xs text-blue-700 hover:underline">Open</button>` : ''}
        ${p.status === 'Open' ? `<button onclick="changeEnrollmentPeriodStatus(${p.id}, 'Closed')" class="text-xs text-red-700 hover:underline">Close</button>` : ''}
        ${p.status === 'Closed' ? '<span class="text-xs text-slate-400">—</span>' : ''}
      </td>
    </tr>
  `).join('');
}

function openEnrollmentPeriodForm() {
  document.getElementById('enrollmentPeriodForm').reset();
  document.getElementById('enrollmentPeriodModal').classList.remove('hidden');
}

function closeEnrollmentPeriodModal() {
  document.getElementById('enrollmentPeriodModal').classList.add('hidden');
}

async function submitEnrollmentPeriodForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;
  const body = {
    period_name: g('epName').trim(),
    plan_year: parseInt(g('epYear')),
    start_date: g('epStart'),
    end_date: g('epEnd'),
  };
  const res = await api('/api/benefits/enrollment-periods', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeEnrollmentPeriodModal();
  loadEnrollmentPeriods();
}

async function changeEnrollmentPeriodStatus(periodId, status) {
  const res = await api(`/api/benefits/enrollment-periods/${periodId}`, { method: 'PUT', body: JSON.stringify({ status }) });
  if (!res || !res.ok) { alert('Error updating enrollment period'); return; }
  loadEnrollmentPeriods();
}

// ============================================================================
// BENEFITS: LIFE EVENTS (HR-facing review)
// ============================================================================

let lifeEvents = [];
const lifeEventsList = createListState({ sortKey: 'event_date', sortDir: 'desc' });

async function loadLifeEvents() {
  const res = await api('/api/benefits/life-events');
  if (!res || !res.ok) return;
  lifeEvents = await res.json();
  lifeEventsList.resetPage();
  renderLifeEventsTable();
}

function setLifeEventsSort(key) { lifeEventsList.setSort(key); renderLifeEventsTable(); }
function setLifeEventsPageSize(size) { lifeEventsList.setPageSize(size); renderLifeEventsTable(); }
function lifeEventsPagePrev() { lifeEventsList.prevPage(); renderLifeEventsTable(); }
function lifeEventsPageNext() { lifeEventsList.nextPage(lifeEvents.length); renderLifeEventsTable(); }

function renderLifeEventsTable() {
  const tbody = document.getElementById('lifeEventsTableBody');
  if (!tbody) return;
  document.getElementById('lifeEventsEmptyState')?.classList.toggle('hidden', lifeEvents.length > 0);
  lifeEventsList.updateSortArrows('.life-events-sort-arrow');

  const pagination = document.getElementById('lifeEventsPagination');
  if (!lifeEvents.length) { pagination?.classList.add('hidden'); tbody.innerHTML = ''; return; }
  pagination?.classList.remove('hidden');
  const pageSizeEl = document.getElementById('lifeEventsPageSize');
  if (pageSizeEl) pageSizeEl.value = String(lifeEventsList.pageSize);

  const { pageItems, start, total } = lifeEventsList.view(lifeEvents);
  const pageInfoEl = document.getElementById('lifeEventsPageInfo');
  if (pageInfoEl) pageInfoEl.textContent = `${start + 1}-${Math.min(start + lifeEventsList.pageSize, total)} of ${total}`;

  const statusBadge = status => {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-amber-100 text-amber-700';
  };

  tbody.innerHTML = pageItems.map(ev => `
    <tr>
      <td class="px-4 py-3">
        <p class="font-medium">${esc(ev.employee_name ? displayName(ev.employee_name, ev.employee_preferred_name) : ev.employee_id)}</p>
        <p class="text-xs text-slate-500">${esc(ev.employee_id)}</p>
      </td>
      <td class="px-4 py-3">${esc(ev.event_type)}</td>
      <td class="px-4 py-3">${fmtDate(ev.event_date)}</td>
      <td class="px-4 py-3">
        <span class="badge ${statusBadge(ev.status)}">${esc(ev.status)}</span>
        ${ev.window_end_date ? `<p class="text-xs text-slate-400 mt-1">Window until ${fmtDate(ev.window_end_date)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right">
        ${ev.status === 'Pending Review' ? `
          <button onclick="decideLifeEvent(${ev.id}, 'Approved')" class="text-xs text-emerald-700 hover:underline mr-3">Approve</button>
          <button onclick="decideLifeEvent(${ev.id}, 'Rejected')" class="text-xs text-red-700 hover:underline">Reject</button>
        ` : '<span class="text-xs text-slate-400">—</span>'}
      </td>
    </tr>
  `).join('');
}

async function decideLifeEvent(eventId, status) {
  const res = await api(`/api/benefits/life-events/${eventId}/decide`, { method: 'PUT', body: JSON.stringify({ status }) });
  if (!res || !res.ok) { alert('Error deciding life event'); return; }
  loadLifeEvents();
}

// ============================================================================
// MY BENEFITS (self-service)
// ============================================================================

let myEligiblePlans = [];
let myEnrollments = [];
let myActivePeriod = null;
let myApprovedWindowEvent = null;

async function loadMyBenefitsPage() {
  const [plansRes, enrollRes, periodRes, eventsRes, depsRes, claimsRes] = await Promise.all([
    api('/api/benefits/eligible-plans/mine'),
    api('/api/benefits/enrollments/mine'),
    api('/api/benefits/enrollment-periods/active'),
    api('/api/benefits/life-events/mine'),
    api('/api/benefits/dependents/mine'),
    api('/api/benefits/claims/mine'),
  ]);

  myEligiblePlans = (plansRes && plansRes.ok) ? await plansRes.json() : [];
  myEnrollments = (enrollRes && enrollRes.ok) ? await enrollRes.json() : [];
  myActivePeriod = (periodRes && periodRes.ok) ? await periodRes.json() : null;
  const myEvents = (eventsRes && eventsRes.ok) ? await eventsRes.json() : [];
  const myDeps = (depsRes && depsRes.ok) ? await depsRes.json() : [];
  const myClaims = (claimsRes && claimsRes.ok) ? await claimsRes.json() : [];

  const today = new Date().toISOString().slice(0, 10);
  myApprovedWindowEvent = myEvents.find(e => e.status === 'Approved' && e.window_end_date && e.window_end_date >= today) || null;

  renderMyBenefitsBanner();
  renderMyBenefitsPlansTable();
  renderMyLifeEventsTable(myEvents);
  renderMyClaimsTable(myClaims);
  renderDependentsTable(document.getElementById('myDependentsTableBody'), document.getElementById('myDependentsEmptyState'), myDeps, true);
}

function renderMyBenefitsBanner() {
  const banner = document.getElementById('myBenefitsWindowBanner');
  if (myActivePeriod) {
    banner.className = 'mb-4 rounded-xl border px-4 py-3 text-sm bg-emerald-50 border-emerald-200 text-emerald-800';
    banner.textContent = `Open enrollment is active: "${myActivePeriod.period_name}" through ${fmtDate(myActivePeriod.end_date)}. You can enroll or change your elections now.`;
    banner.classList.remove('hidden');
  } else if (myApprovedWindowEvent) {
    banner.className = 'mb-4 rounded-xl border px-4 py-3 text-sm bg-blue-50 border-blue-200 text-blue-800';
    banner.textContent = `You have a life-event enrollment window open until ${fmtDate(myApprovedWindowEvent.window_end_date)} (${myApprovedWindowEvent.event_type}).`;
    banner.classList.remove('hidden');
  } else {
    banner.className = 'mb-4 rounded-xl border px-4 py-3 text-sm bg-slate-50 border-slate-200 text-slate-600';
    banner.textContent = 'No open enrollment period is currently active. You can still submit a life event if you have a qualifying change.';
    banner.classList.remove('hidden');
  }
}

function renderMyBenefitsPlansTable() {
  const tbody = document.getElementById('myBenefitsPlansTableBody');
  document.getElementById('myBenefitsPlansEmptyState')?.classList.toggle('hidden', myEligiblePlans.length > 0);
  const canElect = !!(myActivePeriod || myApprovedWindowEvent);

  const fmtCost = (v, type) => {
    if (v == null) return '—';
    if (type === 'Percent of Salary') return `${Number(v)}%`;
    return fmtCurrency(v);
  };

  tbody.innerHTML = myEligiblePlans.map(p => {
    const enrollment = myEnrollments.find(e => e.benefit_plan_id === p.id);
    const electionBadge = !enrollment ? 'bg-slate-100 text-slate-500'
      : enrollment.status === 'Enrolled' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500';
    const electionLabel = enrollment ? enrollment.status : 'Not elected';
    return `
      <tr>
        <td class="px-4 py-3 font-medium">${esc(p.plan_name)}</td>
        <td class="px-4 py-3"><span class="badge bg-purple-100 text-purple-700">${esc(p.plan_category)}</span></td>
        <td class="px-4 py-3 text-right">${fmtCost(p.employee_cost, p.contribution_type)}</td>
        <td class="px-4 py-3"><span class="badge ${electionBadge}">${esc(electionLabel)}</span></td>
        <td class="px-4 py-3 text-right">
          ${canElect ? `
            <button onclick="electMyBenefit(${p.id}, 'Enrolled')" class="text-xs text-emerald-700 hover:underline mr-3">Enroll</button>
            <button onclick="electMyBenefit(${p.id}, 'Waived')" class="text-xs text-slate-600 hover:underline">Waive</button>
          ` : '<span class="text-xs text-slate-400">No open window</span>'}
        </td>
      </tr>
    `;
  }).join('');
}

function renderMyLifeEventsTable(events) {
  const tbody = document.getElementById('myLifeEventsTableBody');
  document.getElementById('myLifeEventsEmptyState')?.classList.toggle('hidden', events.length > 0);
  const statusBadge = status => {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-amber-100 text-amber-700';
  };
  tbody.innerHTML = events.map(ev => `
    <tr>
      <td class="px-4 py-3">${esc(ev.event_type)}</td>
      <td class="px-4 py-3">${fmtDate(ev.event_date)}</td>
      <td class="px-4 py-3"><span class="badge ${statusBadge(ev.status)}">${esc(ev.status)}</span></td>
    </tr>
  `).join('');
}

async function electMyBenefit(planId, status) {
  const body = { benefit_plan_id: planId, status };
  if (!myActivePeriod && myApprovedWindowEvent) body.life_event_id = myApprovedWindowEvent.id;
  const res = await api('/api/benefits/enrollments/mine', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  loadMyBenefitsPage();
}

function openLifeEventForm() {
  document.getElementById('lifeEventForm').reset();
  document.getElementById('lifeEventModal').classList.remove('hidden');
}

function closeLifeEventModal() {
  document.getElementById('lifeEventModal').classList.add('hidden');
}

async function submitLifeEventForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;
  const body = {
    event_type: g('leType'),
    event_date: g('leDate'),
    notes: g('leNotes').trim() || null,
  };
  const res = await api('/api/benefits/life-events/mine', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeLifeEventModal();
  loadMyBenefitsPage();
}

// ============================================================================
// DEPENDENTS / BENEFICIARIES (shared HR + self-service)
// ============================================================================

let dependentFormContext = 'self'; // 'self' or 'hr'
let currentDependentsEmployeeId = null;

function renderDependentsTable(tbody, emptyState, deps, showActions, context, employeeId) {
  if (!tbody) return;
  emptyState?.classList.toggle('hidden', deps.length > 0);
  tbody.innerHTML = deps.map(d => `
    <tr>
      <td class="px-4 py-3">
        <p class="font-medium">${esc(d.full_name)}</p>
        ${d.national_id ? `<p class="text-xs text-slate-500">${esc(d.national_id)}</p>` : ''}
      </td>
      <td class="px-4 py-3">${esc(d.relationship)}</td>
      <td class="px-4 py-3">${fmtDate(d.date_of_birth)}</td>
      <td class="px-4 py-3 text-center">
        ${d.is_beneficiary ? `<span class="badge bg-blue-100 text-blue-700">${d.beneficiary_percentage != null ? d.beneficiary_percentage + '%' : 'Yes'}</span>` : '<span class="text-xs text-slate-400">—</span>'}
      </td>
      ${showActions ? `<td class="px-4 py-3 text-right"><button onclick='openDependentForm(${JSON.stringify(d)}, ${JSON.stringify(context)}, ${JSON.stringify(employeeId)})' class="text-xs text-blue-700 hover:underline">Edit</button></td>` : ''}
    </tr>
  `).join('');
}

// Edit Employee > Dependents tab (HR-facing, per employee)
async function loadEmpDependentsTab() {
  const res = await api(`/api/benefits/employees/${currentEmpId}/dependents`);
  const deps = (res && res.ok) ? await res.json() : [];
  renderDependentsTable(document.getElementById('empDependentsTableBody'), document.getElementById('empDependentsEmptyState'), deps, true, 'hr', currentEmpId);
}

function toggleBeneficiaryPercentRow() {
  document.getElementById('depBeneficiaryPercentRow').classList.toggle('hidden', !document.getElementById('depIsBeneficiary').checked);
}

function openDependentForm(existing, context, employeeId) {
  dependentFormContext = context || 'self';
  currentDependentsEmployeeId = employeeId || null;
  document.getElementById('dependentForm').reset();
  document.getElementById('depBeneficiaryPercentRow').classList.add('hidden');
  document.getElementById('depId').value = '';

  if (existing && existing.id) {
    document.getElementById('dependentModalTitle').textContent = 'Edit Dependent';
    document.getElementById('depId').value = existing.id;
    document.getElementById('depName').value = existing.full_name;
    document.getElementById('depRelationship').value = existing.relationship;
    document.getElementById('depDob').value = existing.date_of_birth || '';
    document.getElementById('depNationalId').value = existing.national_id || '';
    document.getElementById('depIsBeneficiary').checked = !!existing.is_beneficiary;
    document.getElementById('depBeneficiaryPercent').value = existing.beneficiary_percentage ?? '';
    document.getElementById('depNotes').value = existing.notes || '';
    if (existing.is_beneficiary) document.getElementById('depBeneficiaryPercentRow').classList.remove('hidden');
  } else {
    document.getElementById('dependentModalTitle').textContent = 'Add Dependent';
  }

  document.getElementById('dependentModal').classList.remove('hidden');
}

function closeDependentModal() {
  document.getElementById('dependentModal').classList.add('hidden');
}

async function submitDependentForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;
  const depId = g('depId');
  const body = {
    full_name: g('depName').trim(),
    relationship: g('depRelationship'),
    date_of_birth: g('depDob') || null,
    national_id: g('depNationalId').trim() || null,
    is_beneficiary: document.getElementById('depIsBeneficiary').checked,
    beneficiary_percentage: g('depBeneficiaryPercent') ? parseFloat(g('depBeneficiaryPercent')) : null,
    notes: g('depNotes').trim() || null,
  };

  let res;
  if (depId) {
    res = await api(`/api/benefits/dependents/${depId}`, { method: 'PUT', body: JSON.stringify(body) });
  } else if (dependentFormContext === 'hr') {
    res = await api(`/api/benefits/employees/${currentDependentsEmployeeId}/dependents`, { method: 'POST', body: JSON.stringify(body) });
  } else {
    res = await api('/api/benefits/dependents/mine', { method: 'POST', body: JSON.stringify(body) });
  }

  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeDependentModal();

  if (dependentFormContext === 'hr') {
    loadEmpDependentsTab();
  } else {
    loadMyBenefitsPage();
  }
}

// ============================================================================
// CLAIMS TRACKING
// ============================================================================

function claimStatusBadge(status) {
  if (status === 'Approved') return 'bg-blue-100 text-blue-700';
  if (status === 'Paid') return 'bg-emerald-100 text-emerald-700';
  if (status === 'Rejected') return 'bg-red-100 text-red-700';
  return 'bg-amber-100 text-amber-700';
}

let currentClaims = [];
const claimsList = createListState({ sortKey: 'claim_date', sortDir: 'desc' });

async function loadClaims() {
  const res = await api('/api/benefits/claims');
  if (!res || !res.ok) return;
  currentClaims = await res.json();
  claimsList.resetPage();
  renderClaimsTable();
}

function setClaimsSort(key) { claimsList.setSort(key); renderClaimsTable(); }
function setClaimsPageSize(size) { claimsList.setPageSize(size); renderClaimsTable(); }
function claimsPagePrev() { claimsList.prevPage(); renderClaimsTable(); }
function claimsPageNext() { claimsList.nextPage(currentClaims.length); renderClaimsTable(); }

function renderClaimsTable() {
  const tbody = document.getElementById('claimsTableBody');
  if (!tbody) return;
  document.getElementById('claimsEmptyState')?.classList.toggle('hidden', currentClaims.length > 0);
  claimsList.updateSortArrows('.claims-sort-arrow');

  const pagination = document.getElementById('claimsPagination');
  if (!currentClaims.length) { pagination?.classList.add('hidden'); tbody.innerHTML = ''; return; }
  pagination?.classList.remove('hidden');
  const pageSizeEl = document.getElementById('claimsPageSize');
  if (pageSizeEl) pageSizeEl.value = String(claimsList.pageSize);

  const { pageItems, start, total } = claimsList.view(currentClaims);
  const pageInfoEl = document.getElementById('claimsPageInfo');
  if (pageInfoEl) pageInfoEl.textContent = `${start + 1}-${Math.min(start + claimsList.pageSize, total)} of ${total}`;

  tbody.innerHTML = pageItems.map(c => `
    <tr>
      <td class="px-4 py-3">
        <p class="font-medium">${esc(c.employee_name ? displayName(c.employee_name, c.employee_preferred_name) : c.employee_id)}</p>
        <p class="text-xs text-slate-500">${esc(c.employee_id)}</p>
      </td>
      <td class="px-4 py-3">
        <p>${esc(c.plan_name)}</p>
        <p class="text-xs text-slate-500">${esc(c.plan_category)}</p>
      </td>
      <td class="px-4 py-3">${fmtDate(c.claim_date)}</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(c.amount_claimed)}</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(c.amount_approved)}</td>
      <td class="px-4 py-3">
        <span class="badge ${claimStatusBadge(c.status)}">${esc(c.status)}</span>
        ${c.payout_date ? `<p class="text-xs text-slate-400 mt-1">Paid ${fmtDate(c.payout_date)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right">
        ${(c.status === 'Submitted' || c.status === 'Under Review') ? `
          <button onclick="openClaimDecideModal(${c.id})" class="text-xs text-emerald-700 hover:underline mr-3">Approve</button>
          <button onclick="rejectClaim(${c.id})" class="text-xs text-red-700 hover:underline">Reject</button>
        ` : c.status === 'Approved' ? `
          <button onclick="markClaimPaid(${c.id})" class="text-xs text-blue-700 hover:underline">Mark Paid</button>
        ` : '<span class="text-xs text-slate-400">—</span>'}
      </td>
    </tr>
  `).join('');
}

async function rejectClaim(claimId) {
  const res = await api(`/api/benefits/claims/${claimId}/decide`, { method: 'PUT', body: JSON.stringify({ status: 'Rejected' }) });
  if (!res || !res.ok) { alert('Error rejecting claim'); return; }
  loadClaims();
}

let currentDecideClaimId = null;

function openClaimDecideModal(claimId) {
  const claim = currentClaims.find(c => c.id === claimId);
  if (!claim) return;
  currentDecideClaimId = claimId;
  document.getElementById('claimDecideInfo').textContent =
    `${claim.employee_name ? displayName(claim.employee_name, claim.employee_preferred_name) : claim.employee_id} claimed ${fmtCurrency(claim.amount_claimed)} under '${claim.plan_name}' (${fmtDate(claim.claim_date)}). Reimbursement Cap plans are capped by the employee's remaining annual balance — an over-cap amount will be rejected by the server with the remaining balance shown.`;
  document.getElementById('claimDecideAmount').value = claim.amount_claimed;
  document.getElementById('claimDecideModal').classList.remove('hidden');
}

function closeClaimDecideModal() {
  document.getElementById('claimDecideModal').classList.add('hidden');
  currentDecideClaimId = null;
}

async function submitClaimDecideForm(e) {
  e.preventDefault();
  const amount_approved = parseFloat(document.getElementById('claimDecideAmount').value);
  const res = await api(`/api/benefits/claims/${currentDecideClaimId}/decide`, {
    method: 'PUT',
    body: JSON.stringify({ status: 'Approved', amount_approved }),
  });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeClaimDecideModal();
  loadClaims();
}

async function markClaimPaid(claimId) {
  const res = await api(`/api/benefits/claims/${claimId}/pay`, { method: 'PUT' });
  if (!res || !res.ok) { alert('Error marking claim as paid'); return; }
  loadClaims();
}

function renderMyClaimsTable(claims) {
  const tbody = document.getElementById('myClaimsTableBody');
  document.getElementById('myClaimsEmptyState')?.classList.toggle('hidden', claims.length > 0);
  tbody.innerHTML = claims.map(c => `
    <tr>
      <td class="px-4 py-3">${esc(c.plan_name)}</td>
      <td class="px-4 py-3">${fmtDate(c.claim_date)}</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(c.amount_claimed)}</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(c.amount_approved)}</td>
      <td class="px-4 py-3"><span class="badge ${claimStatusBadge(c.status)}">${esc(c.status)}</span></td>
    </tr>
  `).join('');
}

async function openClaimForm() {
  document.getElementById('claimForm').reset();
  const select = document.getElementById('claimPlan');
  select.innerHTML = myEligiblePlans.map(p => `<option value="${p.id}">${esc(p.plan_name)} (${esc(p.plan_category)})</option>`).join('');
  await populateClaimProjectField();
  document.getElementById('claimModal').classList.remove('hidden');
}

async function populateClaimProjectField() {
  const wrap = document.getElementById('claimProjectWrap');
  const sel = document.getElementById('claimProjectId');
  wrap.classList.add('hidden');
  sel.innerHTML = '';
  const needed = await moduleHasProjectManagerStep('claims');
  if (!needed) return;
  const res = await api('/api/projects/mine');
  const myProjects = res?.ok ? await res.json() : [];
  if (!myProjects.length) return;  // no project to pick — step auto-skips
  sel.innerHTML = myProjects.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  wrap.classList.remove('hidden');
}

function closeClaimModal() {
  document.getElementById('claimModal').classList.add('hidden');
}

async function submitClaimForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;
  const projectWrap = document.getElementById('claimProjectWrap');
  const body = {
    benefit_plan_id: parseInt(g('claimPlan')),
    claim_date: g('claimDate'),
    amount_claimed: parseFloat(g('claimAmount')),
    description: g('claimDesc').trim() || null,
    project_id: !projectWrap.classList.contains('hidden') && g('claimProjectId') ? parseInt(g('claimProjectId')) : null,
  };
  const res = await api('/api/benefits/claims/mine', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeClaimModal();
  loadMyBenefitsPage();
}

// ============================================================================
// COMPLIANCE & REPORTING
// ============================================================================

async function loadComplianceReport() {
  const res = await api('/api/benefits/reports/summary');
  if (!res || !res.ok) return;
  renderComplianceReport(await res.json());
}

function renderComplianceReport(r) {
  document.getElementById('crActivePlans').textContent = r.total_active_plans;
  document.getElementById('crEnrolledEmployees').textContent = r.total_enrolled_employees;
  document.getElementById('crEmployerCost').textContent = fmtCurrency(r.total_monthly_employer_cost);
  document.getElementById('crClaimsPaid').textContent = fmtCurrency(r.total_claims_paid_ytd);

  const flagsEl = document.getElementById('crComplianceFlags');
  if (r.compliance_flags.length === 0) {
    flagsEl.innerHTML = '<p class="text-sm bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl px-4 py-3">No compliance documentation gaps detected.</p>';
  } else {
    flagsEl.innerHTML = `
      <div class="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
        <p class="text-sm font-semibold text-amber-800 mb-2">Compliance flags (${r.compliance_flags.length})</p>
        <ul class="text-sm text-amber-800 list-disc list-inside space-y-1">
          ${r.compliance_flags.map(f => `<li>${esc(f)}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  const tbody = document.getElementById('crPlansTableBody');
  document.getElementById('crPlansEmptyState')?.classList.toggle('hidden', r.plans.length > 0);
  tbody.innerHTML = r.plans.map(p => `
    <tr>
      <td class="px-4 py-3">
        <p class="font-medium">${esc(p.plan_name)}</p>
        <p class="text-xs text-slate-500">${esc(p.plan_category)}${p.carrier_name ? ' · ' + esc(p.carrier_name) : ''}</p>
      </td>
      <td class="px-4 py-3 text-right">${p.enrolled_count}</td>
      <td class="px-4 py-3 text-right">${p.waived_count}</td>
      <td class="px-4 py-3 text-right">${p.participation_rate != null ? p.participation_rate + '%' : '—'}</td>
      <td class="px-4 py-3 text-right">${p.contribution_type === 'Fixed Premium' ? fmtCurrency(p.monthly_employer_cost_total) : '—'}</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(p.claims_paid_total)}</td>
    </tr>
  `).join('');
}

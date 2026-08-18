// Compensation Framework Management
// ============================================================================

let payGrades = [];
let jobLevels = [];
let jobRoles = [];
let salaryStructures = [];

// ============================================================================
// PAY GRADES MANAGEMENT
// ============================================================================

async function loadPayGrades() {
  const res = await api('/api/compensation/pay-grades');
  if (!res || !res.ok) return;
  payGrades = await res.json();
  renderPayGradesTable();
}

function renderPayGradesTable() {
  const tbody = document.getElementById('payGradesTableBody');
  if (!tbody) return;
  document.getElementById('payGradesEmptyState')?.classList.toggle('hidden', payGrades.length > 0);

  tbody.innerHTML = payGrades.map(grade => `
    <tr class="hover:bg-slate-50 transition cursor-pointer" onclick="editPayGrade(${grade.id})">
      <td class="px-4 py-3">
        <div>
          <p class="font-medium">${esc(grade.grade_code)}</p>
          <p class="text-xs text-slate-500">${esc(grade.grade_name)}</p>
        </div>
      </td>
      <td class="px-4 py-3">Level ${grade.grade_level}</td>
      <td class="px-4 py-3 text-right">
        <div class="text-sm">
          <p class="text-slate-600">${fmtCurrency(grade.min_salary)}</p>
          <p class="text-slate-500 text-xs">min</p>
        </div>
      </td>
      <td class="px-4 py-3 text-right">
        <div class="text-sm">
          <p class="text-slate-600">${fmtCurrency(grade.midpoint_salary)}</p>
          <p class="text-slate-500 text-xs">mid</p>
        </div>
      </td>
      <td class="px-4 py-3 text-right">
        <div class="text-sm">
          <p class="text-slate-600">${fmtCurrency(grade.max_salary)}</p>
          <p class="text-slate-500 text-xs">max</p>
        </div>
      </td>
      <td class="px-4 py-3 text-right">
        <span class="badge ${grade.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}">
          ${grade.is_active ? 'Active' : 'Inactive'}
        </span>
      </td>
    </tr>
  `).join('');
}

async function openPayGradeForm() {
  document.getElementById('payGradeForm').reset();
  document.getElementById('payGradeFormTitle').textContent = 'Create New Pay Grade';
  document.getElementById('payGradeId').value = '';
  document.getElementById('compensationPayGradeModal').classList.remove('hidden');
}

async function submitPayGradeForm(e) {
  e.preventDefault();
  const gradeId = document.getElementById('payGradeId').value;
  const g = id => document.getElementById(id).value;

  const body = {
    grade_code: g('pgCode').trim(),
    grade_name: g('pgName').trim(),
    grade_level: parseInt(g('pgLevel')),
    min_salary: parseFloat(g('pgMin')),
    midpoint_salary: parseFloat(g('pgMid')),
    max_salary: parseFloat(g('pgMax')),
    description: g('pgDesc').trim() || null,
  };

  const url = gradeId ? `/api/compensation/pay-grades/${gradeId}` : '/api/compensation/pay-grades';
  const method = gradeId ? 'PUT' : 'POST';

  const res = await api(url, { method, body: JSON.stringify(body) });
  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  closePayGradeModal();
  loadPayGrades();
}

function closePayGradeModal() {
  document.getElementById('compensationPayGradeModal').classList.add('hidden');
}

function editPayGrade(gradeId) {
  const grade = payGrades.find(g => g.id === gradeId);
  if (!grade) return;

  document.getElementById('payGradeFormTitle').textContent = `Edit Pay Grade: ${grade.grade_code}`;
  document.getElementById('payGradeId').value = gradeId;
  document.getElementById('pgCode').value = grade.grade_code;
  document.getElementById('pgName').value = grade.grade_name;
  document.getElementById('pgLevel').value = grade.grade_level;
  document.getElementById('pgMin').value = grade.min_salary;
  document.getElementById('pgMid').value = grade.midpoint_salary;
  document.getElementById('pgMax').value = grade.max_salary;
  document.getElementById('pgDesc').value = grade.description || '';

  document.getElementById('compensationPayGradeModal').classList.remove('hidden');
}

// ============================================================================
// JOB LEVELS MANAGEMENT
// ============================================================================

async function loadJobLevels() {
  const res = await api('/api/compensation/job-levels');
  if (!res || !res.ok) return;
  jobLevels = await res.json();
  renderJobLevelsTable();
}

function renderJobLevelsTable() {
  const tbody = document.getElementById('jobLevelsTableBody');
  if (!tbody) return;
  document.getElementById('jobLevelsEmptyState')?.classList.toggle('hidden', jobLevels.length > 0);

  tbody.innerHTML = jobLevels.map(level => `
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(level.level_code)}</p>
      </td>
      <td class="px-4 py-3">
        <p class="text-sm">${esc(level.level_name)}</p>
      </td>
      <td class="px-4 py-3">
        <span class="inline-block px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded">Level ${level.level_order}</span>
      </td>
      <td class="px-4 py-3">
        <span class="badge ${level.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}">
          ${level.is_active ? 'Active' : 'Inactive'}
        </span>
      </td>
    </tr>
  `).join('');
}

async function openJobLevelForm() {
  document.getElementById('jobLevelForm').reset();
  document.getElementById('compensationJobLevelModal').classList.remove('hidden');
}

async function submitJobLevelForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    level_code: g('jlCode').trim(),
    level_name: g('jlName').trim(),
    level_order: parseInt(g('jlOrder')),
    description: g('jlDesc').trim() || null,
  };

  const res = await api('/api/compensation/job-levels', {
    method: 'POST',
    body: JSON.stringify(body)
  });

  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  document.getElementById('compensationJobLevelModal').classList.add('hidden');
  loadJobLevels();
}

function closeJobLevelModal() {
  document.getElementById('compensationJobLevelModal').classList.add('hidden');
}

// ============================================================================
// JOB ROLES MANAGEMENT
// ============================================================================

async function loadJobRoles() {
  const res = await api('/api/compensation/job-roles');
  if (!res || !res.ok) return;
  jobRoles = await res.json();
  renderJobRolesTable();
}

function renderJobRolesTable() {
  const tbody = document.getElementById('jobRolesTableBody');
  if (!tbody) return;
  document.getElementById('jobRolesEmptyState')?.classList.toggle('hidden', jobRoles.length > 0);

  // Grade mappings now come embedded in each role from /job-roles itself
  // (see JobRoleListItem on the backend) — no more one request per role.
  tbody.innerHTML = jobRoles.map(role => {
    const level = jobLevels.find(l => l.id === role.job_level_id);
    const grades = role.pay_grades || [];
    const gradesLabel = grades.length
      ? grades.map(g => g.is_primary ? `<strong>${esc(g.grade_code)}</strong>` : esc(g.grade_code)).join(', ')
      : '<span class="text-slate-400">—</span>';
    return `
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3"><p class="font-medium">${esc(role.role_code)}</p></td>
      <td class="px-4 py-3"><p class="text-sm">${esc(role.role_name)}</p></td>
      <td class="px-4 py-3"><p class="text-sm">${level ? esc(level.level_name) : '—'}</p></td>
      <td class="px-4 py-3"><p class="text-sm">${role.department ? esc(role.department) : '—'}</p></td>
      <td class="px-4 py-3"><p class="text-sm">${gradesLabel}</p></td>
      <td class="px-4 py-3 text-center">
        <span class="badge ${role.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}">
          ${role.is_active ? 'Active' : 'Inactive'}
        </span>
      </td>
    </tr>
  `;
  }).join('');
}

function openJobRoleForm() {
  document.getElementById('jobRoleForm').reset();

  const levelSelect = document.getElementById('jrLevel');
  levelSelect.innerHTML = jobLevels.map(l => `<option value="${l.id}">${esc(l.level_name)} (${esc(l.level_code)})</option>`).join('');

  const gradesList = document.getElementById('jrGradesList');
  gradesList.innerHTML = payGrades.map(g => `
    <label class="flex items-center gap-3 px-3 py-2 text-sm hover:bg-slate-50">
      <input type="checkbox" class="jr-grade-check" value="${g.id}"/>
      <span class="flex-1">${esc(g.grade_code)} — ${esc(g.grade_name)}</span>
      <span class="flex items-center gap-1 text-xs text-slate-500">
        <input type="radio" name="jrPrimaryGrade" value="${g.id}"/> primary
      </span>
    </label>
  `).join('');

  document.getElementById('compensationJobRoleModal').classList.remove('hidden');
}

function closeJobRoleModal() {
  document.getElementById('compensationJobRoleModal').classList.add('hidden');
}

async function submitJobRoleForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    role_code: g('jrCode').trim(),
    role_name: g('jrName').trim(),
    job_level_id: parseInt(g('jrLevel')),
    department: g('jrDept').trim() || null,
    required_experience_years: g('jrExp') ? parseInt(g('jrExp')) : null,
    description: g('jrDesc').trim() || null,
  };

  const res = await api('/api/compensation/job-roles', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }
  const role = await res.json();

  const primaryGradeId = document.querySelector('input[name="jrPrimaryGrade"]:checked')?.value;
  const checkedGrades = Array.from(document.querySelectorAll('.jr-grade-check:checked')).map(el => el.value);

  for (const gradeId of checkedGrades) {
    const isPrimary = gradeId === primaryGradeId;
    await api(`/api/compensation/job-roles/${role.id}/pay-grades/${gradeId}?is_primary=${isPrimary}`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  }

  closeJobRoleModal();
  loadJobRoles();
}

// ============================================================================
// MERIT CYCLES
// ============================================================================

let meritCycles = [];
let meritRecommendations = [];
let currentMeritCycleId = null;

async function loadMeritCycles() {
  const res = await api('/api/compensation/merit-cycles');
  if (!res || !res.ok) return;
  meritCycles = await res.json();

  const tbody = document.getElementById('meritCyclesTableBody');
  document.getElementById('meritCyclesEmptyState')?.classList.toggle('hidden', meritCycles.length > 0);
  if (tbody) {
    tbody.innerHTML = meritCycles.map(cycle => `
      <tr class="hover:bg-slate-50 transition cursor-pointer" onclick="openMeritCycleDetail(${cycle.id})">
        <td class="px-4 py-3">
          <p class="font-medium">${esc(cycle.cycle_name)}</p>
          <p class="text-xs text-slate-500">${cycle.review_year}</p>
        </td>
        <td class="px-4 py-3">
          <p class="text-sm">${fmtDate(cycle.cycle_start_date)} to ${fmtDate(cycle.cycle_end_date)}</p>
          <p class="text-xs text-slate-500">Submit by: ${fmtDate(cycle.submission_deadline)}</p>
        </td>
        <td class="px-4 py-3">
          ${cycle.budget_pool_amount ? `<p>Budget: ${fmtCurrency(cycle.budget_pool_amount, 0)}</p>` : '<p>—</p>'}
        </td>
        <td class="px-4 py-3">
          <span class="badge ${cycle.status === 'Active' ? 'bg-blue-100 text-blue-700' : cycle.status === 'Draft' ? 'bg-slate-100 text-slate-600' : 'bg-emerald-100 text-emerald-700'}">
            ${cycle.status}
          </span>
        </td>
      </tr>
    `).join('');
  }
}

// ============================================================================
// MERIT RECOMMENDATIONS (per cycle, viewed via the cycle detail modal)
// ============================================================================

async function openMeritCycleDetail(cycleId) {
  const cycle = meritCycles.find(c => c.id === cycleId);
  if (!cycle) return;
  currentMeritCycleId = cycleId;

  document.getElementById('meritDetailTitle').textContent = cycle.cycle_name;
  document.getElementById('meritDetailSubtitle').textContent =
    `${fmtDate(cycle.cycle_start_date)} to ${fmtDate(cycle.cycle_end_date)} — ${cycle.status}`;

  document.getElementById('meritRecForm').classList.add('hidden');
  document.getElementById('meritRecForm').reset();

  if (!employees || employees.length === 0) await loadEmployees();
  const empSelect = document.getElementById('mrEmployee');
  const activeEmployees = (employees || []).filter(e => e.status === 'Active');
  empSelect.innerHTML = activeEmployees.map(e =>
    `<option value="${esc(e.employee_id)}">${esc(e.full_name)} (${esc(e.employee_id)})</option>`
  ).join('');

  await loadMeritRecommendations(cycleId);
  document.getElementById('compensationMeritDetailModal').classList.remove('hidden');
}

function closeMeritDetailModal() {
  document.getElementById('compensationMeritDetailModal').classList.add('hidden');
  currentMeritCycleId = null;
}

function toggleMeritRecForm() {
  document.getElementById('meritRecForm').classList.toggle('hidden');
}

async function onMeritRecEmployeeChange() {
  const employeeId = document.getElementById('mrEmployee').value;
  if (!employeeId) return;
  const res = await api(`/api/compensation/employees/${employeeId}/compensation`);
  if (res && res.ok) {
    const comp = await res.json();
    document.getElementById('mrCurrentSalary').value = comp.base_salary;
    computeMeritNewSalary();
  }
}

function computeMeritNewSalary() {
  const current = parseFloat(document.getElementById('mrCurrentSalary').value);
  const percent = parseFloat(document.getElementById('mrPercent').value);
  if (!isNaN(current) && !isNaN(percent)) {
    document.getElementById('mrNewSalary').value = (current * (1 + percent / 100)).toFixed(2);
  }
}

async function loadMeritRecommendations(cycleId) {
  const res = await api(`/api/compensation/merit-cycles/${cycleId}/recommendations`);
  if (!res || !res.ok) return;
  meritRecommendations = await res.json();
  renderMeritRecTable();
}

function renderMeritRecTable() {
  const tbody = document.getElementById('meritRecTableBody');
  if (!tbody) return;
  document.getElementById('meritRecEmptyState')?.classList.toggle('hidden', meritRecommendations.length > 0);

  const statusBadge = status => {
    if (status === 'Approved') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-amber-100 text-amber-700';
  };

  tbody.innerHTML = meritRecommendations.map(rec => `
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(rec.employee_name || rec.employee_id)}</p>
        <p class="text-xs text-slate-500">${esc(rec.employee_id)}</p>
      </td>
      <td class="px-4 py-3 text-right">${fmtCurrency(rec.current_salary)}</td>
      <td class="px-4 py-3 text-center">${Number(rec.recommended_increase_percent).toFixed(2)}%</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(rec.recommended_new_salary)}</td>
      <td class="px-4 py-3">
        <span class="badge ${statusBadge(rec.approval_status)}">${esc(rec.approval_status)}</span>
        ${rec.reason ? `<p class="text-xs text-slate-500 mt-1">${esc(rec.reason)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right">
        ${rec.approval_status === 'Pending' ? `
          <button onclick="decideMeritRec(${rec.id}, 'Approved')" class="text-xs text-emerald-700 hover:underline mr-3">Approve</button>
          <button onclick="decideMeritRec(${rec.id}, 'Rejected')" class="text-xs text-red-700 hover:underline">Reject</button>
        ` : '<span class="text-xs text-slate-400">—</span>'}
      </td>
    </tr>
  `).join('');
}

async function submitMeritRecommendation(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    employee_id: g('mrEmployee'),
    current_salary: parseFloat(g('mrCurrentSalary')),
    recommended_increase_percent: parseFloat(g('mrPercent')),
    recommended_new_salary: parseFloat(g('mrNewSalary')),
    reason: g('mrReason').trim() || null,
  };

  const res = await api(`/api/compensation/merit-recommendations?merit_cycle_id=${currentMeritCycleId}`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  document.getElementById('meritRecForm').classList.add('hidden');
  document.getElementById('meritRecForm').reset();
  loadMeritRecommendations(currentMeritCycleId);
}

async function decideMeritRec(recId, approvalStatus) {
  const res = await api(`/api/compensation/merit-recommendations/${recId}`, {
    method: 'PUT',
    body: JSON.stringify({ approval_status: approvalStatus }),
  });

  if (!res || !res.ok) {
    alert('Error updating recommendation');
    return;
  }

  loadMeritRecommendations(currentMeritCycleId);
}

async function openMeritCycleForm() {
  document.getElementById('meritCycleForm').reset();
  document.getElementById('compensationMeritModal').classList.remove('hidden');
}

async function submitMeritCycleForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    cycle_name: g('mcName').trim(),
    review_year: parseInt(g('mcYear')),
    cycle_start_date: g('mcStart'),
    cycle_end_date: g('mcEnd'),
    submission_deadline: g('mcDeadline'),
    budget_pool_amount: parseFloat(g('mcBudget')) || null,
    description: g('mcDesc').trim() || null,
  };

  const res = await api('/api/compensation/merit-cycles', {
    method: 'POST',
    body: JSON.stringify(body)
  });

  if (!res || !res.ok) {
    alert('Error creating merit cycle');
    return;
  }

  document.getElementById('compensationMeritModal').classList.add('hidden');
  loadMeritCycles();
}

function closeMeritModal() {
  document.getElementById('compensationMeritModal').classList.add('hidden');
}

// ============================================================================
// VARIABLE PAY: BONUS / INCENTIVE PLANS
// ============================================================================

let bonusPlans = [];
let bonusPayouts = [];
let currentBonusPlanId = null;

async function loadBonusPlans() {
  const res = await api('/api/compensation/bonus-plans');
  if (!res || !res.ok) return;
  bonusPlans = await res.json();
  renderBonusPlansTable();
}

function renderBonusPlansTable() {
  const tbody = document.getElementById('bonusPlansTableBody');
  if (!tbody) return;
  document.getElementById('bonusPlansEmptyState')?.classList.toggle('hidden', bonusPlans.length > 0);

  const statusBadge = status => {
    if (status === 'Active') return 'bg-blue-100 text-blue-700';
    if (status === 'Closed') return 'bg-emerald-100 text-emerald-700';
    return 'bg-slate-100 text-slate-600';
  };

  tbody.innerHTML = bonusPlans.map(plan => `
    <tr class="hover:bg-slate-50 transition cursor-pointer" onclick="openBonusPlanDetail(${plan.id})">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(plan.plan_name)}</p>
        ${plan.plan_year ? `<p class="text-xs text-slate-500">${plan.plan_year}</p>` : ''}
      </td>
      <td class="px-4 py-3"><span class="badge bg-purple-100 text-purple-700">${esc(plan.plan_type)}</span></td>
      <td class="px-4 py-3">
        <p class="text-sm">${plan.period_start && plan.period_end ? `${fmtDate(plan.period_start)} to ${fmtDate(plan.period_end)}` : '—'}</p>
      </td>
      <td class="px-4 py-3">
        ${plan.budget_pool_amount ? `<p>Budget: ${fmtCurrency(plan.budget_pool_amount, 0)}</p>` : '<p>—</p>'}
      </td>
      <td class="px-4 py-3 text-center">
        <span class="badge ${statusBadge(plan.status)}">${esc(plan.status)}</span>
      </td>
    </tr>
  `).join('');
}

function openBonusPlanForm() {
  document.getElementById('bonusPlanForm').reset();
  document.getElementById('compensationBonusPlanModal').classList.remove('hidden');
}

function closeBonusPlanModal() {
  document.getElementById('compensationBonusPlanModal').classList.add('hidden');
}

async function submitBonusPlanForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    plan_name: g('bpName').trim(),
    plan_type: g('bpType'),
    plan_year: parseInt(g('bpYear')) || null,
    period_start: g('bpStart') || null,
    period_end: g('bpEnd') || null,
    budget_pool_amount: parseFloat(g('bpBudget')) || null,
    description: g('bpDesc').trim() || null,
  };

  const res = await api('/api/compensation/bonus-plans', {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  closeBonusPlanModal();
  loadBonusPlans();
}

async function openBonusPlanDetail(planId) {
  const plan = bonusPlans.find(p => p.id === planId);
  if (!plan) return;
  currentBonusPlanId = planId;

  document.getElementById('bonusDetailTitle').textContent = plan.plan_name;
  document.getElementById('bonusDetailSubtitle').textContent =
    `${plan.plan_type}${plan.plan_year ? ' · ' + plan.plan_year : ''}${plan.period_start && plan.period_end ? ' · ' + fmtDate(plan.period_start) + ' to ' + fmtDate(plan.period_end) : ''}`;
  document.getElementById('bonusPlanStatusSelect').value = plan.status;

  document.getElementById('bonusPayoutForm').classList.add('hidden');
  document.getElementById('bonusPayoutForm').reset();

  if (!employees || employees.length === 0) await loadEmployees();
  const empSelect = document.getElementById('bpoEmployee');
  const activeEmployees = (employees || []).filter(e => e.status === 'Active');
  empSelect.innerHTML = activeEmployees.map(e =>
    `<option value="${esc(e.employee_id)}">${esc(e.full_name)} (${esc(e.employee_id)})</option>`
  ).join('');

  await loadBonusPayouts(planId);
  document.getElementById('compensationBonusDetailModal').classList.remove('hidden');
}

function closeBonusDetailModal() {
  document.getElementById('compensationBonusDetailModal').classList.add('hidden');
  currentBonusPlanId = null;
}

function toggleBonusPayoutForm() {
  document.getElementById('bonusPayoutForm').classList.toggle('hidden');
}

async function changeBonusPlanStatus() {
  const status = document.getElementById('bonusPlanStatusSelect').value;
  const res = await api(`/api/compensation/bonus-plans/${currentBonusPlanId}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
  if (!res || !res.ok) {
    alert('Error updating plan status');
    return;
  }
  const updated = await res.json();
  const idx = bonusPlans.findIndex(p => p.id === currentBonusPlanId);
  if (idx >= 0) bonusPlans[idx] = updated;
  renderBonusPlansTable();
}

async function loadBonusPayouts(planId) {
  const res = await api(`/api/compensation/bonus-plans/${planId}/payouts`);
  if (!res || !res.ok) return;
  bonusPayouts = await res.json();
  renderBonusPayoutTable();
}

function renderBonusPayoutTable() {
  const tbody = document.getElementById('bonusPayoutTableBody');
  if (!tbody) return;
  document.getElementById('bonusPayoutEmptyState')?.classList.toggle('hidden', bonusPayouts.length > 0);

  const statusBadge = status => {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Paid') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-amber-100 text-amber-700';
  };

  tbody.innerHTML = bonusPayouts.map(payout => `
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(payout.employee_name || payout.employee_id)}</p>
        <p class="text-xs text-slate-500">${esc(payout.employee_id)}</p>
      </td>
      <td class="px-4 py-3 text-right">${payout.target_amount ? fmtCurrency(payout.target_amount) : '—'}</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(payout.awarded_amount)}</td>
      <td class="px-4 py-3">
        <span class="badge ${statusBadge(payout.status)}">${esc(payout.status)}</span>
        ${payout.reason ? `<p class="text-xs text-slate-500 mt-1">${esc(payout.reason)}</p>` : ''}
        ${payout.payout_date ? `<p class="text-xs text-slate-400 mt-1">Paid ${fmtDate(payout.payout_date)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right">
        ${payout.status === 'Pending' ? `
          <button onclick="decideBonusPayout(${payout.id}, 'Approved')" class="text-xs text-emerald-700 hover:underline mr-3">Approve</button>
          <button onclick="decideBonusPayout(${payout.id}, 'Rejected')" class="text-xs text-red-700 hover:underline">Reject</button>
        ` : payout.status === 'Approved' ? `
          <button onclick="markBonusPayoutPaid(${payout.id})" class="text-xs text-blue-700 hover:underline">Mark Paid</button>
        ` : '<span class="text-xs text-slate-400">—</span>'}
      </td>
    </tr>
  `).join('');
}

async function submitBonusPayout(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    employee_id: g('bpoEmployee'),
    target_amount: parseFloat(g('bpoTarget')) || null,
    awarded_amount: parseFloat(g('bpoAwarded')),
    reason: g('bpoReason').trim() || null,
  };

  const res = await api(`/api/compensation/bonus-payouts?bonus_plan_id=${currentBonusPlanId}`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  document.getElementById('bonusPayoutForm').classList.add('hidden');
  document.getElementById('bonusPayoutForm').reset();
  loadBonusPayouts(currentBonusPlanId);
}

async function decideBonusPayout(payoutId, status) {
  const res = await api(`/api/compensation/bonus-payouts/${payoutId}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
  if (!res || !res.ok) {
    alert('Error updating payout');
    return;
  }
  loadBonusPayouts(currentBonusPlanId);
}

async function markBonusPayoutPaid(payoutId) {
  const res = await api(`/api/compensation/bonus-payouts/${payoutId}/pay`, { method: 'PUT' });
  if (!res || !res.ok) {
    alert('Error marking payout as paid');
    return;
  }
  loadBonusPayouts(currentBonusPlanId);
}

// ============================================================================
// VARIABLE PAY: COMMISSION STRUCTURES
// ============================================================================

let commissionPlans = [];
let commissionEntries = [];
let currentCommissionPlanId = null;

async function loadCommissionPlans() {
  const res = await api('/api/compensation/commission-plans');
  if (!res || !res.ok) return;
  commissionPlans = await res.json();
  renderCommissionPlansTable();
}

function renderCommissionPlansTable() {
  const tbody = document.getElementById('commissionPlansTableBody');
  if (!tbody) return;
  document.getElementById('commissionPlansEmptyState')?.classList.toggle('hidden', commissionPlans.length > 0);

  const statusBadge = status => {
    if (status === 'Active') return 'bg-blue-100 text-blue-700';
    if (status === 'Closed') return 'bg-emerald-100 text-emerald-700';
    return 'bg-slate-100 text-slate-600';
  };

  tbody.innerHTML = commissionPlans.map(plan => `
    <tr class="hover:bg-slate-50 transition cursor-pointer" onclick="openCommissionPlanDetail(${plan.id})">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(plan.plan_name)}</p>
        ${plan.plan_year ? `<p class="text-xs text-slate-500">${plan.plan_year}</p>` : ''}
      </td>
      <td class="px-4 py-3"><span class="badge bg-purple-100 text-purple-700">${esc(plan.plan_type)}</span></td>
      <td class="px-4 py-3">${plan.default_rate_percent != null ? Number(plan.default_rate_percent) + '%' : '—'}</td>
      <td class="px-4 py-3">
        <p class="text-sm">${plan.period_start && plan.period_end ? `${fmtDate(plan.period_start)} to ${fmtDate(plan.period_end)}` : '—'}</p>
      </td>
      <td class="px-4 py-3 text-center">
        <span class="badge ${statusBadge(plan.status)}">${esc(plan.status)}</span>
      </td>
    </tr>
  `).join('');
}

function openCommissionPlanForm() {
  document.getElementById('commissionPlanForm').reset();
  document.getElementById('compensationCommissionPlanModal').classList.remove('hidden');
}

function closeCommissionPlanModal() {
  document.getElementById('compensationCommissionPlanModal').classList.add('hidden');
}

async function submitCommissionPlanForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    plan_name: g('cpName').trim(),
    plan_type: g('cpType'),
    default_rate_percent: parseFloat(g('cpRate')) || null,
    plan_year: parseInt(g('cpYear')) || null,
    period_start: g('cpStart') || null,
    period_end: g('cpEnd') || null,
    description: g('cpDesc').trim() || null,
  };

  const res = await api('/api/compensation/commission-plans', {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  closeCommissionPlanModal();
  loadCommissionPlans();
}

async function openCommissionPlanDetail(planId) {
  const plan = commissionPlans.find(p => p.id === planId);
  if (!plan) return;
  currentCommissionPlanId = planId;

  document.getElementById('commissionDetailTitle').textContent = plan.plan_name;
  document.getElementById('commissionDetailSubtitle').textContent =
    `${plan.plan_type}${plan.default_rate_percent != null ? ' · ' + plan.default_rate_percent + '% default' : ''}${plan.plan_year ? ' · ' + plan.plan_year : ''}${plan.period_start && plan.period_end ? ' · ' + fmtDate(plan.period_start) + ' to ' + fmtDate(plan.period_end) : ''}`;
  document.getElementById('commissionPlanStatusSelect').value = plan.status;

  document.getElementById('commissionEntryForm').classList.add('hidden');
  document.getElementById('commissionEntryForm').reset();
  document.getElementById('cePreview').textContent = '';

  if (!employees || employees.length === 0) await loadEmployees();
  const empSelect = document.getElementById('ceEmployee');
  const activeEmployees = (employees || []).filter(e => e.status === 'Active');
  empSelect.innerHTML = activeEmployees.map(e =>
    `<option value="${esc(e.employee_id)}">${esc(e.full_name)} (${esc(e.employee_id)})</option>`
  ).join('');
  if (plan.default_rate_percent != null) document.getElementById('ceRate').value = plan.default_rate_percent;

  await loadCommissionEntries(planId);
  document.getElementById('compensationCommissionDetailModal').classList.remove('hidden');
}

function closeCommissionDetailModal() {
  document.getElementById('compensationCommissionDetailModal').classList.add('hidden');
  currentCommissionPlanId = null;
}

function toggleCommissionEntryForm() {
  document.getElementById('commissionEntryForm').classList.toggle('hidden');
}

function updateCommissionPreview() {
  const sales = parseFloat(document.getElementById('ceSales').value) || 0;
  const rate = parseFloat(document.getElementById('ceRate').value) || 0;
  const commission = sales * rate / 100;
  document.getElementById('cePreview').textContent =
    sales && rate ? `Calculated commission: ${fmtCurrency(commission)}` : '';
}

async function changeCommissionPlanStatus() {
  const status = document.getElementById('commissionPlanStatusSelect').value;
  const res = await api(`/api/compensation/commission-plans/${currentCommissionPlanId}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
  if (!res || !res.ok) {
    alert('Error updating plan status');
    return;
  }
  const updated = await res.json();
  const idx = commissionPlans.findIndex(p => p.id === currentCommissionPlanId);
  if (idx >= 0) commissionPlans[idx] = updated;
  renderCommissionPlansTable();
}

async function loadCommissionEntries(planId) {
  const res = await api(`/api/compensation/commission-plans/${planId}/entries`);
  if (!res || !res.ok) return;
  commissionEntries = await res.json();
  renderCommissionEntryTable();
}

function renderCommissionEntryTable() {
  const tbody = document.getElementById('commissionEntryTableBody');
  if (!tbody) return;
  document.getElementById('commissionEntryEmptyState')?.classList.toggle('hidden', commissionEntries.length > 0);

  const statusBadge = status => {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Paid') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-amber-100 text-amber-700';
  };

  tbody.innerHTML = commissionEntries.map(entry => `
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(entry.employee_name || entry.employee_id)}</p>
        <p class="text-xs text-slate-500">${esc(entry.employee_id)}</p>
      </td>
      <td class="px-4 py-3 text-right">
        ${fmtCurrency(entry.sales_amount)}
        ${entry.quota_target ? `<p class="text-xs text-slate-400">Quota: ${fmtCurrency(entry.quota_target, 0)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right">${Number(entry.commission_rate_percent)}%</td>
      <td class="px-4 py-3 text-right">${fmtCurrency(entry.calculated_commission)}</td>
      <td class="px-4 py-3">
        <span class="badge ${statusBadge(entry.status)}">${esc(entry.status)}</span>
        ${entry.notes ? `<p class="text-xs text-slate-500 mt-1">${esc(entry.notes)}</p>` : ''}
        ${entry.payout_date ? `<p class="text-xs text-slate-400 mt-1">Paid ${fmtDate(entry.payout_date)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right">
        ${entry.status === 'Pending' ? `
          <button onclick="decideCommissionEntry(${entry.id}, 'Approved')" class="text-xs text-emerald-700 hover:underline mr-3">Approve</button>
          <button onclick="decideCommissionEntry(${entry.id}, 'Rejected')" class="text-xs text-red-700 hover:underline">Reject</button>
        ` : entry.status === 'Approved' ? `
          <button onclick="markCommissionEntryPaid(${entry.id})" class="text-xs text-blue-700 hover:underline">Mark Paid</button>
        ` : '<span class="text-xs text-slate-400">—</span>'}
      </td>
    </tr>
  `).join('');
}

async function submitCommissionEntry(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    employee_id: g('ceEmployee'),
    sales_amount: parseFloat(g('ceSales')),
    quota_target: parseFloat(g('ceQuota')) || null,
    commission_rate_percent: parseFloat(g('ceRate')),
    notes: g('ceNotes').trim() || null,
  };

  const res = await api(`/api/compensation/commission-entries?commission_plan_id=${currentCommissionPlanId}`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  document.getElementById('commissionEntryForm').classList.add('hidden');
  document.getElementById('commissionEntryForm').reset();
  document.getElementById('cePreview').textContent = '';
  loadCommissionEntries(currentCommissionPlanId);
}

async function decideCommissionEntry(entryId, status) {
  const res = await api(`/api/compensation/commission-entries/${entryId}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
  if (!res || !res.ok) {
    alert('Error updating commission entry');
    return;
  }
  loadCommissionEntries(currentCommissionPlanId);
}

async function markCommissionEntryPaid(entryId) {
  const res = await api(`/api/compensation/commission-entries/${entryId}/pay`, { method: 'PUT' });
  if (!res || !res.ok) {
    alert('Error marking commission entry as paid');
    return;
  }
  loadCommissionEntries(currentCommissionPlanId);
}

// ============================================================================
// EQUITY & LONG-TERM INCENTIVES
// ============================================================================

let equityGrants = [];
let currentEquityGrantId = null;
let currentEquityGrantType = null;
let currentEquityGrantFmv = null;
let currentEquityVestingEvents = [];
let currentSettleEventId = null;

async function loadEquityGrants() {
  const res = await api('/api/compensation/equity-grants');
  if (!res || !res.ok) return;
  equityGrants = await res.json();
  renderEquityGrantsTable();
}

function renderEquityGrantsTable() {
  const tbody = document.getElementById('equityGrantsTableBody');
  if (!tbody) return;
  document.getElementById('equityGrantsEmptyState')?.classList.toggle('hidden', equityGrants.length > 0);

  const statusBadge = status => {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    if (status === 'Cancelled') return 'bg-slate-100 text-slate-500';
    return 'bg-amber-100 text-amber-700';
  };

  tbody.innerHTML = equityGrants.map(g => `
    <tr class="hover:bg-slate-50 transition cursor-pointer" onclick="openEquityGrantDetail(${g.id})">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(g.employee_name || g.employee_id)}</p>
        <p class="text-xs text-slate-500">${esc(g.employee_id)}</p>
      </td>
      <td class="px-4 py-3"><span class="badge bg-purple-100 text-purple-700">${esc(g.grant_type)}</span></td>
      <td class="px-4 py-3 text-right">${Number(g.quantity).toLocaleString('en-MY')}</td>
      <td class="px-4 py-3">
        <p class="text-sm">${g.vesting_years}y · ${g.cliff_months}mo cliff</p>
        <p class="text-xs text-slate-400">From ${fmtDate(g.vesting_start_date)}</p>
      </td>
      <td class="px-4 py-3 text-center">
        <span class="badge ${statusBadge(g.status)}">${esc(g.status)}</span>
      </td>
    </tr>
  `).join('');
}

function openEquityGrantForm() {
  document.getElementById('equityGrantForm').reset();
  document.getElementById('egVestYears').value = 4;
  document.getElementById('egCliff').value = 12;
  (async () => {
    if (!employees || employees.length === 0) await loadEmployees();
    const empSelect = document.getElementById('egEmployee');
    const activeEmployees = (employees || []).filter(e => e.status === 'Active');
    empSelect.innerHTML = activeEmployees.map(e =>
      `<option value="${esc(e.employee_id)}">${esc(e.full_name)} (${esc(e.employee_id)})</option>`
    ).join('');
  })();
  document.getElementById('compensationEquityGrantModal').classList.remove('hidden');
}

function closeEquityGrantModal() {
  document.getElementById('compensationEquityGrantModal').classList.add('hidden');
}

async function submitEquityGrantForm(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value;

  const body = {
    employee_id: g('egEmployee'),
    grant_type: g('egType'),
    grant_date: g('egGrantDate'),
    quantity: parseInt(g('egQuantity')),
    strike_price: parseFloat(g('egStrike')) || null,
    fair_market_value_at_grant: parseFloat(g('egFmv')) || null,
    vesting_start_date: g('egVestStart'),
    vesting_years: parseInt(g('egVestYears')),
    cliff_months: parseInt(g('egCliff')),
    notes: g('egNotes').trim() || null,
  };

  const res = await api('/api/compensation/equity-grants', {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }

  closeEquityGrantModal();
  loadEquityGrants();
}

async function openEquityGrantDetail(grantId) {
  currentEquityGrantId = grantId;
  const res = await api(`/api/compensation/equity-grants/${grantId}`);
  if (!res || !res.ok) return;
  const g = await res.json();
  renderEquityGrantDetail(g);
  document.getElementById('compensationEquityDetailModal').classList.remove('hidden');
}

function closeEquityDetailModal() {
  document.getElementById('compensationEquityDetailModal').classList.add('hidden');
  currentEquityGrantId = null;
}

function renderEquityGrantDetail(g) {
  currentEquityGrantType = g.grant_type;
  currentEquityGrantFmv = g.fair_market_value_at_grant;
  currentEquityVestingEvents = g.vesting_events;
  document.getElementById('equityDetailTitle').textContent = `${esc(g.employee_name || g.employee_id)} — ${esc(g.grant_type)}`;
  document.getElementById('equityDetailSubtitle').textContent =
    `${Number(g.quantity).toLocaleString('en-MY')} units · granted ${fmtDate(g.grant_date)} · ${g.vesting_years}y vesting, ${g.cliff_months}mo cliff · ${g.status}`;

  document.getElementById('equityTotalUnits').textContent = Number(g.quantity).toLocaleString('en-MY');
  document.getElementById('equityVestedUnits').textContent = Number(g.quantity_vested).toLocaleString('en-MY');
  document.getElementById('equityUnvestedUnits').textContent = Number(g.quantity_unvested).toLocaleString('en-MY');

  const actions = document.getElementById('equityDetailActions');
  if (g.status === 'Pending Approval') {
    actions.innerHTML = `
      <span class="badge bg-amber-100 text-amber-700">Pending Approval</span>
      <div class="flex gap-2">
        <button onclick="decideEquityGrant('Approved')" class="btn-primary text-sm">Approve</button>
        <button onclick="decideEquityGrant('Rejected')" class="btn-ghost text-sm text-red-700">Reject</button>
      </div>
    `;
  } else if (g.status === 'Approved') {
    actions.innerHTML = `
      <span class="badge bg-blue-100 text-blue-700">Approved</span>
      <button onclick="cancelEquityGrant()" class="btn-ghost text-sm text-red-700">Cancel Grant</button>
    `;
  } else {
    actions.innerHTML = `<span class="badge bg-slate-100 text-slate-500">${esc(g.status)}</span>`;
  }

  const tbody = document.getElementById('equityVestingTableBody');
  document.getElementById('equityVestingEmptyState')?.classList.toggle('hidden', g.vesting_events.length > 0);
  const statusBadge = status => {
    if (status === 'Vested') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Paid') return 'bg-blue-100 text-blue-700';
    if (status === 'Cancelled') return 'bg-slate-100 text-slate-500';
    return 'bg-amber-100 text-amber-700';
  };
  const isPhantom = g.grant_type === 'Phantom';
  tbody.innerHTML = g.vesting_events.map(ev => `
    <tr>
      <td class="px-4 py-3">${fmtDate(ev.vest_date)}</td>
      <td class="px-4 py-3 text-right">${Number(ev.quantity_vested).toLocaleString('en-MY')}</td>
      <td class="px-4 py-3">
        <span class="badge ${statusBadge(ev.status)}">${esc(ev.status)}</span>
        ${ev.vested_at ? `<p class="text-xs text-slate-400 mt-1">Vested ${fmtDate(ev.vested_at)}</p>` : ''}
        ${ev.status === 'Paid' ? `<p class="text-xs text-slate-500 mt-1">${fmtCurrency(ev.cash_payout)} @ ${fmtCurrency(ev.settlement_price, 4)}/unit</p><p class="text-xs text-slate-400">Paid ${fmtDate(ev.payout_date)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right">
        ${ev.status === 'Scheduled' ? `<button onclick="markVestingEventVested(${ev.id})" class="text-xs text-blue-700 hover:underline">Mark Vested</button>`
          : (ev.status === 'Vested' && isPhantom) ? `<button onclick="promptSettleVestingEvent(${ev.id})" class="text-xs text-blue-700 hover:underline">Settle &amp; Pay</button>`
          : '<span class="text-xs text-slate-400">—</span>'}
      </td>
    </tr>
  `).join('');
}

async function decideEquityGrant(status) {
  const res = await api(`/api/compensation/equity-grants/${currentEquityGrantId}/decide`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
  if (!res || !res.ok) {
    alert('Error deciding equity grant');
    return;
  }
  await openEquityGrantDetail(currentEquityGrantId);
  loadEquityGrants();
}

async function cancelEquityGrant() {
  const res = await api(`/api/compensation/equity-grants/${currentEquityGrantId}/cancel`, { method: 'PUT' });
  if (!res || !res.ok) {
    alert('Error cancelling equity grant');
    return;
  }
  await openEquityGrantDetail(currentEquityGrantId);
  loadEquityGrants();
}

async function markVestingEventVested(eventId) {
  const res = await api(`/api/compensation/vesting-events/${eventId}/vest`, { method: 'PUT' });
  if (!res || !res.ok) {
    alert('Error marking vesting event as vested');
    return;
  }
  await openEquityGrantDetail(currentEquityGrantId);
}

function promptSettleVestingEvent(eventId) {
  currentSettleEventId = eventId;
  const ev = currentEquityVestingEvents.find(e => e.id === eventId);
  const fmv = currentEquityGrantFmv;
  document.getElementById('equitySettleInfo').textContent =
    `${Number(ev.quantity_vested).toLocaleString('en-MY')} vested units` +
    (fmv != null ? ` · FMV at grant ${fmtCurrency(fmv, 4)}/unit` : '') +
    ` · payout = max(0, settlement − FMV) × units.`;
  document.getElementById('equitySettleForm').reset();
  document.getElementById('esPreview').textContent = '';
  document.getElementById('equitySettleModal').classList.remove('hidden');
}

function closeEquitySettleModal() {
  document.getElementById('equitySettleModal').classList.add('hidden');
  currentSettleEventId = null;
}

function updateEquitySettlePreview() {
  const ev = currentEquityVestingEvents.find(e => e.id === currentSettleEventId);
  const price = parseFloat(document.getElementById('esPrice').value);
  const fmv = currentEquityGrantFmv != null ? Number(currentEquityGrantFmv) : 0;
  if (!ev || isNaN(price)) { document.getElementById('esPreview').textContent = ''; return; }
  const payout = Math.max(0, price - fmv) * ev.quantity_vested;
  document.getElementById('esPreview').textContent = `Cash payout: ${fmtCurrency(payout)}`;
}

async function submitEquitySettleForm(e) {
  e.preventDefault();
  const settlement_price = parseFloat(document.getElementById('esPrice').value);
  if (isNaN(settlement_price) || settlement_price < 0) {
    alert('Enter a valid non-negative settlement price.');
    return;
  }
  const res = await api(`/api/compensation/vesting-events/${currentSettleEventId}/settle`, {
    method: 'PUT',
    body: JSON.stringify({ settlement_price }),
  });
  if (!res || !res.ok) {
    alert('Error: ' + (await res.json()).detail);
    return;
  }
  closeEquitySettleModal();
  await openEquityGrantDetail(currentEquityGrantId);
}

// ============================================================================
// TOTAL REWARDS STATEMENT
// ============================================================================

function renderTotalRewardsStatement(s) {
  const statusBadge = status => {
    if (status === 'Approved') return 'bg-blue-100 text-blue-700';
    if (status === 'Rejected') return 'bg-red-100 text-red-700';
    return 'bg-slate-100 text-slate-600';
  };

  const formatChangeType = t => t.split('_').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');

  const historyRows = [
    ...s.salary_changes.map(c => ({
      date: c.effective_date, kind: formatChangeType(c.change_type),
      detail: `${fmtCurrency(c.from_salary)} → ${fmtCurrency(c.to_salary)}`,
      status: c.status,
    })),
    ...s.merit_history.map(m => ({
      date: m.approval_date || m.created_at?.slice(0, 10), kind: 'Merit Increase',
      detail: `+${m.recommended_increase_percent}% · ${fmtCurrency(m.current_salary)} → ${fmtCurrency(m.recommended_new_salary)}`,
      status: m.approval_status,
    })),
  ].sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  return `
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="bg-white rounded-xl border border-slate-200 p-5">
        <p class="text-xs text-slate-500 uppercase font-semibold">Annualized Base Salary</p>
        <p class="text-2xl font-bold mt-1">${fmtCurrency(s.base_salary_annualized)}</p>
        <p class="text-xs text-slate-400 mt-1">${s.base_salary_monthly != null ? fmtCurrency(s.base_salary_monthly) + ' / month' : 'No current compensation record'}</p>
      </div>
      <div class="bg-white rounded-xl border border-slate-200 p-5">
        <p class="text-xs text-slate-500 uppercase font-semibold">Variable Pay (${s.year} YTD)</p>
        <p class="text-2xl font-bold mt-1">${fmtCurrency(s.bonus_ytd + s.commission_ytd)}</p>
        <p class="text-xs text-slate-400 mt-1">Bonus ${fmtCurrency(s.bonus_ytd)} · Commission ${fmtCurrency(s.commission_ytd)}</p>
      </div>
      <div class="bg-white rounded-xl border border-blue-200 bg-blue-50 p-5">
        <p class="text-xs text-blue-700 uppercase font-semibold">Total Cash Compensation</p>
        <p class="text-2xl font-bold mt-1 text-blue-900">${fmtCurrency(s.total_cash_compensation)}</p>
        <p class="text-xs text-blue-600 mt-1">Annualized base + ${s.year} bonus &amp; commission</p>
      </div>
    </div>

    <h3 class="text-sm font-semibold text-slate-700 mb-3">Compensation History</h3>
    <div class="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-slate-50 border-b border-slate-200">
          <tr>
            <th class="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Date</th>
            <th class="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Type</th>
            <th class="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Change</th>
            <th class="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Status</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          ${historyRows.map(h => `
            <tr>
              <td class="px-4 py-3">${fmtDate(h.date)}</td>
              <td class="px-4 py-3">${esc(h.kind)}</td>
              <td class="px-4 py-3">${esc(h.detail)}</td>
              <td class="px-4 py-3"><span class="badge ${statusBadge(h.status)}">${esc(h.status)}</span></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      ${historyRows.length === 0 ? '<p class="text-center text-slate-400 text-sm py-12">No compensation history recorded yet.</p>' : ''}
    </div>
  `;
}

function populateYearSelect(selectEl) {
  if (selectEl.options.length > 0) return;
  const thisYear = new Date().getFullYear();
  for (let y = thisYear; y >= thisYear - 2; y--) {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y;
    selectEl.appendChild(opt);
  }
}

async function loadHrTotalRewards() {
  const empSelect = document.getElementById('trEmployeeSelect');
  const yearSelect = document.getElementById('trYearSelect');
  populateYearSelect(yearSelect);

  if (empSelect.options.length === 0) {
    if (!employees || employees.length === 0) await loadEmployees();
    empSelect.innerHTML = (employees || []).map(e =>
      `<option value="${esc(e.employee_id)}">${esc(e.full_name)} (${esc(e.employee_id)})</option>`
    ).join('');
  }

  const empId = empSelect.value;
  const year = yearSelect.value;
  const container = document.getElementById('hrTotalRewardsContent');
  if (!empId) { container.innerHTML = ''; return; }

  const res = await api(`/api/compensation/total-rewards/${empId}?year=${year}`);
  if (!res || !res.ok) { container.innerHTML = '<p class="text-center text-slate-400 text-sm py-12">Unable to load statement.</p>'; return; }
  const data = await res.json();
  container.innerHTML = renderTotalRewardsStatement(data);
}

async function loadMyTotalRewards() {
  const yearSelect = document.getElementById('myTrYearSelect');
  populateYearSelect(yearSelect);
  const container = document.getElementById('myTotalRewardsContent');

  const res = await api(`/api/compensation/total-rewards/mine?year=${yearSelect.value}`);
  if (!res || !res.ok) { container.innerHTML = '<p class="text-center text-slate-400 text-sm py-12">No total rewards statement available for your account.</p>'; return; }
  const data = await res.json();
  container.innerHTML = renderTotalRewardsStatement(data);
}

// ============================================================================
// PAY EQUITY ANALYSIS
// ============================================================================

async function loadPayEquityReport() {
  const res = await api('/api/compensation/pay-equity/report');
  if (!res || !res.ok) return;

  const report = await res.json();
  const container = document.getElementById('payEquityAnalysis');
  if (!container) return;

  let html = `<div class="space-y-6">`;

  if (report.excluded_no_compensation_count > 0) {
    html += `
      <div class="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-start gap-3">
        <svg class="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
        <p class="text-sm text-amber-800">
          <strong>${report.excluded_no_compensation_count} employee${report.excluded_no_compensation_count === 1 ? '' : 's'}</strong>
          ${report.excluded_no_compensation_count === 1 ? 'has' : 'have'} no compensation record assigned and
          ${report.excluded_no_compensation_count === 1 ? 'is' : 'are'} not reflected in the averages below.
          Assign compensation from each employee's profile to include them.
        </p>
      </div>
    `;
  }

  // Gender Gap
  if (report.gender_gap && report.gender_gap.length > 0) {
    const gap = report.gender_gap[0];
    html += `
      <div class="bg-slate-50 border border-slate-200 rounded-lg p-6">
        <h3 class="font-medium text-slate-800 mb-4">Gender Pay Gap Analysis</h3>
        <div class="grid md:grid-cols-2 gap-6">
          <div>
            <p class="text-xs text-slate-500 uppercase mb-1">${esc(gap.category_1)}</p>
            <p class="text-2xl font-bold text-slate-800">${fmtCurrency(gap.avg_salary_1, 0)}</p>
            <p class="text-xs text-slate-600">Employees: ${gap.count_1}</p>
          </div>
          <div>
            <p class="text-xs text-slate-500 uppercase mb-1">${esc(gap.category_2)}</p>
            <p class="text-2xl font-bold text-slate-800">${fmtCurrency(gap.avg_salary_2, 0)}</p>
            <p class="text-xs text-slate-600">Employees: ${gap.count_2}</p>
          </div>
        </div>
        <div class="mt-4">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium">Pay Gap:</span>
            <span class="badge ${Math.abs(gap.pay_gap_percent) > 5 ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}">
              ${gap.pay_gap_percent?.toFixed(2)}%
            </span>
          </div>
        </div>
      </div>
    `;
  }

  // Department Breakdown
  if (report.department_gap && report.department_gap.length > 0) {
    html += `
      <div class="bg-slate-50 border border-slate-200 rounded-lg p-6">
        <h3 class="font-medium text-slate-800 mb-4">Department Salary Distribution</h3>
        <div class="space-y-3">
          ${report.department_gap.map(dept => `
            <div class="flex items-center justify-between">
              <div>
                <p class="text-sm font-medium">${esc(dept.category_1)}</p>
                <p class="text-xs text-slate-500">${dept.count_1} employees</p>
              </div>
              <p class="font-medium">${fmtCurrency(dept.avg_salary_1, 0)}</p>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  html += `</div>`;
  container.innerHTML = html;
}

// ============================================================================
// INITIALIZATION
// ============================================================================

// Compensation now lives as 5 separate top-level pages (Pay Grades, Job
// Levels, Job Roles, Merit Cycles, Pay Equity) rather than one long scroll,
// each wired individually into core.js's showPage() dispatch. Job Roles is
// the one exception that needs a small wrapper: its table and "New Job
// Role" form both look up level/grade names from the payGrades/jobLevels
// arrays, which won't be populated yet if the user navigates here directly
// without visiting those other pages first.
async function loadJobRolesPage() {
  await Promise.all([loadPayGrades(), loadJobLevels()]);
  loadJobRoles();
}

// Note: no DOMContentLoaded auto-run here — core.js's showPage() calls the
// relevant load function itself whenever the user navigates to one of the
// 5 Compensation pages. Running it unconditionally at script-load used to
// fire these requests before any institution was selected (a superadmin's
// active_institution_id is null pre-selection), silently returning empty
// results that then went stale and never refreshed.

// ============================================================================
// EMPLOYEE COMPENSATION (assign Job Role / Job Level / Pay Grade to an
// employee — bridges the Compensation module's taxonomy pages above to an
// individual employee record, from the employee view modal's Compensation
// tab in employees.js/index.html)
// ============================================================================

async function ensureCompLookupsLoaded() {
  const need = [];
  if (!jobRoles.length) need.push(loadJobRoles());
  if (!jobLevels.length) need.push(loadJobLevels());
  if (!payGrades.length) need.push(loadPayGrades());
  if (need.length) await Promise.all(need);
}

async function loadEmployeeCompensationTab(employeeId) {
  const el = document.getElementById('vt-compensation');
  if (!el) return;
  const role = currentUser.role;
  const canAssign = ['superadmin', 'hr_manager', 'payroll_manager', 'compensation_manager'].includes(role);
  document.getElementById('vt-compensation-btn')?.classList.toggle('hidden', !canAssign);
  if (!canAssign) return;

  el.innerHTML = '<p class="text-slate-400 text-sm">Loading…</p>';
  const res = await api(`/api/compensation/employees/${employeeId}/compensation`);
  const actionBtn = `<button onclick="openAssignCompModal('${esc(employeeId)}')" class="btn-primary text-sm mt-4">
    ${res && res.ok ? 'Update Compensation' : 'Assign Compensation'}
  </button>`;

  if (!res || !res.ok) {
    el.innerHTML = `<p class="text-slate-400 text-sm">No compensation record on file for this employee yet.</p>${actionBtn}`;
    return;
  }
  const comp = await res.json();
  el.innerHTML = vgrid([
    ['Job Role', comp.job_role ? `${comp.job_role.role_name} (${comp.job_role.role_code})` : '—'],
    ['Job Level', comp.job_level ? `${comp.job_level.level_name} (${comp.job_level.level_code})` : '—'],
    ['Pay Grade', comp.pay_grade ? `${comp.pay_grade.grade_name} (${comp.pay_grade.grade_code})` : '—'],
    ['Effective Date', fmtDate(comp.effective_date)],
  ]) + '<p class="text-xs text-slate-400 mt-3">Salary is set on the employee\'s own record (Edit Employee → Statutory tab → Basic Salary) — the figure payroll uses — not duplicated here.</p>' + actionBtn;
}

async function openAssignCompModal(employeeId) {
  await ensureCompLookupsLoaded();
  document.getElementById('acEmployeeId').value = employeeId;
  document.getElementById('assignCompForm').reset();
  document.getElementById('assignCompErr').classList.add('hidden');
  document.getElementById('acEffectiveDate').value = new Date().toISOString().slice(0, 10);

  const roleSelect = document.getElementById('acJobRole');
  roleSelect.innerHTML = '<option value="">— No job role —</option>' +
    jobRoles.filter(r => r.is_active).map(r => `<option value="${r.id}">${esc(r.role_name)} (${esc(r.role_code)})</option>`).join('');

  // Prefill from the employee's current compensation, if any, so "Update"
  // starts from where they are rather than blank.
  const current = await api(`/api/compensation/employees/${employeeId}/compensation`);
  if (current && current.ok) {
    const comp = await current.json();
    if (comp.job_role_id) roleSelect.value = comp.job_role_id;
    onAssignCompRoleChange(comp.pay_grade_id);
  } else {
    onAssignCompRoleChange();
  }

  document.getElementById('assignCompModal').classList.remove('hidden');
}

function closeAssignCompModal() {
  document.getElementById('assignCompModal').classList.add('hidden');
}

// Job Role determines Job Level (shown read-only) and narrows the Pay
// Grade choices to that role's own mapped grades — falls back to every
// pay grade in the institution if the role has none mapped yet, or if no
// role is selected at all.
function onAssignCompRoleChange(preselectGradeId) {
  const roleId = parseInt(document.getElementById('acJobRole').value) || null;
  const role = roleId ? jobRoles.find(r => r.id === roleId) : null;
  const level = role ? jobLevels.find(l => l.id === role.job_level_id) : null;
  document.getElementById('acJobLevelDisplay').value = level ? `${level.level_name} (${level.level_code})` : '';

  const grades = (role && role.pay_grades && role.pay_grades.length) ? role.pay_grades : payGrades;
  const gradeSelect = document.getElementById('acPayGrade');
  gradeSelect.innerHTML = '<option value="">— No pay grade —</option>' +
    grades.map(g => `<option value="${g.id}">${esc(g.grade_name)} (${esc(g.grade_code)})</option>`).join('');
  if (preselectGradeId) gradeSelect.value = preselectGradeId;
  onAssignCompGradeChange();
}

function onAssignCompGradeChange() {
  const gradeId = parseInt(document.getElementById('acPayGrade').value) || null;
  const grade = gradeId ? payGrades.find(g => g.id === gradeId) : null;
  const rangeEl = document.getElementById('acGradeRange');
  if (!grade) { rangeEl.textContent = ''; return; }
  rangeEl.textContent = `Range: ${fmtCurrency(grade.min_salary)} – ${fmtCurrency(grade.max_salary)} (midpoint ${fmtCurrency(grade.midpoint_salary)})`;
}

async function submitAssignCompForm(e) {
  e.preventDefault();
  const employeeId = document.getElementById('acEmployeeId').value;
  const err = document.getElementById('assignCompErr');
  err.classList.add('hidden');
  const body = {
    job_role_id: parseInt(document.getElementById('acJobRole').value) || null,
    job_level_id: null,
    pay_grade_id: parseInt(document.getElementById('acPayGrade').value) || null,
    effective_date: document.getElementById('acEffectiveDate').value,
  };
  const role = jobRoles.find(r => r.id === body.job_role_id);
  if (role) body.job_level_id = role.job_level_id;

  const res = await api(`/api/compensation/employees/${employeeId}/compensation`, {
    method: 'POST', body: JSON.stringify(body),
  });
  if (!res) return;
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    err.textContent = d.detail || 'Failed to save compensation';
    err.classList.remove('hidden');
    return;
  }
  closeAssignCompModal();
  await loadEmployeeCompensationTab(employeeId);
}

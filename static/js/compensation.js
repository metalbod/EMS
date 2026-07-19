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
          <p class="text-slate-600">RM ${Number(grade.min_salary).toLocaleString('en-MY', {minimumFractionDigits: 2})}</p>
          <p class="text-slate-500 text-xs">min</p>
        </div>
      </td>
      <td class="px-4 py-3 text-right">
        <div class="text-sm">
          <p class="text-slate-600">RM ${Number(grade.midpoint_salary).toLocaleString('en-MY', {minimumFractionDigits: 2})}</p>
          <p class="text-slate-500 text-xs">mid</p>
        </div>
      </td>
      <td class="px-4 py-3 text-right">
        <div class="text-sm">
          <p class="text-slate-600">RM ${Number(grade.max_salary).toLocaleString('en-MY', {minimumFractionDigits: 2})}</p>
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
  await renderJobRolesTable();
}

async function renderJobRolesTable() {
  const tbody = document.getElementById('jobRolesTableBody');
  if (!tbody) return;
  document.getElementById('jobRolesEmptyState')?.classList.toggle('hidden', jobRoles.length > 0);

  // Grade mappings aren't included in the list response, so fetch them
  // per-role (there's no bulk endpoint) and render once all resolve.
  const gradesByRole = await Promise.all(jobRoles.map(async role => {
    const res = await api(`/api/compensation/job-roles/${role.id}/pay-grades`);
    return (res && res.ok) ? await res.json() : [];
  }));

  tbody.innerHTML = jobRoles.map((role, i) => {
    const level = jobLevels.find(l => l.id === role.job_level_id);
    const grades = gradesByRole[i];
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

async function loadMeritCycles() {
  const res = await api('/api/compensation/merit-cycles');
  if (!res || !res.ok) return;
  const cycles = await res.json();

  const tbody = document.getElementById('meritCyclesTableBody');
  document.getElementById('meritCyclesEmptyState')?.classList.toggle('hidden', cycles.length > 0);
  if (tbody) {
    tbody.innerHTML = cycles.map(cycle => `
      <tr class="hover:bg-slate-50 transition">
        <td class="px-4 py-3">
          <p class="font-medium">${esc(cycle.cycle_name)}</p>
          <p class="text-xs text-slate-500">${cycle.review_year}</p>
        </td>
        <td class="px-4 py-3">
          <p class="text-sm">${cycle.cycle_start_date} to ${cycle.cycle_end_date}</p>
          <p class="text-xs text-slate-500">Submit by: ${cycle.submission_deadline}</p>
        </td>
        <td class="px-4 py-3">
          ${cycle.budget_pool_amount ? `<p>Budget: RM ${Number(cycle.budget_pool_amount).toLocaleString('en-MY', {maximumFractionDigits: 0})}</p>` : '<p>—</p>'}
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
// PAY EQUITY ANALYSIS
// ============================================================================

async function loadPayEquityReport() {
  const res = await api('/api/compensation/pay-equity/report');
  if (!res || !res.ok) return;

  const report = await res.json();
  const container = document.getElementById('payEquityAnalysis');
  if (!container) return;

  let html = `<div class="space-y-6">`;

  // Gender Gap
  if (report.gender_gap && report.gender_gap.length > 0) {
    const gap = report.gender_gap[0];
    html += `
      <div class="bg-slate-50 border border-slate-200 rounded-lg p-6">
        <h3 class="font-medium text-slate-800 mb-4">Gender Pay Gap Analysis</h3>
        <div class="grid md:grid-cols-2 gap-6">
          <div>
            <p class="text-xs text-slate-500 uppercase mb-1">${esc(gap.category_1)}</p>
            <p class="text-2xl font-bold text-slate-800">RM ${Number(gap.avg_salary_1).toLocaleString('en-MY', {maximumFractionDigits: 0})}</p>
            <p class="text-xs text-slate-600">Employees: ${gap.count_1}</p>
          </div>
          <div>
            <p class="text-xs text-slate-500 uppercase mb-1">${esc(gap.category_2)}</p>
            <p class="text-2xl font-bold text-slate-800">RM ${Number(gap.avg_salary_2).toLocaleString('en-MY', {maximumFractionDigits: 0})}</p>
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
              <p class="font-medium">RM ${Number(dept.avg_salary_1).toLocaleString('en-MY', {maximumFractionDigits: 0})}</p>
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

async function initCompensationPage() {
  // Pay grades and job levels must resolve before job roles renders, since
  // its table and "New Job Role" form both look up level/grade names from
  // the payGrades/jobLevels arrays populated by those two calls.
  await Promise.all([loadPayGrades(), loadJobLevels()]);
  loadJobRoles();
  loadMeritCycles();
  loadPayEquityReport();
}

// Note: this page is only loaded (script tag present) once the app shell is
// already up, and core.js's showPage() calls initCompensationPage() itself
// whenever the user navigates to Settings → Compensation — so no
// DOMContentLoaded auto-run here. Running it unconditionally at script-load
// used to fire these requests before any institution was selected (a
// superadmin's active_institution_id is null pre-selection), silently
// returning empty results that then went stale and never refreshed.

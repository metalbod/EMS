// Approval Workflow settings (Leave / Claims / Job Requisition / Timesheet / L&D Enrollment)
// ---------------------------------------------------------------------------
const AW_MODULES = [
  {key:'leave', label:'Leave'},
  {key:'claims', label:'Claims'},
  {key:'requisition', label:'Job Requisition'},
  {key:'timesheet', label:'Timesheet'},
  {key:'ld_enrollment', label:'L&D Enrollment'},
];
const AW_STEP_LABELS = {
  direct_manager: 'Direct Manager',
  skip_level_manager: 'Skip-Level Manager',
  hr_manager: 'HR Manager',
  specific_employee: 'Specific Employee',
  project_manager: 'Project Manager',
};
// Mirrors core/approval_workflow.py's PROJECT_MANAGER_MODULES — Requisition
// and L&D Enrollment have no project link, so that approver type isn't
// offered for them.
const AW_PROJECT_MANAGER_MODULES = ['leave', 'claims', 'timesheet'];

let awCurrentModule = 'leave';
let awWorkflowsCache = [];
let awCurrentWorkflowId = null;

function loadApprovalWorkflowPage() {
  document.getElementById('awModuleTabs').innerHTML = AW_MODULES.map(m =>
    `<button class="view-tab-btn px-4 py-3 text-sm ${m.key===awCurrentModule?'view-tab-active':''}" onclick="switchAwModule('${m.key}')">${esc(m.label)}</button>`
  ).join('');
  awUpdateProjectManagerOptionVisibility();
  loadAwWorkflows();
}

// Used by Leave/Claims submission forms to decide whether to show a
// Project picker — the applicable (default) workflow for the module has
// to actually have a project_manager step configured, primary or alt.
async function moduleHasProjectManagerStep(module) {
  const res = await api(`/api/approval-workflows?module=${module}`);
  if (!res?.ok) return false;
  const workflows = await res.json();
  const wf = workflows.find(w => w.is_default) || workflows[0];
  if (!wf) return false;
  return wf.steps.some(s => s.approver_type === 'project_manager' || s.alt_approver_type === 'project_manager');
}

function awUpdateProjectManagerOptionVisibility() {
  const allowed = AW_PROJECT_MANAGER_MODULES.includes(awCurrentModule);
  ['awNewStepType', 'awNewStepAltType'].forEach(id => {
    const opt = document.querySelector(`#${id} option[value="project_manager"]`);
    if (opt) opt.hidden = !allowed;
  });
}

function switchAwModule(module) {
  awCurrentModule = module;
  awCurrentWorkflowId = null;
  loadApprovalWorkflowPage();
}

async function loadAwWorkflows(selectId) {
  hideAwWorkflowForm();
  const res = await api(`/api/approval-workflows?module=${awCurrentModule}`);
  awWorkflowsCache = res?.ok ? await res.json() : [];
  const sel = document.getElementById('awWorkflowSelect');
  if (!awWorkflowsCache.length) {
    sel.innerHTML = '<option value="">No workflows yet</option>';
    awCurrentWorkflowId = null;
    renderAwSteps();
    return;
  }
  sel.innerHTML = awWorkflowsCache.map(w =>
    `<option value="${w.id}">${esc(w.name)}${w.is_default?' (Default)':''} — ${w.steps.length} step${w.steps.length===1?'':'s'}</option>`
  ).join('');
  awCurrentWorkflowId = selectId && awWorkflowsCache.some(w=>w.id===selectId) ? selectId : awWorkflowsCache[0].id;
  sel.value = String(awCurrentWorkflowId);
  renderAwSteps();
}

function switchApprovalWorkflow() {
  awCurrentWorkflowId = parseInt(document.getElementById('awWorkflowSelect').value);
  renderAwSteps();
}

function showAwWorkflowForm() {
  document.getElementById('awWorkflowName').value = '';
  document.getElementById('awWorkflowIsDefault').checked = false;
  document.getElementById('awWorkflowForm').classList.remove('hidden');
}
function hideAwWorkflowForm() { document.getElementById('awWorkflowForm')?.classList.add('hidden'); }

async function saveAwWorkflow() {
  const name = document.getElementById('awWorkflowName').value.trim();
  if (!name) { alert('Workflow name is required'); return; }
  const res = await api('/api/approval-workflows', {method:'POST', body: JSON.stringify({module: awCurrentModule, name})});
  if (!res?.ok) return;
  const created = await res.json();
  if (document.getElementById('awWorkflowIsDefault').checked) {
    await api(`/api/approval-workflows/${created.id}`, {method:'PUT', body: JSON.stringify({name, is_default:true})});
  }
  hideAwWorkflowForm();
  await loadAwWorkflows(created.id);
}

async function renameAwWorkflow() {
  if (!awCurrentWorkflowId) return;
  const current = awWorkflowsCache.find(w=>w.id===awCurrentWorkflowId);
  const name = prompt('Workflow name:', current?.name || '');
  if (!name || !name.trim()) return;
  const res = await api(`/api/approval-workflows/${awCurrentWorkflowId}`, {method:'PUT', body: JSON.stringify({name: name.trim(), is_default: !!current?.is_default})});
  if (!res?.ok) return;
  await loadAwWorkflows(awCurrentWorkflowId);
}

async function setAwWorkflowDefault() {
  if (!awCurrentWorkflowId) return;
  const current = awWorkflowsCache.find(w=>w.id===awCurrentWorkflowId);
  await api(`/api/approval-workflows/${awCurrentWorkflowId}`, {method:'PUT', body: JSON.stringify({name: current?.name || '', is_default: true})});
  await loadAwWorkflows(awCurrentWorkflowId);
}

async function deleteAwWorkflow() {
  if (!awCurrentWorkflowId) return;
  if (!confirm('Delete this workflow?')) return;
  const res = await api(`/api/approval-workflows/${awCurrentWorkflowId}`, {method:'DELETE'});
  if (!res?.ok) { const d = await res?.json().catch(()=>({})); alert(d?.detail || 'Failed to delete'); return; }
  await loadAwWorkflows();
}

function renderAwSteps() {
  const wrap = document.getElementById('awStepsList');
  const emptyEl = document.getElementById('awStepsEmpty');
  const addForm = document.getElementById('awAddStepForm');
  if (!awCurrentWorkflowId) { wrap.innerHTML=''; emptyEl.classList.remove('hidden'); addForm.classList.add('hidden'); return; }
  const workflow = awWorkflowsCache.find(w=>w.id===awCurrentWorkflowId);
  const steps = workflow?.steps || [];
  addForm.classList.remove('hidden');
  if (!steps.length) { wrap.innerHTML=''; emptyEl.classList.remove('hidden'); return; }
  emptyEl.classList.add('hidden');
  const empName = id => { const e=(employees||[]).find(e=>e.employee_id===id); return e ? esc(e.full_name) : esc(id); };
  wrap.innerHTML = steps.map((s, idx) => {
    const detail = s.approver_type==='specific_employee' ? empName(s.specific_employee_id) : '';
    const altDetail = s.alt_approver_type ?
      `<span class="text-xs text-slate-400 flex-shrink-0">OR</span>
       <span class="badge bg-purple-100 text-purple-700 text-xs flex-shrink-0">${AW_STEP_LABELS[s.alt_approver_type]||s.alt_approver_type}</span>
       ${s.alt_approver_type==='specific_employee' ? `<span class="text-sm text-slate-600 flex-shrink-0">${empName(s.alt_specific_employee_id)}</span>` : ''}` : '';
    return `<div class="flex items-center gap-3 py-2.5 px-3 border border-slate-100 rounded-lg flex-wrap">
      <span class="text-xs font-semibold text-slate-400 w-14 flex-shrink-0">Step ${idx+1}</span>
      <div class="flex flex-col flex-shrink-0">
        <button onclick="moveAwStep(${s.id},'up')" ${idx===0?'disabled':''} class="text-slate-300 hover:text-blue-500 disabled:opacity-30" title="Move up"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg></button>
        <button onclick="moveAwStep(${s.id},'down')" ${idx===steps.length-1?'disabled':''} class="text-slate-300 hover:text-blue-500 disabled:opacity-30" title="Move down"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg></button>
      </div>
      <span class="badge bg-indigo-100 text-indigo-700 text-xs flex-shrink-0">${AW_STEP_LABELS[s.approver_type]||s.approver_type}</span>
      ${detail ? `<span class="text-sm text-slate-600 flex-shrink-0">${detail}</span>` : ''}
      ${altDetail}
      <span class="flex-1"></span>
      <button onclick="deleteAwStep(${s.id})" class="text-slate-300 hover:text-red-500 flex-shrink-0" title="Remove"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
    </div>`;
  }).join('');
}

function _awPopulateEmployeeSelect(sel) {
  if (!sel.options.length) {
    sel.innerHTML = (employees||[]).filter(e=>e.status==='Active')
      .map(e=>`<option value="${e.employee_id}">${esc(e.full_name)} (${esc(e.employee_id)})</option>`).join('');
  }
}

function onAwNewStepTypeChange() {
  const isSpecific = document.getElementById('awNewStepType').value === 'specific_employee';
  const empSel = document.getElementById('awNewStepEmployee');
  empSel.classList.toggle('hidden', !isSpecific);
  if (isSpecific) _awPopulateEmployeeSelect(empSel);
}

function onAwNewStepAltToggle() {
  const hasAlt = document.getElementById('awNewStepHasAlt').checked;
  document.getElementById('awNewStepAltType').classList.toggle('hidden', !hasAlt);
  document.getElementById('awNewStepAltEmployee').classList.toggle('hidden', !hasAlt || document.getElementById('awNewStepAltType').value !== 'specific_employee');
  if (hasAlt) onAwNewStepAltTypeChange();
}

function onAwNewStepAltTypeChange() {
  const hasAlt = document.getElementById('awNewStepHasAlt').checked;
  const isSpecific = document.getElementById('awNewStepAltType').value === 'specific_employee';
  const empSel = document.getElementById('awNewStepAltEmployee');
  empSel.classList.toggle('hidden', !hasAlt || !isSpecific);
  if (isSpecific) _awPopulateEmployeeSelect(empSel);
}

async function addAwStep() {
  if (!awCurrentWorkflowId) { alert('Create a workflow first'); return; }
  const approver_type = document.getElementById('awNewStepType').value;
  const specific_employee_id = approver_type === 'specific_employee' ? document.getElementById('awNewStepEmployee').value : null;
  if (approver_type === 'specific_employee' && !specific_employee_id) { alert('Choose an employee'); return; }

  const hasAlt = document.getElementById('awNewStepHasAlt').checked;
  const alt_approver_type = hasAlt ? document.getElementById('awNewStepAltType').value : null;
  const alt_specific_employee_id = hasAlt && alt_approver_type === 'specific_employee' ? document.getElementById('awNewStepAltEmployee').value : null;
  if (hasAlt) {
    if (alt_approver_type === approver_type) { alert('The OR approver must be a different type than the primary approver'); return; }
    if (alt_approver_type === 'specific_employee' && !alt_specific_employee_id) { alert('Choose an alternative employee'); return; }
  }

  const res = await api(`/api/approval-workflows/${awCurrentWorkflowId}/steps`, {method:'POST', body: JSON.stringify({approver_type, specific_employee_id, alt_approver_type, alt_specific_employee_id})});
  if (!res?.ok) { const d = await res?.json().catch(()=>({})); alert(d?.detail || 'Failed to add step'); return; }
  document.getElementById('awNewStepHasAlt').checked = false;
  onAwNewStepAltToggle();
  await loadAwWorkflows(awCurrentWorkflowId);
}

async function moveAwStep(stepId, direction) {
  await api(`/api/approval-workflows/${awCurrentWorkflowId}/steps/${stepId}/move`, {method:'POST', body: JSON.stringify({direction})});
  await loadAwWorkflows(awCurrentWorkflowId);
}

async function deleteAwStep(stepId) {
  if (!confirm('Remove this step?')) return;
  await api(`/api/approval-workflows/${awCurrentWorkflowId}/steps/${stepId}`, {method:'DELETE'});
  await loadAwWorkflows(awCurrentWorkflowId);
}

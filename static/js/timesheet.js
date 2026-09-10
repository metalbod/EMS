// Timesheet / Projects
// ---------------------------------------------------------------------------
let projectsCache=[], myProjectsCache=[], projectFilter='';
// pageSize is set well above any realistic project count — this list has no
// pagination UI, only sorting, so createListState is used sort-only here.
const projectList = createListState({ sortKey: 'name', pageSize: 10000 });
// Pivot-table expand state for the Projects list — which project rows are
// showing their task sub-rows, and each project's own task list once
// fetched (lazy: only loaded on first expand, not for every project up
// front). Kept in sync with the Edit Project modal's own task list by
// loadProjectTasksForManage below, rather than a second independent fetch
// path, so editing a task there can't leave this cache stale.
let expandedProjectIds=new Set(), projectTasksByProject={};
let tsCurrentWeekStart=null, tsCurrentTimesheet=null;
let tsApprovalFilter='Submitted';
const TS_STATUS_COLORS={'Draft':'status-neutral','Submitted':'status-pending','Approved':'status-positive','Rejected':'status-negative'};

// Login roles eligible to be picked as a Project Manager. Matters beyond
// the picker itself: core/approval_workflow.py's "project_manager"
// approver type lets anyone listed in a project's manager_ids approve
// that project's timesheets, regardless of their own login role — so
// this list is what keeps that approval power aligned with roles that
// could plausibly hold it through any other path in the app. Frontend-
// only for now (POST/PUT /api/projects still accepts any employee_id),
// so this narrows the picker but doesn't by itself close that off.
const PROJECT_MANAGER_ELIGIBLE_ROLES=['manager','hr_manager','hr_admin'];
// employee_ids currently holding one of those roles — populated by
// loadProjectManagerEligibility() each time the Edit Project modal opens.
let projectManagerEligibleIds=new Set();

function isProjectManager() {
  return HR_MANAGER_ONLY_ROLES.includes(currentUser?.role);
}

// ---------------------------------------------------------------------------
// Projects (HR Manager)
// ---------------------------------------------------------------------------
const PROJECT_TABLE_COLUMNS=[
  {key:'name', label:'Project'},
  {key:'status', label:'Status'},
  {key:'task_count', label:'Tasks'},
  {key:'member_count', label:'Team'},
  {key:'total_allocated_hours', label:'Allocated'},
  {key:'total_logged_hours', label:'Clocked'},
];

async function loadProjects() {
  const listEl=document.getElementById('projectList');
  const emptyEl=document.getElementById('projectEmpty');
  listEl.innerHTML='<tr><td colspan="6" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  let url='/api/projects';
  if(projectFilter) url+=`?status=${encodeURIComponent(projectFilter)}`;
  const res=await api(url);
  if(!res?.ok){ listEl.innerHTML=''; return; }
  const rows=await res.json();
  projectsCache=rows;
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); renderProjectTableHead(); return; }
  emptyEl?.classList.add('hidden');
  renderProjectTableHead();
  renderProjectTable();
}

function renderProjectTableHead() {
  document.getElementById('projectTableHead').innerHTML=PROJECT_TABLE_COLUMNS.map(c=>{
    const active=projectList.sortKey===c.key;
    const arrow=active?(projectList.sortDir==='asc'?'▲':'▼'):'';
    return `<th class="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide cursor-pointer select-none hover:text-slate-700" onclick="setProjectSort('${c.key}')">${c.label} <span class="text-blue-600">${arrow}</span></th>`;
  }).join('');
}

function setProjectSort(key) {
  projectList.setSort(key);
  renderProjectTableHead();
  renderProjectTable();
}

function renderProjectTable() {
  const listEl=document.getElementById('projectList');
  const STATUS_COLORS={'Active':'status-positive','On Hold':'status-pending','Completed':'status-neutral'};
  const { pageItems: sorted } = projectList.view(projectsCache);
  listEl.innerHTML=sorted.map(p=>{
    const expanded=expandedProjectIds.has(p.id);
    return `
    <tr class="border-t border-slate-100 cursor-pointer hover:bg-slate-50 transition" onclick="openProjectModal(${p.id})">
      <td class="px-4 py-3">
        <div class="flex items-center gap-2">
          <button onclick="event.stopPropagation();toggleProjectExpand(${p.id})" class="shrink-0 p-0.5 text-slate-400 hover:text-slate-600" title="${expanded?'Collapse':'Expand'} tasks">
            <svg class="w-3.5 h-3.5 transition-transform ${expanded?'rotate-90':''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"/></svg>
          </button>
          <div class="min-w-0">
            <p class="font-medium text-slate-800">${esc(p.name)}</p>
            <p class="text-xs text-slate-400 line-clamp-1">${esc(p.description||'')}</p>
          </div>
        </div>
      </td>
      <td class="px-4 py-3"><span class="badge text-xs ${statusColor(STATUS_COLORS, p.status)}">${p.status}</span></td>
      <td class="px-4 py-3 text-slate-600">${p.task_count}</td>
      <td class="px-4 py-3 text-slate-600">${p.member_count}</td>
      <td class="px-4 py-3 text-slate-600">${p.total_allocated_hours}h</td>
      <td class="px-4 py-3 text-slate-600">${p.total_logged_hours}h</td>
    </tr>${expanded?projectTaskSubRows(p.id):''}`;
  }).join('');
}

// Pivot-table task sub-rows for one project — see toggleProjectExpand.
// Purely informational (no click handler): task editing stays in the
// existing Edit Project modal's Tasks tab, not duplicated here.
function projectTaskSubRows(projectId) {
  const tasks=projectTasksByProject[projectId];
  if(tasks===undefined) {
    return `<tr class="bg-slate-50/60"><td colspan="6" class="pl-12 pr-4 py-2.5 text-xs text-slate-400">Loading tasks…</td></tr>`;
  }
  if(!tasks.length) {
    return `<tr class="bg-slate-50/60"><td colspan="6" class="pl-12 pr-4 py-2.5 text-xs text-slate-400">No tasks yet.</td></tr>`;
  }
  return tasks.map(t=>`
    <tr class="bg-slate-50/60 border-t border-slate-100">
      <td class="pl-12 pr-4 py-2.5">
        <div class="flex items-center gap-2 min-w-0">
          <span class="text-slate-300 shrink-0">↳</span>
          <span class="text-slate-700 truncate">${esc(t.name)}</span>
          ${t.open_to_all?'<span class="badge text-xs bg-blue-100 text-blue-700 shrink-0">ALL</span>':''}
        </div>
      </td>
      <td class="px-4 py-2.5"><span class="badge text-xs ${statusColor(TASK_STATUS_COLORS, t.status)}">${t.status}</span></td>
      <td class="px-4 py-2.5 text-slate-300">—</td>
      <td class="px-4 py-2.5 text-slate-300">—</td>
      <td class="px-4 py-2.5 text-slate-500">${t.estimated_hours?t.estimated_hours+'h':'—'}</td>
      <td class="px-4 py-2.5 text-slate-500">${t.logged_hours}h</td>
    </tr>`).join('');
}

async function toggleProjectExpand(projectId) {
  if(expandedProjectIds.has(projectId)) {
    expandedProjectIds.delete(projectId);
    renderProjectTable();
    return;
  }
  expandedProjectIds.add(projectId);
  renderProjectTable();
  if(!projectTasksByProject[projectId]) {
    const res=await api(`/api/projects/${projectId}/tasks`);
    projectTasksByProject[projectId]=res?.ok?await res.json():[];
    renderProjectTable();
  }
}

function setProjectFilter(status) {
  projectFilter=status;
  document.querySelectorAll('.project-filter-btn').forEach(b=>b.classList.remove('project-filter-active'));
  event?.target?.classList?.add('project-filter-active');
  loadProjects();
}

function switchProjectTab(name) {
  ['details','tasks'].forEach(t=>{
    document.getElementById(`projectTab-${t}`)?.classList.toggle('hidden', t!==name);
    const btn=document.querySelector(`.project-tab-btn[data-ptab="${t}"]`);
    if(btn){ btn.classList.toggle('project-tab-active', t===name); btn.classList.toggle('text-slate-500', t!==name); }
  });
}

// Fetches which employees currently hold a manager-tier login role
// (PROJECT_MANAGER_ELIGIBLE_ROLES), for renderProjectManagersChecklist to
// filter against. Reachable only by whoever can already open the Edit
// Project modal (nav-projects is HR_MANAGER_ONLY_ROLES-gated), which is
// exactly who /api/users' own role gate (_USER_MANAGE = superadmin,
// hr_manager) already allows — no new backend permission needed.
async function loadProjectManagerEligibility() {
  const res=await api('/api/users');
  const list=res?.ok?await res.json():[];
  projectManagerEligibleIds=new Set(
    list.filter(u=>u.is_active && PROJECT_MANAGER_ELIGIBLE_ROLES.includes(u.role) && u.employee_id).map(u=>u.employee_id)
  );
}

function renderProjectManagersChecklist(selectedIds) {
  const wrap=document.getElementById('projectManagersList');
  // Limited to manager-tier employees (see PROJECT_MANAGER_ELIGIBLE_ROLES)
  // — plus anyone already assigned, even if their role no longer
  // qualifies, so re-saving an existing project without touching this
  // field can't silently drop a legacy assignment the picker itself
  // wouldn't offer anymore.
  const active=(employees||[]).filter(e=>e.status==='Active' && (projectManagerEligibleIds.has(e.employee_id) || selectedIds.includes(e.employee_id)));
  wrap.innerHTML=active.map(e=>{
    const label=`${displayName(e.full_name,e.preferred_name)} (${e.employee_id})`;
    return `
    <label class="project-manager-option flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 cursor-pointer" data-label="${esc(label)}">
      <input type="checkbox" class="project-manager-checkbox" value="${e.employee_id}" ${selectedIds.includes(e.employee_id)?'checked':''} onchange="syncProjectManagersSelectAll()"/>
      ${esc(label)}
    </label>`;
  }).join('') + `<div id="projectManagersNoMatch" class="hidden text-center text-xs text-slate-400 py-3">No matches</div>`;
  const searchEl=document.getElementById('projectManagersSearch');
  if(searchEl) searchEl.value='';
  // Also handles the "nobody eligible at all" empty state and syncs
  // Select All — same computation filterProjectManagerOptions does for a
  // live search, run here once against the just-rendered, unfiltered list.
  filterProjectManagerOptions();
}

// Filters the checklist by name/ID as the user types, without re-rendering
// (so checked state — including for options scrolled out of view — is never
// lost). Reuses employee-picker.js's filterEmployeeOptions (same
// substring/case-insensitive match already used by every searchable
// employee <select> in the app) rather than a second hand-rolled matcher.
// "Select All" only ever acts on what's currently visible, so it composes
// with an active search instead of fighting it.
function filterProjectManagerOptions() {
  const q=document.getElementById('projectManagersSearch')?.value||'';
  const opts=[...document.querySelectorAll('.project-manager-option')];
  const matched=new Set(filterEmployeeOptions(
    opts.map(el=>({value: el.querySelector('.project-manager-checkbox').value, label: el.dataset.label})),
    q
  ).map(o=>o.value));
  let visibleCount=0;
  opts.forEach(opt=>{
    const match=matched.has(opt.querySelector('.project-manager-checkbox').value);
    opt.classList.toggle('hidden', !match);
    if(match) visibleCount++;
  });
  document.getElementById('projectManagersNoMatch')?.classList.toggle('hidden', visibleCount>0);
  syncProjectManagersSelectAll();
}

function visibleProjectManagerCheckboxes() {
  return [...document.querySelectorAll('.project-manager-option:not(.hidden) .project-manager-checkbox')];
}

function syncProjectManagersSelectAll() {
  const boxes=visibleProjectManagerCheckboxes();
  document.getElementById('projectManagersSelectAll').checked = boxes.length>0 && boxes.every(b=>b.checked);
}

function toggleAllProjectManagers() {
  const checked=document.getElementById('projectManagersSelectAll').checked;
  visibleProjectManagerCheckboxes().forEach(b=>b.checked=checked);
}

async function openProjectModal(projectId) {
  document.getElementById('projectId').value=projectId||'';
  document.getElementById('projectModalTitle').textContent=projectId?'Edit Project':'Add Project';
  const tasksBtn=document.getElementById('projectTabTasksBtn');
  switchProjectTab('details');
  if(!employees || !employees.length) await loadEmployees();
  await loadProjectManagerEligibility();
  if(projectId){
    const p=projectsCache.find(x=>x.id===projectId);
    document.getElementById('projectName').value=p?.name||'';
    document.getElementById('projectDesc').value=p?.description||'';
    document.getElementById('projectStatus').value=p?.status||'Active';
    renderProjectManagersChecklist(p?.manager_ids||[]);
    tasksBtn.classList.remove('hidden');
    await loadProjectTasksForManage(projectId);
    resetProjectTaskForm();
  } else {
    document.getElementById('projectName').value='';
    document.getElementById('projectDesc').value='';
    document.getElementById('projectStatus').value='Active';
    renderProjectManagersChecklist([]);
    tasksBtn.classList.add('hidden');
  }
  document.getElementById('projectModal').classList.remove('hidden');
}
function closeProjectModal() { closeModal('projectModal'); }

const submitProject = guardAsync(async function() {
  const id=document.getElementById('projectId').value;
  const body={
    name: document.getElementById('projectName').value.trim(),
    description: document.getElementById('projectDesc').value.trim()||null,
    status: document.getElementById('projectStatus').value,
    manager_ids: [...document.querySelectorAll('.project-manager-checkbox:checked')].map(b=>b.value),
  };
  if(!body.name){ alert('Project name is required'); return; }
  const url=id?`/api/projects/${id}`:'/api/projects';
  const res=await api(url,{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res?.ok){
    const proj=await res.json();
    if(!id){
      // Newly created — reopen in edit mode so tasks can be added right away
      await loadProjects();
      openProjectModal(proj.id);
    } else {
      closeProjectModal();
      loadProjects();
    }
  } else {
    const d=await res.json(); alert(d.detail||'Failed to save project');
  }
});

async function deleteProject(projectId) {
  if(!confirm('Delete this project?')) return;
  const res=await api(`/api/projects/${projectId}`,{method:'DELETE'});
  if(res?.ok||res?.status===204){ closeProjectModal(); loadProjects(); }
  else { const d=await res.json(); alert(d.detail||'Failed to delete project'); }
}

// ---------------------------------------------------------------------------
// Project Tasks (HR Manager)
// ---------------------------------------------------------------------------
let projectTasksCache=[];
const TASK_STATUS_COLORS={'Not Started':'status-neutral','In Progress':'status-info','Completed':'status-positive'};

async function loadProjectTasksForManage(projectId) {
  const res=await api(`/api/projects/${projectId}/tasks`);
  projectTasksCache=res?.ok?await res.json():[];
  // Keep the Projects list's pivot-table sub-rows in sync — this is the
  // one place task data actually changes, so it's also the one place
  // that needs to invalidate/refresh that cache (see toggleProjectExpand).
  projectTasksByProject[projectId]=projectTasksCache;
  if(expandedProjectIds.has(projectId)) renderProjectTable();
  document.getElementById('projectTaskList').innerHTML=projectTasksCache.length?projectTasksCache.map(t=>`
    <div class="border border-slate-200 rounded-lg p-2 text-sm">
      <div class="flex items-center justify-between gap-2">
        <span class="font-medium text-slate-700">${esc(t.name)}</span>
        <div class="flex items-center gap-1">
          ${t.open_to_all?'<span class="badge text-xs bg-blue-100 text-blue-700">ALL</span>':''}
          <span class="badge text-xs ${statusColor(TASK_STATUS_COLORS, t.status)}">${t.status}</span>
        </div>
      </div>
      <p class="text-xs text-slate-500 mt-0.5">
        ${t.start_date?`${fmtDate(t.start_date)} → ${t.end_date?fmtDate(t.end_date):'?'}`:'No dates set'}
        ${t.estimated_hours?` · ${t.logged_hours}/${t.estimated_hours} hrs logged`:` · ${t.logged_hours} hrs logged`}
      </p>
      <div class="flex gap-2 mt-1">
        <button onclick="editProjectTask(${t.id})" class="text-xs text-blue-600 hover:underline">Edit</button>
        <button onclick="deleteProjectTask(${projectId},${t.id})" class="text-xs text-red-600 hover:underline">Delete</button>
      </div>
    </div>`).join(''):'<p class="text-xs text-slate-400 text-center py-2">No tasks yet.</p>';
}

function resetProjectTaskForm() {
  document.getElementById('projectTaskId').value='';
  document.getElementById('projectTaskName').value='';
  document.getElementById('projectTaskDesc').value='';
  document.getElementById('projectTaskHours').value='';
  document.getElementById('projectTaskStart').value='';
  document.getElementById('projectTaskEnd').value='';
  document.getElementById('projectTaskStatus').value='Not Started';
  document.getElementById('taskAssignSection').classList.add('hidden');
  document.getElementById('taskAssignHint').classList.remove('hidden');
}

function editProjectTask(taskId) {
  const t=projectTasksCache.find(x=>x.id===taskId);
  if(!t) return;
  document.getElementById('projectTaskId').value=t.id;
  document.getElementById('projectTaskName').value=t.name;
  document.getElementById('projectTaskDesc').value=t.description||'';
  document.getElementById('projectTaskHours').value=t.estimated_hours||'';
  document.getElementById('projectTaskStart').value=t.start_date||'';
  document.getElementById('projectTaskEnd').value=t.end_date||'';
  document.getElementById('projectTaskStatus').value=t.status;
  showTaskAssignSection(t.id);
}

const submitProjectTask = guardAsync(async function() {
  const projectId=document.getElementById('projectId').value;
  const taskId=document.getElementById('projectTaskId').value;
  const name=document.getElementById('projectTaskName').value.trim();
  if(!name){ alert('Task name is required'); return; }
  const body={
    name,
    description: document.getElementById('projectTaskDesc').value.trim()||null,
    estimated_hours: parseFloat(document.getElementById('projectTaskHours').value)||null,
    start_date: document.getElementById('projectTaskStart').value||null,
    end_date: document.getElementById('projectTaskEnd').value||null,
    status: document.getElementById('projectTaskStatus').value,
  };
  const url=taskId?`/api/projects/${projectId}/tasks/${taskId}`:`/api/projects/${projectId}/tasks`;
  const res=await api(url,{method:taskId?'PUT':'POST',body:JSON.stringify(body)});
  if(res?.ok){
    const saved=await res.json();
    await loadProjectTasksForManage(parseInt(projectId));
    // Keep the form open on the just-saved task so team members can be assigned right away
    document.getElementById('projectTaskId').value=saved.id;
    showTaskAssignSection(saved.id);
  } else {
    const d=await res.json(); alert(d.detail||'Failed to save task');
  }
});

async function deleteProjectTask(projectId, taskId) {
  if(!confirm('Delete this task?')) return;
  const res=await api(`/api/projects/${projectId}/tasks/${taskId}`,{method:'DELETE'});
  if(res?.ok||res?.status===204){ loadProjectTasksForManage(projectId); resetProjectTaskForm(); }
  else { const d=await res.json(); alert(d.detail||'Failed to delete task'); }
}

// ---------------------------------------------------------------------------
// Task Assignments — per-team-member expected effort (start datetime + duration).
// Purely for capturing expected effort; actual timesheet logging is never
// capped by this (see addTimesheetEntry / My Timesheet).
// ---------------------------------------------------------------------------
async function showTaskAssignSection(taskId) {
  document.getElementById('taskAssignHint').classList.add('hidden');
  document.getElementById('taskAssignSection').classList.remove('hidden');
  await loadTaskAssignments(taskId);
}

function toggleTaskAssignAllMode() {
  const isAll=document.getElementById('taskAssignEmpId').value==='ALL';
  document.getElementById('taskAssignStart').disabled=isAll;
  document.getElementById('taskAssignDuration').disabled=isAll;
  document.getElementById('taskAssignStart').classList.toggle('opacity-50', isAll);
  document.getElementById('taskAssignDuration').classList.toggle('opacity-50', isAll);
}

async function loadTaskAssignments(taskId) {
  const projectId=document.getElementById('projectId').value;
  const task=projectTasksCache.find(t=>t.id===taskId);
  const openToAll=!!task?.open_to_all;
  document.getElementById('taskAssignOpenBanner').classList.toggle('hidden', !openToAll);

  const res=await api(`/api/projects/${projectId}/tasks/${taskId}/assignments`);
  const assignments=res?.ok?await res.json():[];
  document.getElementById('taskAssignList').innerHTML=(!openToAll && assignments.length)?assignments.map(a=>`
    <div class="flex items-center gap-2 py-1 border-b border-slate-100 text-xs">
      <span class="flex-1">${esc(displayName(a.full_name,a.preferred_name))}</span>
      <span class="text-slate-400">${fmtDate(a.start_datetime)}${a.start_datetime.includes('T')?', '+a.start_datetime.split('T')[1]:''} · ${a.duration_hours}h</span>
      <button onclick="removeTaskAssignment(${taskId},'${a.employee_id}')" class="text-slate-300 hover:text-red-500"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>`).join(''):(openToAll?'':'<p class="text-xs text-slate-400 text-center py-1">No one assigned yet.</p>');

  // Offer active employees not already assigned to this task, plus an "ALL" shortcut.
  // Fetched fresh rather than relying on the `employees` cache, which is only
  // populated once the Employees page has been visited this session.
  const empRes=await api('/api/employees');
  const allEmployees=empRes?.ok?await empRes.json():[];
  const assignedIds=new Set(assignments.map(a=>a.employee_id));
  const sel=document.getElementById('taskAssignEmpId');
  const available=allEmployees.filter(e=>e.status==='Active'&&!assignedIds.has(e.employee_id));
  const allOption=openToAll?'':'<option value="ALL">ALL — every employee</option>';
  sel.innerHTML=allOption+(available.length
    ? available.map(e=>`<option value="${e.employee_id}">${esc(displayName(e.full_name,e.preferred_name))}</option>`).join('')
    : (openToAll?'':'<option value="">All employees already assigned</option>'));
  toggleTaskAssignAllMode();
}

const addTaskAssignment = guardAsync(async function() {
  const projectId=document.getElementById('projectId').value;
  const taskId=document.getElementById('projectTaskId').value;
  const employeeId=document.getElementById('taskAssignEmpId').value;
  if(!employeeId){ alert('No project member available to assign. Add them as a project member first.'); return; }
  if(employeeId==='ALL'){
    const res=await api(`/api/projects/${projectId}/tasks/${taskId}/open-to-all`,{method:'PATCH',body:JSON.stringify({open_to_all:true})});
    if(res?.ok){
      const task=await res.json();
      const idx=projectTasksCache.findIndex(t=>t.id===task.id);
      if(idx>=0) projectTasksCache[idx]=task;
      loadTaskAssignments(parseInt(taskId));
    } else { const d=await res.json(); alert(d.detail||'Failed to open task to all employees'); }
    return;
  }
  const startDatetime=document.getElementById('taskAssignStart').value;
  const durationHours=parseFloat(document.getElementById('taskAssignDuration').value);
  if(!startDatetime||!durationHours){ alert('Start date/time and duration (hours) are required.'); return; }
  const res=await api(`/api/projects/${projectId}/tasks/${taskId}/assignments`,{method:'POST',body:JSON.stringify({employee_id:employeeId,start_datetime:startDatetime,duration_hours:durationHours})});
  if(res?.ok){
    document.getElementById('taskAssignStart').value='';
    document.getElementById('taskAssignDuration').value='';
    loadTaskAssignments(parseInt(taskId));
  } else {
    const d=await res.json(); alert(d.detail||'Failed to assign team member');
  }
});

async function removeTaskAssignment(taskId, employeeId) {
  const projectId=document.getElementById('projectId').value;
  await api(`/api/projects/${projectId}/tasks/${taskId}/assignments/${employeeId}`,{method:'DELETE'});
  loadTaskAssignments(taskId);
}

async function removeTaskOpenToAll() {
  const projectId=document.getElementById('projectId').value;
  const taskId=parseInt(document.getElementById('projectTaskId').value);
  const res=await api(`/api/projects/${projectId}/tasks/${taskId}/open-to-all`,{method:'PATCH',body:JSON.stringify({open_to_all:false})});
  if(res?.ok){
    const task=await res.json();
    const idx=projectTasksCache.findIndex(t=>t.id===task.id);
    if(idx>=0) projectTasksCache[idx]=task;
    loadTaskAssignments(taskId);
  }
}

// ---------------------------------------------------------------------------
// My Timesheet
// ---------------------------------------------------------------------------
function tsGetMonday(d) {
  const date=new Date(d);
  const day=date.getDay();
  const diff=(day===0?-6:1)-day; // shift to Monday
  date.setDate(date.getDate()+diff);
  date.setHours(0,0,0,0);
  return date;
}
function tsFmt(d) { return d.toISOString().slice(0,10); }

async function loadTimesheetPage() {
  if(!tsCurrentWeekStart) tsCurrentWeekStart=tsGetMonday(new Date());
  const res=await api('/api/projects/mine');
  myProjectsCache=res?.ok?await res.json():[];
  document.getElementById('tsEntryProject').innerHTML=myProjectsCache.length
    ? myProjectsCache.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')
    : '<option value="">No assigned projects</option>';
  await loadTsEntryTasks();
  await loadCurrentTimesheet();
}

async function loadTsEntryTasks() {
  const projectId=document.getElementById('tsEntryProject').value;
  const taskSel=document.getElementById('tsEntryTask');
  if(!projectId){ taskSel.innerHTML='<option value="">—</option>'; return; }
  const res=await api(`/api/projects/${projectId}/tasks`);
  const tasks=res?.ok?await res.json():[];
  taskSel.innerHTML=tasks.length
    ? tasks.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('')
    : '<option value="">No tasks defined for this project</option>';
}

function shiftTimesheetWeek(dir) {
  tsCurrentWeekStart.setDate(tsCurrentWeekStart.getDate()+dir*7);
  loadCurrentTimesheet();
}

async function loadCurrentTimesheet() {
  const start=tsFmt(tsCurrentWeekStart);
  const end=new Date(tsCurrentWeekStart); end.setDate(end.getDate()+6);
  const endStr=tsFmt(end);
  // fmtDate() here (not the raw ISO start/endStr, which the API call below
  // needs as-is) — matches every other date-range label in the app
  // (Payroll runs, Leave, PIP/Performance cycles, Employee contract dates
  // all render `${fmtDate(a)} → ${fmtDate(b)}`); this was the one place
  // that had been left showing the raw "YYYY-MM-DD" string instead.
  document.getElementById('timesheetWeekLabel').textContent=`${fmtDate(start)} → ${fmtDate(endStr)}`;

  const empId=currentUser?.employee_id;
  if(!empId){
    document.getElementById('timesheetEntryBody').innerHTML='';
    document.getElementById('timesheetEntryEmpty').classList.remove('hidden');
    document.getElementById('timesheetAddForm').classList.add('hidden');
    document.getElementById('timesheetSubmitBtn').classList.add('hidden');
    return;
  }
  const res=await api('/api/timesheets',{method:'POST',body:JSON.stringify({employee_id:empId,period_start:start,period_end:endStr})});
  const ts=await res.json();
  const detailRes=await api(`/api/timesheets/${ts.id}`);
  tsCurrentTimesheet=await detailRes.json();
  renderTimesheetEntries();
}

function renderTimesheetEntries() {
  const ts=tsCurrentTimesheet;
  const tbody=document.getElementById('timesheetEntryBody');
  const emptyEl=document.getElementById('timesheetEntryEmpty');
  const isDraft=ts.status==='Draft';

  if(!ts.entries.length){
    tbody.innerHTML='';
    emptyEl.classList.remove('hidden');
  } else {
    emptyEl.classList.add('hidden');
    tbody.innerHTML=ts.entries.map(e=>`
      <tr class="border-t border-slate-100">
        <td class="px-4 py-2">${fmtDate(e.date)}</td>
        <td class="px-4 py-2">${esc(e.project_name)}</td>
        <td class="px-4 py-2">${esc(e.task_name||'—')}</td>
        <td class="px-4 py-2">${e.hours}</td>
        <td class="px-4 py-2 text-slate-500">${esc(e.description||'')}</td>
        <td class="px-4 py-2 text-right">${isDraft?`<button onclick="deleteTimesheetEntry(${e.id})" class="text-slate-300 hover:text-red-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>`:''}</td>
      </tr>`).join('');
  }
  document.getElementById('timesheetTotalHours').textContent=ts.total_hours;

  const badgeWrap=document.getElementById('timesheetStatusBadgeWrap');
  badgeWrap.innerHTML=`<span class="badge ${statusColor(TS_STATUS_COLORS, ts.status)}">${ts.status}</span>${ts.notes?` <span class="text-xs text-slate-400 ml-1">${esc(ts.notes)}</span>`:''}`;

  document.getElementById('timesheetAddForm').classList.toggle('hidden', !isDraft);
  document.getElementById('timesheetSubmitBtn').classList.toggle('hidden', !isDraft);
  document.getElementById('tsEntryDate').value='';
  document.getElementById('tsEntryHours').value='';
  document.getElementById('tsEntryDesc').value='';
}

const addTimesheetEntry = guardAsync(async function() {
  const projectId=document.getElementById('tsEntryProject').value;
  if(!projectId){ alert('You have no assigned projects to log time against. Ask HR to add you to a project.'); return; }
  const taskId=document.getElementById('tsEntryTask').value;
  if(!taskId){ alert('This project has no tasks defined yet. Ask HR to add a task before logging time.'); return; }
  const date=document.getElementById('tsEntryDate').value;
  const hours=parseFloat(document.getElementById('tsEntryHours').value);
  if(!date||!hours){ alert('Date and hours are required.'); return; }
  const body={ project_id:parseInt(projectId), task_id:parseInt(taskId), date, hours, description:document.getElementById('tsEntryDesc').value.trim()||null };
  const res=await api(`/api/timesheets/${tsCurrentTimesheet.id}/entries`,{method:'POST',body:JSON.stringify(body)});
  if(res?.ok){
    const detailRes=await api(`/api/timesheets/${tsCurrentTimesheet.id}`);
    tsCurrentTimesheet=await detailRes.json();
    renderTimesheetEntries();
  } else {
    const d=await res.json(); alert(d.detail||'Failed to add entry');
  }
});

async function deleteTimesheetEntry(entryId) {
  await api(`/api/timesheets/${tsCurrentTimesheet.id}/entries/${entryId}`,{method:'DELETE'});
  const detailRes=await api(`/api/timesheets/${tsCurrentTimesheet.id}`);
  tsCurrentTimesheet=await detailRes.json();
  renderTimesheetEntries();
}

const submitTimesheet = guardAsync(async function() {
  if(!confirm('Submit this timesheet for approval? You will not be able to edit it afterwards.')) return;
  const res=await api(`/api/timesheets/${tsCurrentTimesheet.id}/status`,{method:'PATCH',body:JSON.stringify({status:'Submitted'})});
  if(res?.ok){ loadCurrentTimesheet(); }
  else { const d=await res.json(); alert(d.detail||'Failed to submit'); }
});

// ---------------------------------------------------------------------------
// Timesheet Approvals (manager / HR)
// ---------------------------------------------------------------------------
let tsApprovalRowsCache=[];
const tsApprovalList=createListState({sortKey:'period_start', sortDir:'desc'});

async function loadTimesheetApprovals() {
  const tbody=document.getElementById('timesheetApprovalTableBody');
  tbody.innerHTML='<tr><td colspan="4" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  let url='/api/timesheets';
  if(tsApprovalFilter) url+=`?status=${encodeURIComponent(tsApprovalFilter)}`;
  const res=await api(url);
  if(!res?.ok){ tbody.innerHTML=''; return; }
  tsApprovalRowsCache=await res.json();
  tsApprovalList.resetPage();
  renderTimesheetApprovalTable();
}

function setTimesheetApprovalSort(key) { tsApprovalList.setSort(key); renderTimesheetApprovalTable(); }
function setTimesheetApprovalPageSize(size) { tsApprovalList.setPageSize(size); renderTimesheetApprovalTable(); }
function timesheetApprovalPagePrev() { tsApprovalList.prevPage(); renderTimesheetApprovalTable(); }
function timesheetApprovalPageNext() { tsApprovalList.nextPage(tsApprovalRowsCache.length); renderTimesheetApprovalTable(); }

function renderTimesheetApprovalTable() {
  const tbody=document.getElementById('timesheetApprovalTableBody');
  const emptyEl=document.getElementById('timesheetApprovalEmpty');
  const pagination=document.getElementById('timesheetApprovalPagination');
  tsApprovalList.updateSortArrows('.ts-appr-sort-arrow');

  if(!tsApprovalRowsCache.length){ tbody.innerHTML=''; emptyEl?.classList.remove('hidden'); pagination?.classList.add('hidden'); return; }
  emptyEl?.classList.add('hidden');
  pagination?.classList.remove('hidden');
  const pageSizeEl=document.getElementById('timesheetApprovalPageSize');
  if(pageSizeEl) pageSizeEl.value=String(tsApprovalList.pageSize);

  const { pageItems, start, total }=tsApprovalList.view(tsApprovalRowsCache);
  const pageInfoEl=document.getElementById('timesheetApprovalPageInfo');
  if(pageInfoEl) pageInfoEl.textContent=`${start+1}-${Math.min(start+tsApprovalList.pageSize, total)} of ${total}`;

  tbody.innerHTML=pageItems.map(t=>`
    <tr class="cursor-pointer hover:bg-slate-50 transition" onclick="openTimesheetDetail(${t.id})">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(displayName(t.employee_name,t.employee_preferred_name))}</p>
        <p class="text-xs text-slate-500">${esc(t.department||'')}${t.designation?' · '+esc(t.designation):''}</p>
      </td>
      <td class="px-4 py-3 text-slate-600">
        ${fmtDate(t.period_start)} → ${fmtDate(t.period_end)}
        ${t.status==='Submitted' && !t.is_actionable ? `<p class="text-xs text-slate-400 mt-0.5">Pending with: ${esc(t.pending_with||'—')}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-right text-slate-600">${t.total_hours} hrs</td>
      <td class="px-4 py-3"><span class="badge ${statusColor(TS_STATUS_COLORS, t.status)} text-xs">${t.status}</span></td>
    </tr>`).join('');
}

function setTimesheetApprovalFilter(status) {
  tsApprovalFilter=status;
  document.querySelectorAll('.ts-appr-filter-btn').forEach(b=>b.classList.remove('ts-appr-filter-active'));
  event?.target?.classList?.add('ts-appr-filter-active');
  loadTimesheetApprovals();
}

async function openTimesheetDetail(tsId) {
  const res=await api(`/api/timesheets/${tsId}`);
  if(!res?.ok) return;
  const ts=await res.json();
  document.getElementById('timesheetDetailTitle').textContent=`Timesheet — ${fmtDate(ts.period_start)} to ${fmtDate(ts.period_end)}`;
  document.getElementById('timesheetDetailMeta').textContent=`Status: ${ts.status}${ts.submitted_at?' · Submitted '+fmtDate(ts.submitted_at):''}`;
  document.getElementById('timesheetDetailBody').innerHTML=ts.entries.map(e=>`
    <tr class="border-t border-slate-100">
      <td class="py-2">${fmtDate(e.date)}</td><td class="py-2">${esc(e.project_name)}</td>
      <td class="py-2">${esc(e.task_name||'—')}</td>
      <td class="py-2">${e.hours}</td><td class="py-2 text-slate-500">${esc(e.description||'')}</td>
    </tr>`).join('');
  document.getElementById('timesheetDetailTotal').textContent=`Total: ${ts.total_hours} hours`;
  const actions=document.getElementById('timesheetDetailActions');
  const cached=tsApprovalRowsCache.find(r=>r.id===ts.id);
  actions.innerHTML=ts.status!=='Submitted'?'':(!cached||cached.is_actionable)?`
    <button onclick="reviewTimesheet(${ts.id},'Approved')" class="btn-primary text-sm">Approve</button>
    <button onclick="reviewTimesheet(${ts.id},'Rejected')" class="btn-ghost text-sm text-red-600">Reject</button>
  `:`<p class="text-xs text-slate-400">Pending with: ${esc(cached.pending_with||'—')}</p>`;
  await loadTimesheetDetailOvertime(tsId);
  document.getElementById('timesheetDetailModal').classList.remove('hidden');
}

const OT_STATUS_COLORS={'Pending':'status-pending','Approved':'status-positive','Rejected':'status-negative'};

async function loadTimesheetDetailOvertime(tsId) {
  const wrap=document.getElementById('timesheetDetailOvertimeWrap');
  const list=document.getElementById('timesheetDetailOvertimeList');
  const res=await api(`/api/timesheets/${tsId}/overtime`);
  const records=res?.ok?await res.json():[];
  if(!records.length){ wrap.classList.add('hidden'); list.innerHTML=''; return; }
  wrap.classList.remove('hidden');
  list.innerHTML=records.map(o=>`
    <div class="flex items-center gap-3 bg-slate-50 rounded-lg px-3 py-2">
      <span class="text-sm text-slate-700 shrink-0">${fmtDate(o.work_date)}</span>
      <span class="text-xs text-slate-500 shrink-0">${o.logged_hours}h logged, ${o.threshold_hours}h normal</span>
      <span class="text-sm font-medium text-amber-700 shrink-0">+${o.overtime_hours}h OT</span>
      <span class="badge ${statusColor(OT_STATUS_COLORS, o.status)} text-xs shrink-0">${o.status}</span>
      <span class="flex-1"></span>
      ${o.status==='Pending'?`
        <button onclick="reviewOvertime(${o.id},${tsId},'Approved')" class="btn-primary text-xs px-2 py-1">Approve</button>
        <button onclick="reviewOvertime(${o.id},${tsId},'Rejected')" class="btn-ghost text-xs px-2 py-1 text-red-600">Reject</button>
      `:''}
    </div>`).join('');
}

async function reviewOvertime(recordId, tsId, status) {
  const res=await api(`/api/overtime/${recordId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  if(res?.ok){ loadTimesheetDetailOvertime(tsId); }
  else { const d=await res.json(); alert(d.detail||'Failed to update overtime record'); }
}

// ---------------------------------------------------------------------------
// My Overtime (employee)
// ---------------------------------------------------------------------------
async function loadMyOvertimePage() {
  const listEl=document.getElementById('myOvertimeList');
  const emptyEl=document.getElementById('myOvertimeEmpty');
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  const res=await api('/api/overtime');
  const records=res?.ok?await res.json():[];
  if(!records.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=records.map(o=>`
    <div class="bg-white border border-slate-200 rounded-xl p-4 flex items-center gap-3">
      <div class="flex-1">
        <p class="font-medium text-slate-800">${fmtDate(o.work_date)}</p>
        <p class="text-xs text-slate-500">${o.logged_hours}h logged vs ${o.threshold_hours}h normal — <span class="font-medium text-amber-700">${o.overtime_hours}h overtime</span></p>
        ${o.status==='Approved'?`<p class="text-xs text-green-700 mt-1">${o.conversion_mode==='leave'?`+${o.leave_days_credited} day(s) credited`:`${fmtCurrency(o.pay_amount)} tracked`}</p>`:''}
      </div>
      <span class="badge ${statusColor(OT_STATUS_COLORS, o.status)} text-xs">${o.status}</span>
    </div>`).join('');
}
function closeTimesheetDetailModal() { closeModal('timesheetDetailModal'); }

async function reviewTimesheet(tsId, status) {
  const res=await api(`/api/timesheets/${tsId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  if(res?.ok){ closeTimesheetDetailModal(); loadTimesheetApprovals(); }
  else { const d=await res.json(); alert(d.detail||'Failed to update'); }
}

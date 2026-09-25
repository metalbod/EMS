// Timesheet / Projects
// ---------------------------------------------------------------------------
let projectsCache=[], myProjectsCache=[], projectFilter='', projectSearchTerm='';
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
// My Timesheet's weekly grid (rows = distinct project/task the employee
// picked, columns = the 7 days) — see loadCurrentTimesheet/renderTimesheetGrid
// below. tsGridRows holds the editable draft state (rebuilt fresh from
// tsCurrentTimesheet.entries on every load — never trusted stale across a
// save); tsPendingDeleteEntryIds queues entries whose row was removed in
// this draft, applied on the next Save Week alongside whatever else changed.
let tsGridRows=[], tsPendingDeleteEntryIds=[], tsWeekDates=[];
let tsApprovalFilter='Submitted', tsApprovalEmployeeFilter='', tsApprovalPeriodFrom='', tsApprovalPeriodTo='', tsApprovalProjectFilter='';
let tsApprovalEmployeeOptionsBuilt=false, tsApprovalProjectOptionsBuilt=false;
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
  {key:'customer', label:'Customer'},
  {key:'status', label:'Status'},
  {key:'task_count', label:'Tasks'},
  {key:'member_count', label:'Team'},
  {key:'total_allocated_hours', label:'Allocated'},
  {key:'total_logged_hours', label:'Clocked'},
];

async function loadProjects() {
  const listEl=document.getElementById('projectList');
  const emptyEl=document.getElementById('projectEmpty');
  listEl.innerHTML='<tr><td colspan="8" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  let url='/api/projects';
  if(projectFilter) url+=`?status=${encodeURIComponent(projectFilter)}`;
  const res=await api(url);
  if(!res?.ok){ listEl.innerHTML=''; return; }
  const rows=await res.json();
  projectsCache=rows;
  populateProjectCustomerOptions();
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); renderProjectTableHead(); return; }
  emptyEl?.classList.add('hidden');
  renderProjectTableHead();
  renderProjectTable();
}

// Rebuilds the Customer field's <datalist> from every distinct customer
// name already tagged on a project in this institution (projectsCache),
// so typing in the modal suggests previously-used names without a
// dedicated customers table/endpoint. Cheap to just rebuild wholesale
// each time loadProjects() runs — this list is never large enough to
// warrant diffing.
function populateProjectCustomerOptions() {
  const dl=document.getElementById('projectCustomerOptions');
  if(!dl) return;
  const names=[...new Set(projectsCache.map(p=>(p.customer||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  dl.innerHTML=names.map(n=>`<option value="${esc(n)}"></option>`).join('');
}

function renderProjectTableHead() {
  document.getElementById('projectTableHead').innerHTML=PROJECT_TABLE_COLUMNS.map(c=>{
    const active=projectList.sortKey===c.key;
    const arrow=active?(projectList.sortDir==='asc'?'▲':'▼'):'';
    return `<th class="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide cursor-pointer select-none hover:text-slate-700" onclick="setProjectSort('${c.key}')">${c.label} <span class="text-blue-600">${arrow}</span></th>`;
  }).join('') + '<th class="px-4 py-2.5"></th>';
}

function setProjectSort(key) {
  projectList.setSort(key);
  renderProjectTableHead();
  renderProjectTable();
}

// Client-side only — projectsCache already holds every project the status
// filter matched (createListState here is sort-only, pageSize:10000, no
// server round-trip), so narrowing further by name/description as the
// list grows doesn't need its own API call either. Case-insensitive by
// virtue of lower-casing both sides before comparing.
function filterProjectsBySearch(term) {
  projectSearchTerm=term;
  renderProjectTable();
}

function renderProjectTable() {
  const listEl=document.getElementById('projectList');
  const STATUS_COLORS={'Active':'status-positive','On Hold':'status-pending','Completed':'status-neutral'};
  const term=projectSearchTerm.trim().toLowerCase();
  const searched=term?projectsCache.filter(p=>(p.name||'').toLowerCase().includes(term)||(p.description||'').toLowerCase().includes(term)||(p.customer||'').toLowerCase().includes(term)):projectsCache;
  const { pageItems: sorted } = projectList.view(searched);
  // loadProjects() already handled the "no projects at all" empty state
  // (projectEmpty) before ever calling this function, so reaching here
  // with zero rows only happens when a search term filtered everything
  // out — a different message, shown inline in the table itself.
  if(!sorted.length && term){
    listEl.innerHTML=`<tr><td colspan="8" class="text-slate-400 text-sm text-center py-8">No projects match "${esc(projectSearchTerm.trim())}".</td></tr>`;
    return;
  }
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
            <div class="flex items-center gap-1.5">
              <p class="font-medium text-slate-800 truncate">${esc(p.name)}</p>
              ${p.is_open_to_all?'<span class="badge text-xs bg-blue-100 text-blue-700 shrink-0" title="Any employee can log time here, no membership needed">ALL</span>':''}
              ${p.is_billable?'<span class="badge text-xs bg-emerald-100 text-emerald-700 shrink-0">Billable</span>':''}
            </div>
            <p class="text-xs text-slate-400 line-clamp-1">${esc(p.description||'')}</p>
          </div>
        </div>
      </td>
      <td class="px-4 py-3 text-slate-600">${p.customer?esc(p.customer):'<span class="text-slate-300">—</span>'}</td>
      <td class="px-4 py-3"><span class="badge text-xs ${statusColor(STATUS_COLORS, p.status)}">${p.status}</span></td>
      <td class="px-4 py-3 text-slate-600">${p.task_count}</td>
      <td class="px-4 py-3 text-slate-600">${p.member_count}</td>
      <td class="px-4 py-3 text-slate-600">${p.total_allocated_hours}h</td>
      <td class="px-4 py-3 text-slate-600">${p.total_logged_hours}h</td>
      <td class="px-4 py-3 text-right">
        <button onclick="event.stopPropagation();openDuplicateProjectModal(${p.id})" class="text-slate-400 hover:text-slate-600 p-1" title="Duplicate project">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V5a2 2 0 012-2h9a2 2 0 012 2v9a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v9a2 2 0 002 2h9a2 2 0 002-2v-2M8 7h6a2 2 0 012 2v6"/></svg>
        </button>
      </td>
    </tr>${expanded?projectTaskSubRows(p.id):''}`;
  }).join('');
}

// Pivot-table task sub-rows for one project — see toggleProjectExpand.
// Purely informational (no click handler): task editing stays in the
// existing Edit Project modal's Tasks tab, not duplicated here.
function projectTaskSubRows(projectId) {
  const tasks=projectTasksByProject[projectId];
  if(tasks===undefined) {
    return `<tr class="bg-slate-50/60"><td colspan="8" class="pl-12 pr-4 py-2.5 text-xs text-slate-400">Loading tasks…</td></tr>`;
  }
  if(!tasks.length) {
    return `<tr class="bg-slate-50/60"><td colspan="8" class="pl-12 pr-4 py-2.5 text-xs text-slate-400">No tasks yet.</td></tr>`;
  }
  return tasks.map(t=>`
    <tr class="bg-slate-50/60 border-t border-slate-100">
      <td class="pl-12 pr-4 py-2.5">
        <div class="flex items-center gap-2 min-w-0">
          <span class="text-slate-300 shrink-0">↳</span>
          <span class="text-slate-700 truncate">${esc(t.name)}</span>
        </div>
      </td>
      <td class="px-4 py-2.5 text-slate-300">—</td>
      <td class="px-4 py-2.5"><span class="badge text-xs ${statusColor(TASK_STATUS_COLORS, t.status)}">${t.status}</span></td>
      <td class="px-4 py-2.5 text-slate-300">—</td>
      <td class="px-4 py-2.5 text-slate-300">—</td>
      <td class="px-4 py-2.5 text-slate-500">${t.estimated_hours?t.estimated_hours+'h':'—'}</td>
      <td class="px-4 py-2.5 text-slate-500">${t.logged_hours}h</td>
      <td class="px-4 py-2.5"></td>
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
//
// Checks u.roles (the full set of capability checkboxes on their user
// account — Settings > Users' "Roles" checklist), NOT u.role (just
// whichever one is currently their "Active / Primary Role", the landing
// view Switch Active Role toggles between). A user can hold Manager
// alongside Employee and default to Employee as their day-to-day view —
// they still hold real Manager-tier capability, so they still belong in
// this picker. Checking only the single active role wrongly excluded
// exactly that case.
async function loadProjectManagerEligibility() {
  const res=await api('/api/users');
  const list=res?.ok?await res.json():[];
  projectManagerEligibleIds=new Set(
    list.filter(u=>u.is_active && u.employee_id && (u.roles||[u.role]).some(r=>PROJECT_MANAGER_ELIGIBLE_ROLES.includes(r)))
      .map(u=>u.employee_id)
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

// Team Members — same searchable checkbox-list pattern as Project
// Manager(s) above, but with no role-eligibility filter: this is the
// project's timesheet membership roster (see routers/projects.py's
// add_timesheet_entry), open to any active employee, not just
// manager-tier ones.
function renderProjectMembersChecklist(selectedIds) {
  const wrap=document.getElementById('projectMembersList');
  // Plus anyone already a member even if their employee record is no
  // longer Active (deactivated after being added) — same reasoning as
  // the Project Manager(s) picker: an unrelated future save can't
  // silently drop them just because the picker itself wouldn't offer
  // them to newly add.
  const active=(employees||[]).filter(e=>e.status==='Active' || selectedIds.includes(e.employee_id));
  wrap.innerHTML=active.map(e=>{
    const label=`${displayName(e.full_name,e.preferred_name)} (${e.employee_id})`;
    return `
    <label class="project-member-option flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 cursor-pointer" data-label="${esc(label)}" data-department="${esc(e.department||'')}">
      <input type="checkbox" class="project-member-checkbox" value="${e.employee_id}" ${selectedIds.includes(e.employee_id)?'checked':''} onchange="syncProjectMembersSelectAll()"/>
      ${esc(label)}
    </label>`;
  }).join('') + `<div id="projectMembersNoMatch" class="hidden text-center text-xs text-slate-400 py-3">No matches</div>`;
  const searchEl=document.getElementById('projectMembersSearch');
  if(searchEl) searchEl.value='';
  populateProjectMembersDeptSelect();
  filterProjectMemberOptions();
}

// Distinct, non-blank department names among the employees actually
// offered in the checklist above (not the whole institution — an
// employee not Active/not already a member never gets a checkbox here,
// so their department shouldn't appear as a pickable shortcut either).
// department is free text (no canonical list anywhere in this app — see
// employees.department), so this is sourced the same way
// attendance.js's Attendance Rule "Department" scope already does: a
// distinct-and-sort over whatever's actually in use.
function populateProjectMembersDeptSelect() {
  const sel=document.getElementById('projectMembersDeptSelect');
  if(!sel) return;
  const depts=[...new Set(
    [...document.querySelectorAll('.project-member-option')].map(opt=>opt.dataset.department).filter(Boolean)
  )].sort((a,b)=>a.localeCompare(b));
  sel.innerHTML='<option value="">+ Add department…</option>' + depts.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');
}

// Checks every listed employee in the chosen department — deliberately
// ignoring the current search term/hidden state (unlike Select All,
// which only acts on what's currently visible) so picking a department
// always adds everyone in it, not just whoever the search box happens
// to be showing. Only ever adds — never unchecks anyone — so this
// composes with manual checks and with picking further departments.
function addProjectMembersByDepartment(dept) {
  if(!dept) return;
  document.querySelectorAll('.project-member-option').forEach(opt=>{
    if(opt.dataset.department===dept) opt.querySelector('.project-member-checkbox').checked=true;
  });
  syncProjectMembersSelectAll();
}

function filterProjectMemberOptions() {
  const q=document.getElementById('projectMembersSearch')?.value||'';
  const opts=[...document.querySelectorAll('.project-member-option')];
  const matched=new Set(filterEmployeeOptions(
    opts.map(el=>({value: el.querySelector('.project-member-checkbox').value, label: el.dataset.label})),
    q
  ).map(o=>o.value));
  let visibleCount=0;
  opts.forEach(opt=>{
    const match=matched.has(opt.querySelector('.project-member-checkbox').value);
    opt.classList.toggle('hidden', !match);
    if(match) visibleCount++;
  });
  document.getElementById('projectMembersNoMatch')?.classList.toggle('hidden', visibleCount>0);
  syncProjectMembersSelectAll();
}

function visibleProjectMemberCheckboxes() {
  return [...document.querySelectorAll('.project-member-option:not(.hidden) .project-member-checkbox')];
}

function syncProjectMembersSelectAll() {
  const boxes=visibleProjectMemberCheckboxes();
  document.getElementById('projectMembersSelectAll').checked = boxes.length>0 && boxes.every(b=>b.checked);
}

function toggleAllProjectMembers() {
  const checked=document.getElementById('projectMembersSelectAll').checked;
  visibleProjectMemberCheckboxes().forEach(b=>b.checked=checked);
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
    document.getElementById('projectCustomer').value=p?.customer||'';
    document.getElementById('projectStatus').value=p?.status||'Active';
    document.getElementById('projectStart').value=p?.start_date||'';
    document.getElementById('projectEnd').value=p?.end_date||'';
    renderProjectManagersChecklist(p?.manager_ids||[]);
    renderProjectMembersChecklist(p?.member_ids||[]);
    document.getElementById('projectOpenToAll').checked=!!p?.is_open_to_all;
    document.getElementById('projectBillable').checked=!!p?.is_billable;
    tasksBtn.classList.remove('hidden');
    await loadProjectTasksForManage(projectId);
    resetProjectTaskForm();
  } else {
    document.getElementById('projectName').value='';
    document.getElementById('projectDesc').value='';
    document.getElementById('projectCustomer').value='';
    document.getElementById('projectStatus').value='Active';
    document.getElementById('projectStart').value='';
    document.getElementById('projectEnd').value='';
    renderProjectManagersChecklist([]);
    renderProjectMembersChecklist([]);
    document.getElementById('projectOpenToAll').checked=false;
    document.getElementById('projectBillable').checked=false;
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
    customer: document.getElementById('projectCustomer').value.trim()||null,
    status: document.getElementById('projectStatus').value,
    start_date: document.getElementById('projectStart').value||null,
    end_date: document.getElementById('projectEnd').value||null,
    manager_ids: [...document.querySelectorAll('.project-manager-checkbox:checked')].map(b=>b.value),
    member_ids: [...document.querySelectorAll('.project-member-checkbox:checked')].map(b=>b.value),
    is_open_to_all: document.getElementById('projectOpenToAll').checked,
    is_billable: document.getElementById('projectBillable').checked,
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
// Duplicate Project — clones a project under a new name. A "fresh start"
// clone (new project always Active, copied tasks reset to Not Started with
// no dates — see routers/projects.py's duplicate_project), scoped by which
// of Tasks/Members to bring along. Managers + Team Members travel together
// as one "Members" unit.
// ---------------------------------------------------------------------------
let duplicatingProjectId=null;

function openDuplicateProjectModal(projectId) {
  const p=projectsCache.find(x=>x.id===projectId);
  if(!p) return;
  duplicatingProjectId=projectId;
  document.getElementById('dupProjectSourceName').textContent=p.name;
  document.getElementById('dupProjectName').value=`${p.name} (Copy)`;
  document.querySelector('input[name="dupProjectScope"][value="tasks_and_members"]').checked=true;
  document.getElementById('dupProjectModal').classList.remove('hidden');
}
function closeDuplicateProjectModal() { closeModal('dupProjectModal'); duplicatingProjectId=null; }

const submitDuplicateProject = guardAsync(async function() {
  const name=document.getElementById('dupProjectName').value.trim();
  if(!name){ alert('Project name is required'); return; }
  const duplicate_scope=document.querySelector('input[name="dupProjectScope"]:checked').value;
  const res=await api(`/api/projects/${duplicatingProjectId}/duplicate`,{method:'POST',body:JSON.stringify({name,duplicate_scope})});
  if(res?.ok){
    const proj=await res.json();
    closeDuplicateProjectModal();
    await loadProjects();
    openProjectModal(proj.id);
  } else {
    const d=await res.json(); alert(d.detail||'Failed to duplicate project');
  }
});

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
    await loadProjectTasksForManage(parseInt(projectId));
    resetProjectTaskForm();
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
  await loadCurrentTimesheet();
}

// Standard Weekly Hours (Settings -> Attendance, next to Shifts/Rules —
// see routers/timesheets.py's TIMESHEET_SETTINGS_MANAGE_ROLES) — the
// "expected hours" baseline behind My Timesheet's Missing/short hours
// line and auto-populated holiday/leave rows.
async function loadTimesheetSettings() {
  const res=await api('/api/timesheets/settings');
  const input=document.getElementById('tsStandardWeeklyHours');
  if(!input) return;
  input.value=res?.ok ? (await res.json()).standard_weekly_hours : 40;
}

const saveTimesheetSettings = guardAsync(async function() {
  const msg=document.getElementById('tsSettingsMsg');
  const hours=parseFloat(document.getElementById('tsStandardWeeklyHours').value);
  if(!hours || hours<=0){ msg.textContent='Enter a value greater than 0.'; msg.className='text-xs text-red-600'; return; }
  const res=await api('/api/timesheets/settings',{method:'PUT',body:JSON.stringify({standard_weekly_hours:hours})});
  if(res?.ok){
    msg.textContent='Saved.';
    msg.className='text-xs text-green-600';
  } else {
    const d=await res.json();
    msg.textContent=apiErrorText(d.detail,'Failed to save.');
    msg.className='text-xs text-red-600';
  }
});

function shiftTimesheetWeek(dir) {
  tsCurrentWeekStart.setDate(tsCurrentWeekStart.getDate()+dir*7);
  loadCurrentTimesheet();
}

async function loadCurrentTimesheet() {
  const start=tsFmt(tsCurrentWeekStart);
  const end=new Date(tsCurrentWeekStart); end.setDate(end.getDate()+6);
  const endStr=tsFmt(end);
  tsWeekDates=[...Array(7)].map((_,i)=>{ const d=new Date(tsCurrentWeekStart); d.setDate(d.getDate()+i); return tsFmt(d); });
  // fmtDate() here (not the raw ISO start/endStr, which the API call below
  // needs as-is) — matches every other date-range label in the app
  // (Payroll runs, Leave, PIP/Performance cycles, Employee contract dates
  // all render `${fmtDate(a)} → ${fmtDate(b)}`); this was the one place
  // that had been left showing the raw "YYYY-MM-DD" string instead.
  document.getElementById('timesheetWeekLabel').textContent=`${fmtDate(start)} → ${fmtDate(endStr)}`;

  const empId=currentUser?.employee_id;
  if(!empId){
    document.getElementById('tsGridBody').innerHTML='';
    document.getElementById('tsGridHead').innerHTML='';
    document.getElementById('tsGridFoot').innerHTML='';
    document.getElementById('tsGridAddRowBtn').classList.add('hidden');
    document.getElementById('tsWeekDescWrap').classList.add('hidden');
    document.getElementById('timesheetSubmitBtn').classList.add('hidden');
    return;
  }
  const res=await api('/api/timesheets',{method:'POST',noBusy:true,body:JSON.stringify({employee_id:empId,period_start:start,period_end:endStr})});
  const ts=await res.json();
  const detailRes=await api(`/api/timesheets/${ts.id}`);
  tsCurrentTimesheet=await detailRes.json();
  tsPendingDeleteEntryIds=[];
  tsGridRows=_tsBuildGridRowsFromEntries(tsCurrentTimesheet.entries);
  renderTimesheetGrid();
}

// Groups tsCurrentTimesheet.entries (one row per logged date+project+task —
// still the real underlying shape) into one grid row per distinct
// project/task, one cell per day. `value`/`original_value` start equal;
// only `value` is mutated by the user, so Save Week can diff against
// `original_value` to know what actually changed.
function _tsBuildGridRowsFromEntries(entries) {
  const byKey={};
  (entries||[]).forEach(e=>{
    const key=`${e.project_id}:${e.task_id}`;
    if(!byKey[key]) byKey[key]={project_id:e.project_id, task_id:e.task_id, project_name:e.project_name, task_name:e.task_name, cells:{}};
    byKey[key].cells[e.date]={entry_id:e.id, value:e.hours, original_value:e.hours};
  });
  return Object.values(byKey);
}

// Mirrors routers/timesheets.py's _check_timesheet_entry_editable: a
// timesheet never split per-project is open exactly while Draft; once
// split, a project is locked only while Submitted/Approved — Rejected
// (or never-submitted) is open again for just that project.
function _tsIsProjectEditable(ts, projectId) {
  const approvals=ts.project_approvals||[];
  if(!approvals.length) return ts.status==='Draft';
  const row=approvals.find(p=>p.project_id===projectId);
  return !row || row.status==='Rejected';
}

function _tsDayHeaderLabel(dateStr) {
  const d=new Date(dateStr+'T00:00:00');
  const WD=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  return `${WD[d.getDay()]}<br>${String(d.getDate()).padStart(2,'0')}`;
}

function renderTimesheetGridHead() {
  document.getElementById('tsGridHead').innerHTML=`<tr>
    <th class="px-3 py-2 text-left" style="min-width:220px">Project / Task</th>
    ${tsWeekDates.map(d=>`<th class="px-1 py-2 text-center w-14">${_tsDayHeaderLabel(d)}</th>`).join('')}
    <th class="px-3 py-2 text-right w-20">Total</th>
    <th class="w-8"></th>
  </tr>`;
}

// Public-holiday/approved-leave rows — computed fresh by GET
// /api/timesheets/{id} (routers/timesheets.py's _weekly_hours_breakdown)
// every time the screen loads, never written to timesheet_entries, so
// they're always read-only here. One row per category (not one per
// holiday/leave instance) — if two different leave types land in the
// same week, both fit in the one "Approved Leave" row, each day-cell's
// own tooltip naming which one applies that day.
function _tsAutoRowsHtml(ts) {
  const byType={holiday:{}, leave:{}};
  (ts.auto_entries||[]).forEach(e=>{ byType[e.type][e.date]=e; });
  return ['holiday','leave'].map(type=>{
    const byDate=byType[type];
    if(!Object.keys(byDate).length) return '';
    const label=type==='holiday'?'Public Holidays':'Approved Leave';
    let total=0;
    const cells=tsWeekDates.map(d=>{
      const e=byDate[d];
      if(!e) return `<td class="px-1 py-2 text-center text-slate-300">—</td>`;
      total+=e.hours;
      return `<td class="px-1 py-2 text-center" title="${esc(e.label)}">${e.hours}</td>`;
    }).join('');
    return `<tr class="bg-slate-50/70 text-slate-500 italic border-t border-slate-100">
      <td class="px-3 py-2">${label}</td>
      ${cells}
      <td class="px-3 py-2 text-right">${total}</td>
      <td></td>
    </tr>`;
  }).join('');
}

function _tsGridRowHtml(row, idx) {
  const ts=tsCurrentTimesheet;
  const isNew=!row.project_id;
  const editable=isNew || _tsIsProjectEditable(ts, row.project_id);
  let rowTotal=0;
  const cells=tsWeekDates.map(d=>{
    const cell=row.cells[d]||{};
    rowTotal+=parseFloat(cell.value)||0;
    if(!editable) return `<td class="px-1 py-2 text-center text-slate-600">${cell.value?cell.value:'—'}</td>`;
    return `<td class="px-1 py-1 text-center"><input type="number" step="0.5" min="0" max="24" class="ts-grid-cell inp text-sm text-center px-1 py-1" style="width:100%" value="${cell.value?cell.value:''}" data-row="${idx}" data-date="${d}" oninput="_tsOnCellInput(${idx}, '${d}', this.value)"/></td>`;
  }).join('');
  const projectTaskCell=isNew
    ? `<div class="flex flex-col gap-1">
        <select class="inp text-xs" onchange="_tsOnRowProjectChange(${idx}, this.value)">
          <option value="">Select project…</option>
          ${(myProjectsCache||[]).map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')}
        </select>
        <select id="tsGridRowTaskSelect${idx}" class="inp text-xs" onchange="_tsOnRowTaskChange(${idx}, this.value)" ${row.project_id?'':'disabled'}>
          <option value="">Select task…</option>
        </select>
      </div>`
    : `<div class="font-medium text-slate-800">${esc(row.project_name)}</div><div class="text-xs text-slate-500">${esc(row.task_name||'—')}</div>${!editable?'<span class="badge text-xs bg-slate-100 text-slate-500 mt-0.5">Locked</span>':''}`;
  return `<tr class="border-t border-slate-100" data-row-index="${idx}">
    <td class="px-3 py-2">${projectTaskCell}</td>
    ${cells}
    <td class="px-3 py-2 text-right font-medium">${rowTotal||''}</td>
    <td class="text-center">${editable?`<button onclick="removeTimesheetGridRow(${idx})" class="text-slate-300 hover:text-red-500" title="Remove row"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>`:''}</td>
  </tr>`;
}

function renderTimesheetGrid() {
  const ts=tsCurrentTimesheet;
  renderTimesheetGridHead();
  document.getElementById('tsGridBody').innerHTML=_tsAutoRowsHtml(ts) + tsGridRows.map((r,i)=>_tsGridRowHtml(r,i)).join('');

  const dayTotals=tsWeekDates.map(d=>tsGridRows.reduce((s,r)=>s+(parseFloat(r.cells[d]?.value)||0),0));
  const grandTotal=dayTotals.reduce((s,v)=>s+v,0);
  const missing=ts.missing_hours||0;
  document.getElementById('tsGridFoot').innerHTML=`
    <tr class="border-t border-slate-200 bg-slate-50 font-medium">
      <td class="px-3 py-2">Total</td>
      ${dayTotals.map(v=>`<td class="px-1 py-2 text-center">${v||''}</td>`).join('')}
      <td class="px-3 py-2 text-right">${grandTotal}</td>
      <td></td>
    </tr>
    <tr id="timesheetMissingRow" class="${missing>0?'':'hidden'} border-t border-slate-100">
      <td class="px-3 py-2 text-amber-700" colspan="8">Missing / short hours</td>
      <td id="timesheetMissingHours" class="px-3 py-2 text-amber-700 font-medium text-right">${missing}</td>
      <td></td>
    </tr>`;

  const badgeWrap=document.getElementById('timesheetStatusBadgeWrap');
  badgeWrap.innerHTML=`<span class="badge ${statusColor(TS_STATUS_COLORS, ts.status)}">${ts.status}</span>${ts.notes?` <span class="text-xs text-slate-400 ml-1">${esc(ts.notes)}</span>`:''}`;

  const isDraftOrOpen=tsGridRows.some((r,i)=>!r.project_id || _tsIsProjectEditable(ts, r.project_id)) || ts.status==='Draft';
  document.getElementById('tsGridAddRowBtn').classList.toggle('hidden', !isDraftOrOpen);
  document.getElementById('tsGridSaveBtn').classList.toggle('hidden', !isDraftOrOpen);
  document.getElementById('timesheetSubmitBtn').classList.toggle('hidden', ts.status!=='Draft');
  document.getElementById('tsWeekDescription').value=ts.description||'';
  document.getElementById('tsWeekDescription').disabled=!isDraftOrOpen;
  document.getElementById('tsGridSaveMsg').textContent='';
}

function _tsOnCellInput(rowIdx, date, value) {
  const row=tsGridRows[rowIdx];
  if(!row.cells[date]) row.cells[date]={entry_id:null, original_value:0};
  row.cells[date].value=value;
}

async function _tsOnRowProjectChange(rowIdx, projectId) {
  const row=tsGridRows[rowIdx];
  row.project_id=projectId?parseInt(projectId):null;
  // _tsGridRowHtml switches a row from its picker dropdowns to plain-text
  // display the moment project_id+task_id are both set (isNew becomes
  // false) — project_name/task_name have to be captured right here, not
  // left to be filled in later, or that display mode renders blank/'—'.
  row.project_name=projectId ? (myProjectsCache||[]).find(p=>p.id===row.project_id)?.name : null;
  row.task_id=null;
  row.task_name=null;
  const taskSel=document.getElementById(`tsGridRowTaskSelect${rowIdx}`);
  if(!projectId){ taskSel.innerHTML='<option value="">Select task…</option>'; taskSel.disabled=true; return; }
  taskSel.disabled=false;
  taskSel.innerHTML='<option value="">Loading…</option>';
  const res=await api(`/api/projects/${projectId}/tasks`);
  const tasks=res?.ok?await res.json():[];
  row._availableTasks=tasks; // so _tsOnRowTaskChange can resolve the chosen task's name below
  taskSel.innerHTML=tasks.length
    ? '<option value="">Select task…</option>'+tasks.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('')
    : '<option value="">No tasks defined for this project</option>';
}

function _tsOnRowTaskChange(rowIdx, taskId) {
  const row=tsGridRows[rowIdx];
  if(!taskId){ row.task_id=null; row.task_name=null; return; }
  const dup=tsGridRows.some((r,i)=>i!==rowIdx && r.project_id===row.project_id && r.task_id===parseInt(taskId));
  if(dup){
    alert('This project/task is already a row above — enter hours there instead of adding a duplicate row.');
    document.getElementById(`tsGridRowTaskSelect${rowIdx}`).value='';
    row.task_id=null;
    row.task_name=null;
    return;
  }
  row.task_id=parseInt(taskId);
  row.task_name=(row._availableTasks||[]).find(t=>t.id===row.task_id)?.name || null;
  renderTimesheetGrid(); // collapse straight to the ready-to-fill row now that both are picked, instead of waiting for some later, unrelated render
}

function addTimesheetGridRow() {
  tsGridRows.push({project_id:null, task_id:null, cells:{}});
  renderTimesheetGrid();
}

// Removing a row never fires a request itself — it just drops the row
// from view and queues whatever entries it had for deletion, applied
// (along with every other change) the next time Save Week runs. A
// brand-new, never-saved row has nothing to queue.
function removeTimesheetGridRow(idx) {
  const row=tsGridRows[idx];
  Object.values(row.cells).forEach(c=>{ if(c.entry_id) tsPendingDeleteEntryIds.push(c.entry_id); });
  tsGridRows.splice(idx,1);
  renderTimesheetGrid();
}

const saveTimesheetGrid = guardAsync(async function() {
  const ts=tsCurrentTimesheet;

  // A row with hours typed in but no project/task chosen yet would
  // otherwise be silently skipped below (no request to fail, no error
  // to show) — catch it before anything saves so the hours aren't lost
  // without the person realizing why.
  const incompleteRow=tsGridRows.some(row => (!row.project_id || !row.task_id) && tsWeekDates.some(d => (parseFloat(row.cells[d]?.value)||0) > 0));
  if(incompleteRow){
    alert('One row has hours entered but no project/task selected yet — pick both before saving, or clear those hours.');
    return;
  }

  const calls=[];

  tsPendingDeleteEntryIds.forEach(id=>{
    calls.push(api(`/api/timesheets/${ts.id}/entries/${id}`,{method:'DELETE'}));
  });

  tsGridRows.forEach(row=>{
    if(!row.project_id || !row.task_id) return; // a blank "+ Add Row" nobody filled in — nothing to save
    tsWeekDates.forEach(date=>{
      const cell=row.cells[date]||{};
      const newVal=parseFloat(cell.value)||0;
      const origVal=parseFloat(cell.original_value)||0;
      if(newVal>0 && !cell.entry_id){
        calls.push(api(`/api/timesheets/${ts.id}/entries`,{method:'POST',body:JSON.stringify({project_id:row.project_id, task_id:row.task_id, date, hours:newVal})}));
      } else if(newVal>0 && cell.entry_id && newVal!==origVal){
        calls.push(api(`/api/timesheets/${ts.id}/entries/${cell.entry_id}`,{method:'PUT',body:JSON.stringify({hours:newVal})}));
      } else if(newVal<=0 && cell.entry_id){
        calls.push(api(`/api/timesheets/${ts.id}/entries/${cell.entry_id}`,{method:'DELETE'}));
      }
    });
  });

  const newDescription=document.getElementById('tsWeekDescription').value.trim()||null;
  if(newDescription!==(ts.description||null)){
    calls.push(api(`/api/timesheets/${ts.id}/description`,{method:'PUT',body:JSON.stringify({description:newDescription})}));
  }

  const msgEl=document.getElementById('tsGridSaveMsg');
  if(!calls.length){ msgEl.textContent='Nothing to save.'; msgEl.className='text-xs text-slate-400'; return; }

  const settled=await Promise.allSettled(calls);
  let failures=0;
  for(const r of settled){
    if(r.status==='rejected' || (r.value && !r.value.ok)) failures++;
  }

  await loadCurrentTimesheet();
  const finalMsgEl=document.getElementById('tsGridSaveMsg');
  if(failures>0){
    finalMsgEl.textContent=`Saved, but ${failures} change(s) failed — check locked rows and try again.`;
    finalMsgEl.className='text-xs text-red-600';
  } else {
    finalMsgEl.textContent='Saved.';
    finalMsgEl.className='text-xs text-green-600';
  }
});

const submitTimesheet = guardAsync(async function() {
  if(!confirm('Submit this timesheet for approval? You will not be able to edit it afterwards.')) return;
  const res=await api(`/api/timesheets/${tsCurrentTimesheet.id}/status`,{method:'PATCH',body:JSON.stringify({status:'Submitted'})});
  if(res?.ok){ loadCurrentTimesheet(); }
  else { const d=await res.json(); alert(d.detail||'Failed to submit'); }
});

// ---------------------------------------------------------------------------
// Timesheet Approvals (manager / HR)
// ---------------------------------------------------------------------------
// Server-paginated (routers/timesheets.py's limit/offset + sort_by/sort_dir
// + X-Total-Count header) — mirrors Audit Log's pattern (see audit.js),
// extended with server-side sort since this table's column headers are
// genuinely sortable (Employee/Period/Hours/Status), unlike Audit Log which
// had no sort UI to preserve. tsApprovalRowsCache now holds just the current
// page (openTimesheetDetail below looks a clicked row up in it for its
// is_actionable/pending_with fields, which only the list endpoint computes).
let tsApprovalRowsCache=[];
let tsApprovalPage=1, tsApprovalPageSize=50, tsApprovalTotal=0;
let tsApprovalSortKey='period_start', tsApprovalSortDir='desc';

async function loadTimesheetApprovals() {
  await populateTimesheetApprovalEmployeeFilter();
  await populateTimesheetApprovalProjectFilter();
  const tbody=document.getElementById('timesheetApprovalTableBody');
  tbody.innerHTML='<tr><td colspan="5" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const offset=(tsApprovalPage-1)*tsApprovalPageSize;
  const params=new URLSearchParams({
    limit:String(tsApprovalPageSize), offset:String(offset),
    sort_by:tsApprovalSortKey, sort_dir:tsApprovalSortDir,
  });
  if(tsApprovalFilter) params.set('status', tsApprovalFilter);
  if(tsApprovalEmployeeFilter) params.set('employee_id', tsApprovalEmployeeFilter);
  if(tsApprovalPeriodFrom) params.set('period_from', tsApprovalPeriodFrom);
  if(tsApprovalPeriodTo) params.set('period_to', tsApprovalPeriodTo);
  if(tsApprovalProjectFilter) params.set('project_id', tsApprovalProjectFilter);
  const res=await api(`/api/timesheets?${params}`);
  if(!res?.ok){ tbody.innerHTML=''; return; }
  tsApprovalRowsCache=await res.json();
  tsApprovalTotal=parseInt(res.headers.get('X-Total-Count')||'0',10);
  renderTimesheetApprovalTable();
}

// Built once per session (from the already role-scoped global `employees`
// array — manager sees their reporting chain, HR sees everyone, same
// scoping list_timesheets itself applies) rather than every reload, so
// picking a different employee doesn't fight a dropdown rebuilding out
// from under the user's own selection.
async function populateTimesheetApprovalEmployeeFilter() {
  if(tsApprovalEmployeeOptionsBuilt) return;
  if(!employees || !employees.length) await loadEmployees();
  const sel=document.getElementById('tsApprovalEmployeeFilter');
  const active=(employees||[]).filter(e=>e.status==='Active').sort((a,b)=>a.full_name.localeCompare(b.full_name));
  sel.innerHTML='<option value="">All Employees</option>' + active.map(e=>
    `<option value="${e.employee_id}">${esc(displayName(e.full_name,e.preferred_name))} (${e.employee_id})</option>`
  ).join('');
  initEmployeeSearchSelect('tsApprovalEmployeeFilter', 'Search employee…');
  tsApprovalEmployeeOptionsBuilt=true;
}

function setTimesheetApprovalEmployeeFilter(employeeId) {
  tsApprovalEmployeeFilter=employeeId;
  tsApprovalPage=1;
  loadTimesheetApprovals();
}

// Every project regardless of status (Active/On Hold/Completed) — a
// timesheet can reference a project that's since moved on, and excluding
// those would make some real timesheets unfindable by this filter.
async function populateTimesheetApprovalProjectFilter() {
  if(tsApprovalProjectOptionsBuilt) return;
  const res=await api('/api/projects');
  const list=res?.ok?await res.json():[];
  const sel=document.getElementById('tsApprovalProjectFilter');
  sel.innerHTML='<option value="">All Projects</option>' + list
    .sort((a,b)=>a.name.localeCompare(b.name))
    .map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');
  tsApprovalProjectOptionsBuilt=true;
}

function setTimesheetApprovalProjectFilter(projectId) {
  tsApprovalProjectFilter=projectId;
  tsApprovalPage=1;
  loadTimesheetApprovals();
}

function setTimesheetApprovalPeriod() {
  tsApprovalPeriodFrom=document.getElementById('tsApprovalPeriodFrom').value;
  tsApprovalPeriodTo=document.getElementById('tsApprovalPeriodTo').value;
  tsApprovalPage=1;
  loadTimesheetApprovals();
}

function clearTimesheetApprovalFilters() {
  tsApprovalFilter='Submitted';
  tsApprovalEmployeeFilter='';
  tsApprovalPeriodFrom='';
  tsApprovalPeriodTo='';
  tsApprovalProjectFilter='';
  document.getElementById('tsApprovalStatusFilter').value='Submitted';
  document.getElementById('tsApprovalEmployeeFilter').value='';
  document.getElementById('tsApprovalEmployeeFilterSearch').value='';
  document.getElementById('tsApprovalPeriodFrom').value='';
  document.getElementById('tsApprovalPeriodTo').value='';
  document.getElementById('tsApprovalProjectFilter').value='';
  tsApprovalPage=1;
  loadTimesheetApprovals();
}

function setTimesheetApprovalSort(key) {
  if(tsApprovalSortKey===key) tsApprovalSortDir = tsApprovalSortDir==='asc' ? 'desc' : 'asc';
  else { tsApprovalSortKey=key; tsApprovalSortDir='asc'; }
  tsApprovalPage=1;
  loadTimesheetApprovals();
}
function setTimesheetApprovalPageSize(size) { tsApprovalPageSize=parseInt(size)||50; tsApprovalPage=1; loadTimesheetApprovals(); }
function timesheetApprovalPagePrev() { if(tsApprovalPage>1){ tsApprovalPage--; loadTimesheetApprovals(); } }
function timesheetApprovalPageNext() {
  const totalPages=Math.max(1, Math.ceil(tsApprovalTotal/tsApprovalPageSize));
  if(tsApprovalPage<totalPages){ tsApprovalPage++; loadTimesheetApprovals(); }
}

function renderTimesheetApprovalTable() {
  const tbody=document.getElementById('timesheetApprovalTableBody');
  const emptyEl=document.getElementById('timesheetApprovalEmpty');
  const pagination=document.getElementById('timesheetApprovalPagination');
  document.querySelectorAll('.ts-appr-sort-arrow').forEach(el=>{
    const key=el.dataset.sortKey;
    el.textContent = key===tsApprovalSortKey ? (tsApprovalSortDir==='asc'?' ▲':' ▼') : '';
  });

  if(!tsApprovalRowsCache.length){ tbody.innerHTML=''; emptyEl?.classList.remove('hidden'); pagination?.classList.add('hidden'); return; }
  emptyEl?.classList.add('hidden');
  pagination?.classList.remove('hidden');
  const pageSizeEl=document.getElementById('timesheetApprovalPageSize');
  if(pageSizeEl) pageSizeEl.value=String(tsApprovalPageSize);

  const offset=(tsApprovalPage-1)*tsApprovalPageSize;
  const pageInfoEl=document.getElementById('timesheetApprovalPageInfo');
  if(pageInfoEl) pageInfoEl.textContent=`${offset+1}-${Math.min(offset+tsApprovalPageSize, tsApprovalTotal)} of ${tsApprovalTotal}`;

  tbody.innerHTML=tsApprovalRowsCache.map(t=>`
    <tr class="cursor-pointer hover:bg-slate-50 transition" onclick="openTimesheetDetail(${t.id})">
      <td class="px-4 py-3">
        <p class="font-medium">${esc(displayName(t.employee_name,t.employee_preferred_name))}</p>
        <p class="text-xs text-slate-500">${esc(t.department||'')}${t.designation?' · '+esc(t.designation):''}</p>
      </td>
      <td class="px-4 py-3 text-slate-600">
        ${fmtDate(t.period_start)} → ${fmtDate(t.period_end)}
        ${t.status==='Submitted' && !t.is_actionable ? `<p class="text-xs text-slate-400 mt-0.5">Pending with: ${pendingWithLabel(t)}</p>` : ''}
      </td>
      <td class="px-4 py-3 text-slate-600">${esc(t.project_names||'—')}</td>
      <td class="px-4 py-3 text-right text-slate-600">${t.total_hours} hrs</td>
      <td class="px-4 py-3"><span class="badge ${statusColor(TS_STATUS_COLORS, t.status)} text-xs">${t.status}</span></td>
    </tr>`).join('');
}

function setTimesheetApprovalFilter(status) {
  tsApprovalFilter=status;
  tsApprovalPage=1;
  loadTimesheetApprovals();
}

async function openTimesheetDetail(tsId) {
  const res=await api(`/api/timesheets/${tsId}`);
  if(!res?.ok) return;
  const ts=await res.json();
  document.getElementById('timesheetDetailTitle').textContent=`Timesheet — ${fmtDate(ts.period_start)} to ${fmtDate(ts.period_end)}`;
  // A split (new-style) timesheet's own status is vestigial once
  // per-project rows exist — real status is shown per project below.
  const hasSplit=ts.project_approvals && ts.project_approvals.length>0;
  document.getElementById('timesheetDetailMeta').textContent=hasSplit
    ? `Submitted ${ts.submitted_at?fmtDate(ts.submitted_at):''} · status shown per project below`
    : `Status: ${ts.status}${ts.submitted_at?' · Submitted '+fmtDate(ts.submitted_at):''}`;
  document.getElementById('timesheetDetailBody').innerHTML=ts.entries.map(e=>`
    <tr class="border-t border-slate-100">
      <td class="py-2">${fmtDate(e.date)}</td><td class="py-2">${esc(e.project_name)}</td>
      <td class="py-2">${esc(e.task_name||'—')}</td>
      <td class="py-2">${e.hours}</td><td class="py-2 text-slate-500">${esc(e.description||'')}</td>
    </tr>`).join('');
  document.getElementById('timesheetDetailTotal').textContent=`Total: ${ts.total_hours} hours`;
  const actions=document.getElementById('timesheetDetailActions');
  if(ts.project_approvals && ts.project_approvals.length){
    // Split (new-style) timesheet — one status/action per project,
    // independent of any other project on this same week. The container
    // defaults to a flex ROW (sized for the legacy 2-button case below) —
    // switch it to a column stack for this multi-row case.
    actions.className='flex flex-col gap-2 mb-4';
    actions.innerHTML=ts.project_approvals.map(pa=>`
      <div class="flex items-center gap-3 bg-slate-50 rounded-lg px-3 py-2 flex-wrap">
        <span class="text-sm font-medium text-slate-700 shrink-0">${esc(pa.project_name)}</span>
        <span class="text-xs text-slate-500 shrink-0">${pa.total_hours}h</span>
        <span class="badge ${statusColor(TS_STATUS_COLORS, pa.status)} text-xs shrink-0">${pa.status}</span>
        <span class="flex-1"></span>
        ${pa.status==='Submitted' ? (pa.is_actionable!==false ? `
          <button onclick="reviewTimesheetProject(${ts.id},${pa.project_id},'Approved')" class="btn-primary text-xs px-2 py-1">Approve</button>
          <button onclick="reviewTimesheetProject(${ts.id},${pa.project_id},'Rejected')" class="btn-ghost text-xs px-2 py-1 text-red-600">Reject</button>
        ` : `<p class="text-xs text-slate-400">Pending with: ${pendingWithLabel(pa)}</p>`) : ''}
      </div>`).join('');
  } else {
    // Legacy (pre-split) or Draft timesheet — the old whole-record action.
    actions.className='flex gap-2 mb-4';
    const cached=tsApprovalRowsCache.find(r=>r.id===ts.id);
    actions.innerHTML=ts.status!=='Submitted'?'':(!cached||cached.is_actionable)?`
      <button onclick="reviewTimesheet(${ts.id},'Approved')" class="btn-primary text-sm">Approve</button>
      <button onclick="reviewTimesheet(${ts.id},'Rejected')" class="btn-ghost text-sm text-red-600">Reject</button>
    `:`<p class="text-xs text-slate-400">Pending with: ${pendingWithLabel(cached)}</p>`;
  }
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
      ${o.project_name?`<span class="text-xs text-slate-600 shrink-0">${esc(o.project_name)}</span>`:''}
      <span class="text-xs text-slate-500 shrink-0">${o.logged_hours}h logged, ${o.threshold_hours}h normal</span>
      <span class="text-sm font-medium text-amber-700 shrink-0">+${o.overtime_hours}h OT</span>
      <span class="badge ${statusColor(OT_STATUS_COLORS, o.status)} text-xs shrink-0">${o.status}</span>
      <span class="flex-1"></span>
      ${(o.status==='Pending' && (o.is_actionable===undefined||o.is_actionable))?`
        <button onclick="reviewOvertime(${o.project_approval_id||o.id},${tsId},'Approved',${!!o.project_approval_id})" class="btn-primary text-xs px-2 py-1">Approve</button>
        <button onclick="reviewOvertime(${o.project_approval_id||o.id},${tsId},'Rejected',${!!o.project_approval_id})" class="btn-ghost text-xs px-2 py-1 text-red-600">Reject</button>
      `:(o.status==='Pending' && !o.is_actionable ? `<p class="text-xs text-slate-400">Pending with: ${pendingWithLabel(o)}</p>` : '')}
    </div>`).join('');
}

async function reviewOvertime(id, tsId, status, isProjectSplit) {
  const url=isProjectSplit ? `/api/overtime/projects/${id}/status` : `/api/overtime/${id}/status`;
  const res=await api(url,{method:'PATCH',body:JSON.stringify({status})});
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
        <p class="font-medium text-slate-800">${fmtDate(o.work_date)}${o.project_name?` <span class="text-slate-400 font-normal">— ${esc(o.project_name)}</span>`:''}</p>
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

async function reviewTimesheetProject(tsId, projectId, status) {
  const res=await api(`/api/timesheets/${tsId}/projects/${projectId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  if(res?.ok){
    // Stays open and refreshes in place — a timesheet split across
    // several projects likely still has other projects left to decide.
    await openTimesheetDetail(tsId);
    loadTimesheetApprovals();
  } else {
    const d=await res.json(); alert(d.detail||'Failed to update');
  }
}

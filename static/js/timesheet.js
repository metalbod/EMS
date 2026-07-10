// Timesheet / Projects
// ---------------------------------------------------------------------------
let projectsCache=[], myProjectsCache=[], projectFilter='';
let projectSortKey='name', projectSortDir=1; // 1=asc, -1=desc
let tsCurrentWeekStart=null, tsCurrentTimesheet=null;
let tsApprovalFilter='Submitted';
const TS_STATUS_COLORS={'Draft':'bg-slate-100 text-slate-600','Submitted':'bg-amber-100 text-amber-700','Approved':'bg-green-100 text-green-700','Rejected':'bg-red-100 text-red-700'};

function isProjectManager() {
  return ['superadmin','hr_manager'].includes(currentUser?.role);
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
    const active=projectSortKey===c.key;
    const arrow=active?(projectSortDir===1?'▲':'▼'):'';
    return `<th class="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide cursor-pointer select-none hover:text-slate-700" onclick="setProjectSort('${c.key}')">${c.label} <span class="text-blue-600">${arrow}</span></th>`;
  }).join('');
}

function setProjectSort(key) {
  if(projectSortKey===key){ projectSortDir*=-1; } else { projectSortKey=key; projectSortDir=1; }
  renderProjectTableHead();
  renderProjectTable();
}

function renderProjectTable() {
  const listEl=document.getElementById('projectList');
  const STATUS_COLORS={'Active':'bg-green-100 text-green-700','On Hold':'bg-amber-100 text-amber-700','Completed':'bg-slate-100 text-slate-600'};
  const sorted=[...projectsCache].sort((a,b)=>{
    let av=a[projectSortKey], bv=b[projectSortKey];
    if(typeof av==='string') av=av.toLowerCase();
    if(typeof bv==='string') bv=bv.toLowerCase();
    if(av<bv) return -1*projectSortDir;
    if(av>bv) return 1*projectSortDir;
    return 0;
  });
  listEl.innerHTML=sorted.map(p=>`
    <tr class="border-t border-slate-100 cursor-pointer hover:bg-slate-50 transition" onclick="openProjectModal(${p.id})">
      <td class="px-4 py-3">
        <p class="font-medium text-slate-800">${esc(p.name)}</p>
        <p class="text-xs text-slate-400 line-clamp-1">${esc(p.description||'')}</p>
      </td>
      <td class="px-4 py-3"><span class="badge text-xs ${STATUS_COLORS[p.status]||'bg-slate-100 text-slate-600'}">${p.status}</span></td>
      <td class="px-4 py-3 text-slate-600">${p.task_count}</td>
      <td class="px-4 py-3 text-slate-600">${p.member_count}</td>
      <td class="px-4 py-3 text-slate-600">${p.total_allocated_hours}h</td>
      <td class="px-4 py-3 text-slate-600">${p.total_logged_hours}h</td>
    </tr>`).join('');
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

async function openProjectModal(projectId) {
  document.getElementById('projectId').value=projectId||'';
  document.getElementById('projectModalTitle').textContent=projectId?'Edit Project':'Add Project';
  const tasksBtn=document.getElementById('projectTabTasksBtn');
  switchProjectTab('details');
  if(projectId){
    const p=projectsCache.find(x=>x.id===projectId);
    document.getElementById('projectName').value=p?.name||'';
    document.getElementById('projectDesc').value=p?.description||'';
    document.getElementById('projectStatus').value=p?.status||'Active';
    tasksBtn.classList.remove('hidden');
    await loadProjectTasksForManage(projectId);
    resetProjectTaskForm();
  } else {
    document.getElementById('projectName').value='';
    document.getElementById('projectDesc').value='';
    document.getElementById('projectStatus').value='Active';
    tasksBtn.classList.add('hidden');
  }
  document.getElementById('projectModal').classList.remove('hidden');
}
function closeProjectModal() { document.getElementById('projectModal').classList.add('hidden'); }

async function submitProject() {
  const id=document.getElementById('projectId').value;
  const body={
    name: document.getElementById('projectName').value.trim(),
    description: document.getElementById('projectDesc').value.trim()||null,
    status: document.getElementById('projectStatus').value,
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
}

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
const TASK_STATUS_COLORS={'Not Started':'bg-slate-100 text-slate-600','In Progress':'bg-blue-100 text-blue-700','Completed':'bg-green-100 text-green-700'};

async function loadProjectTasksForManage(projectId) {
  const res=await api(`/api/projects/${projectId}/tasks`);
  projectTasksCache=res?.ok?await res.json():[];
  document.getElementById('projectTaskList').innerHTML=projectTasksCache.length?projectTasksCache.map(t=>`
    <div class="border border-slate-200 rounded-lg p-2 text-sm">
      <div class="flex items-center justify-between gap-2">
        <span class="font-medium text-slate-700">${esc(t.name)}</span>
        <div class="flex items-center gap-1">
          ${t.open_to_all?'<span class="badge text-xs bg-blue-100 text-blue-700">ALL</span>':''}
          <span class="badge text-xs ${TASK_STATUS_COLORS[t.status]||'bg-slate-100 text-slate-600'}">${t.status}</span>
        </div>
      </div>
      <p class="text-xs text-slate-500 mt-0.5">
        ${t.start_date?`${t.start_date} → ${t.end_date||'?'}`:'No dates set'}
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

async function submitProjectTask() {
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
}

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
      <span class="flex-1">${esc(a.full_name)}</span>
      <span class="text-slate-400">${a.start_datetime.replace('T',' ')} · ${a.duration_hours}h</span>
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
    ? available.map(e=>`<option value="${e.employee_id}">${esc(e.full_name)}</option>`).join('')
    : (openToAll?'':'<option value="">All employees already assigned</option>'));
  toggleTaskAssignAllMode();
}

async function addTaskAssignment() {
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
}

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
  document.getElementById('timesheetWeekLabel').textContent=`${start} → ${endStr}`;

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
        <td class="px-4 py-2">${e.date}</td>
        <td class="px-4 py-2">${esc(e.project_name)}</td>
        <td class="px-4 py-2">${esc(e.task_name||'—')}</td>
        <td class="px-4 py-2">${e.hours}</td>
        <td class="px-4 py-2 text-slate-500">${esc(e.description||'')}</td>
        <td class="px-4 py-2 text-right">${isDraft?`<button onclick="deleteTimesheetEntry(${e.id})" class="text-slate-300 hover:text-red-500"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>`:''}</td>
      </tr>`).join('');
  }
  document.getElementById('timesheetTotalHours').textContent=ts.total_hours;

  const badgeWrap=document.getElementById('timesheetStatusBadgeWrap');
  badgeWrap.innerHTML=`<span class="badge ${TS_STATUS_COLORS[ts.status]||'bg-slate-100 text-slate-600'}">${ts.status}</span>${ts.notes?` <span class="text-xs text-slate-400 ml-1">${esc(ts.notes)}</span>`:''}`;

  document.getElementById('timesheetAddForm').classList.toggle('hidden', !isDraft);
  document.getElementById('timesheetSubmitBtn').classList.toggle('hidden', !isDraft);
  document.getElementById('tsEntryDate').value='';
  document.getElementById('tsEntryHours').value='';
  document.getElementById('tsEntryDesc').value='';
}

async function addTimesheetEntry() {
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
}

async function deleteTimesheetEntry(entryId) {
  await api(`/api/timesheets/${tsCurrentTimesheet.id}/entries/${entryId}`,{method:'DELETE'});
  const detailRes=await api(`/api/timesheets/${tsCurrentTimesheet.id}`);
  tsCurrentTimesheet=await detailRes.json();
  renderTimesheetEntries();
}

async function submitTimesheet() {
  if(!confirm('Submit this timesheet for approval? You will not be able to edit it afterwards.')) return;
  const res=await api(`/api/timesheets/${tsCurrentTimesheet.id}/status`,{method:'PATCH',body:JSON.stringify({status:'Submitted'})});
  if(res?.ok){ loadCurrentTimesheet(); }
  else { const d=await res.json(); alert(d.detail||'Failed to submit'); }
}

// ---------------------------------------------------------------------------
// Timesheet Approvals (manager / HR)
// ---------------------------------------------------------------------------
async function loadTimesheetApprovals() {
  const listEl=document.getElementById('timesheetApprovalList');
  const emptyEl=document.getElementById('timesheetApprovalEmpty');
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  let url='/api/timesheets';
  if(tsApprovalFilter) url+=`?status=${encodeURIComponent(tsApprovalFilter)}`;
  const res=await api(url);
  if(!res?.ok){ listEl.innerHTML=''; return; }
  const rows=await res.json();
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(t=>`
    <div class="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:shadow-sm transition" onclick="openTimesheetDetail(${t.id})">
      <div class="flex items-center justify-between gap-2">
        <div>
          <p class="font-medium text-slate-800">${esc(t.employee_name)}</p>
          <p class="text-xs text-slate-500">${esc(t.department||'')}${t.designation?' · '+esc(t.designation):''} · ${t.period_start} → ${t.period_end}</p>
        </div>
        <div class="text-right">
          <span class="badge ${TS_STATUS_COLORS[t.status]||'bg-slate-100 text-slate-600'} text-xs">${t.status}</span>
          <p class="text-xs text-slate-400 mt-1">${t.total_hours} hrs</p>
        </div>
      </div>
    </div>`).join('');
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
  document.getElementById('timesheetDetailTitle').textContent=`Timesheet — ${ts.period_start} to ${ts.period_end}`;
  document.getElementById('timesheetDetailMeta').textContent=`Status: ${ts.status}${ts.submitted_at?' · Submitted '+ts.submitted_at.slice(0,10):''}`;
  document.getElementById('timesheetDetailBody').innerHTML=ts.entries.map(e=>`
    <tr class="border-t border-slate-100">
      <td class="py-2">${e.date}</td><td class="py-2">${esc(e.project_name)}</td>
      <td class="py-2">${esc(e.task_name||'—')}</td>
      <td class="py-2">${e.hours}</td><td class="py-2 text-slate-500">${esc(e.description||'')}</td>
    </tr>`).join('');
  document.getElementById('timesheetDetailTotal').textContent=`Total: ${ts.total_hours} hours`;
  const actions=document.getElementById('timesheetDetailActions');
  actions.innerHTML=ts.status==='Submitted'?`
    <button onclick="reviewTimesheet(${ts.id},'Approved')" class="btn-primary text-sm">Approve</button>
    <button onclick="reviewTimesheet(${ts.id},'Rejected')" class="btn-ghost text-sm text-red-600">Reject</button>
  `:'';
  document.getElementById('timesheetDetailModal').classList.remove('hidden');
}
function closeTimesheetDetailModal() { document.getElementById('timesheetDetailModal').classList.add('hidden'); }

async function reviewTimesheet(tsId, status) {
  const res=await api(`/api/timesheets/${tsId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  if(res?.ok){ closeTimesheetDetailModal(); loadTimesheetApprovals(); }
  else { const d=await res.json(); alert(d.detail||'Failed to update'); }
}

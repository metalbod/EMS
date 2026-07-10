// Onboarding / Offboarding
// ---------------------------------------------------------------------------
let viewingObId=null, obCurrentType='onboarding', obTemplatesCache={};
const OB_ROLE_COLORS={employee:'bg-purple-100 text-purple-700',manager:'bg-amber-100 text-amber-700',hr_admin:'bg-cyan-100 text-cyan-700',hr_manager:'bg-blue-100 text-blue-700'};
const OB_ROLE_LABELS={employee:'Employee',manager:'Manager',hr_admin:'HR Admin',hr_manager:'HR Manager'};

async function loadObChecklists(type, statusFilter) {
  obCurrentType=type;
  const listEl=document.getElementById(`${type}List`);
  const emptyEl=document.getElementById(`${type}Empty`);
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  let url=`/api/ob/checklists?type=${type}`;
  if(statusFilter&&statusFilter!=='all') url+=`&status=${encodeURIComponent(statusFilter)}`;
  const res=await api(url);
  if(!res||!res.ok){listEl.innerHTML='';return;}
  const rows=await res.json();
  if(!rows.length){listEl.innerHTML='';emptyEl?.classList.remove('hidden');return;}
  emptyEl?.classList.add('hidden');
  const canManage=['superadmin','hr_manager','hr_admin'].includes(currentUser?.role);
  listEl.innerHTML=rows.map(c=>{
    const pct=c.total_items?Math.round((c.done_items/c.total_items)*100):0;
    const myPending=c.my_pending>0;
    return `<div class="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:shadow-sm transition" onclick="openObDetail(${c.id})">
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-0.5">
            <p class="font-medium text-slate-800">${esc(c.employee_name)}</p>
            ${myPending?`<span class="badge bg-orange-100 text-orange-700 text-xs">Action Required</span>`:''}
          </div>
          <p class="text-xs text-slate-500">${esc(c.department||'')}${c.designation?' · '+esc(c.designation):''}</p>
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <span class="badge ${c.status==='Completed'?'bg-green-100 text-green-700':'bg-blue-100 text-blue-700'}">${c.status}</span>
          ${canManage?`<button onclick="event.stopPropagation();deleteObChecklist(${c.id},'${type}')" class="text-slate-300 hover:text-red-500 text-xs" title="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>`:''}
        </div>
      </div>
      <div class="mt-3 flex items-center gap-3">
        <div class="flex-1 bg-slate-100 rounded-full h-1.5"><div class="bg-blue-500 h-1.5 rounded-full" style="width:${pct}%"></div></div>
        <span class="text-xs text-slate-500">${c.done_items}/${c.total_items} done</span>
      </div>
      <p class="text-xs text-slate-400 mt-1">Started ${c.created_at?.slice(0,10)} by ${esc(c.triggered_by)}</p>
    </div>`;
  }).join('');
}

function setObFilter(type, status) {
  document.querySelectorAll('.ob-filter-btn').forEach(b=>b.classList.remove('ob-filter-active'));
  event?.target?.classList?.add('ob-filter-active');
  loadObChecklists(type, status);
}

async function openObDetail(clId) {
  viewingObId=clId;
  const res=await api(`/api/ob/checklists/${clId}`);
  if(!res||!res.ok) return;
  const cl=await res.json();
  const type=cl.type;
  document.getElementById('obDetailTitle').textContent=`${type==='onboarding'?'Onboarding':'Offboarding'} — ${esc(cl.employee_name)}`;
  document.getElementById('obDetailMeta').textContent=`${esc(cl.department||'')}${cl.designation?' · '+esc(cl.designation):''} · Started ${cl.created_at?.slice(0,10)}`;
  const total=cl.items.length;
  const done=cl.items.filter(i=>i.status==='Done'||i.status==='N/A').length;
  const pct=total?Math.round((done/total)*100):0;
  document.getElementById('obProgressBar').style.width=pct+'%';
  document.getElementById('obProgressLabel').textContent=`${done} / ${total}`;
  const badge=document.getElementById('obStatusBadge');
  badge.textContent=cl.status;
  badge.className=`badge ${cl.status==='Completed'?'bg-green-100 text-green-700':'bg-blue-100 text-blue-700'}`;
  // Group items by role
  const roles=['employee','manager','hr_admin','hr_manager'];
  const grouped={};
  roles.forEach(r=>grouped[r]=[]);
  cl.items.forEach(i=>{ if(grouped[i.assigned_role]) grouped[i.assigned_role].push(i); });
  const canComplete=role=>role===currentUser?.role||['superadmin','hr_manager','hr_admin'].includes(currentUser?.role);
  const canEdit=['superadmin','hr_manager','hr_admin'].includes(currentUser?.role);
  let html='';
  roles.forEach(role=>{
    const items=grouped[role];
    if(!items.length) return;
    html+=`<div class="mb-4">
      <div class="flex items-center gap-2 mb-2">
        <span class="badge ${OB_ROLE_COLORS[role]||'bg-slate-100 text-slate-600'} text-xs">${OB_ROLE_LABELS[role]||role}</span>
        <span class="text-xs text-slate-400">${items.filter(i=>i.status==='Done'||i.status==='N/A').length}/${items.length} done</span>
      </div>
      ${items.map(item=>{
        const isDone=item.status==='Done'||item.status==='N/A';
        const isHR=['superadmin','hr_manager','hr_admin'].includes(currentUser?.role);
        const isLinked=!!item.linked_ld_course_id;
        const canAct=canComplete(role)&&cl.status==='In Progress'&&!(isLinked&&!isHR);
        return `<div class="flex items-start gap-3 py-2.5 border-b border-slate-100 last:border-0" id="obitem-${item.id}">
          <div class="mt-0.5 flex-shrink-0">
            ${canAct?`<input type="checkbox" class="w-4 h-4 cursor-pointer" ${isDone?'checked':''} onchange="toggleObItem(${clId},${item.id},this.checked)"/>`
              :`<div class="w-4 h-4 rounded border-2 ${isDone?'bg-blue-500 border-blue-500':'border-slate-300'} flex items-center justify-center">${isDone?'<svg class="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>':''}</div>`}
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <p class="text-sm ${isDone?'line-through text-slate-400':'text-slate-700'}">${esc(item.title)}</p>
              ${isLinked?`<span class="badge text-xs bg-green-100 text-green-700" title="Auto-completes via linked L&D course">🎓 Linked course</span>`:''}
            </div>
            ${item.description?`<p class="text-xs text-slate-400 mt-0.5">${esc(item.description)}</p>`:''}
            ${isLinked&&!isDone&&!isHR?`<p class="text-xs text-blue-600 mt-0.5">Complete this in <a href="#" onclick="closeObDetail();document.querySelector('[data-page=\\'ld-trainings\\']')?.click();return false;" class="underline">My Trainings</a> to auto-complete this item.</p>`:''}
            ${item.completed_by?`<p class="text-xs text-green-600 mt-0.5">✓ ${esc(item.completed_by)} · ${item.completed_at?.slice(0,10)}</p>`:''}
            ${item.notes?`<p class="text-xs text-slate-500 italic mt-0.5">${esc(item.notes)}</p>`:''}
          </div>
          <div class="flex items-center gap-1 flex-shrink-0">
            ${canAct&&isDone?`<button onclick="toggleObItem(${clId},${item.id},false)" class="text-xs text-slate-400 hover:text-orange-500 px-1">Undo</button>`:''}
            ${canEdit?`<button onclick="showObItemEdit(${clId},${item.id},'${esc(item.title).replace(/'/g,"\\'")}','${esc(item.description||'').replace(/'/g,"\\'")}','${item.assigned_role}')" class="text-slate-300 hover:text-blue-500" title="Edit"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
            <button onclick="deleteObItem(${clId},${item.id})" class="text-slate-300 hover:text-red-500" title="Remove"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>`:''}
          </div>
        </div>`;
      }).join('')}
    </div>`;
  });
  // Add item form at bottom (HR only)
  if(canEdit&&cl.status==='In Progress'){
    html+=`<div class="border-t border-slate-200 pt-3 mt-2">
      <p class="text-xs font-medium text-slate-500 mb-2">Add Item</p>
      <div class="flex gap-2">
        <input id="obAddTitle" class="inp flex-1 text-sm" placeholder="Item title…"/>
        <select id="obAddRole" class="inp text-sm" style="width:120px">
          <option value="employee">Employee</option>
          <option value="manager">Manager</option>
          <option value="hr_admin" selected>HR Admin</option>
          <option value="hr_manager">HR Manager</option>
        </select>
        <button onclick="addObItem(${clId})" class="btn-primary text-sm px-3">Add</button>
      </div>
    </div>`;
  }
  document.getElementById('obItemsContainer').innerHTML=html||'<p class="text-slate-400 text-sm">No items.</p>';
  document.getElementById('obDetailModal').classList.remove('hidden');
}

async function toggleObItem(clId,itemId,done) {
  const res=await api(`/api/ob/checklists/${clId}/items/${itemId}`,{method:'PATCH',body:JSON.stringify({status:done?'Done':'Pending'})});
  if(!res||!res.ok) return;
  await openObDetail(clId);
  loadObChecklists(obCurrentType);
}

function closeObDetail(){document.getElementById('obDetailModal').classList.add('hidden');viewingObId=null;}


function openStartObModal(type) {
  document.getElementById('startObType').value=type;
  document.getElementById('startObTitle').textContent=type==='onboarding'?'Start Onboarding':'Start Offboarding';
  document.getElementById('startObSubmitBtn').textContent=type==='onboarding'?'Start Onboarding':'Start Offboarding';
  document.getElementById('startObNotes').value='';
  document.getElementById('startObErr').classList.add('hidden');
  const sel=document.getElementById('startObEmpId');
  sel.innerHTML='<option value="">Select employee…</option>';
  employees.filter(e=>e.status==='Active').forEach(e=>{const o=document.createElement('option');o.value=e.employee_id;o.textContent=`${e.employee_id} — ${esc(e.full_name)}`;sel.appendChild(o);});
  document.getElementById('startObModal').classList.remove('hidden');
}
function closeStartObModal(){document.getElementById('startObModal').classList.add('hidden');}

async function submitStartOb(e) {
  e.preventDefault();
  const err=document.getElementById('startObErr');
  err.classList.add('hidden');
  const type=document.getElementById('startObType').value;
  const body={employee_id:document.getElementById('startObEmpId').value,type,notes:document.getElementById('startObNotes').value||null};
  const res=await api('/api/ob/checklists',{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();err.textContent=d?.detail||'Failed';err.classList.remove('hidden');return;}
  closeStartObModal();
  loadObChecklists(type);
}

async function showObItemEdit(clId,itemId,title,description,assignedRole) {
  const roles=[{v:'employee',l:'Employee'},{v:'manager',l:'Manager'},{v:'hr_admin',l:'HR Admin'},{v:'hr_manager',l:'HR Manager'}];
  const el=document.getElementById('obitem-'+itemId);
  if(!el) return;
  el.innerHTML=`
    <div class="flex-1 space-y-2 py-1">
      <input id="obedit-title-${itemId}" class="inp text-sm w-full" value="${esc(title)}"/>
      <div class="flex gap-2">
        <input id="obedit-desc-${itemId}" class="inp text-sm flex-1" placeholder="Description…" value="${esc(description)}"/>
        <select id="obedit-role-${itemId}" class="inp text-sm" style="width:120px">
          ${roles.map(r=>`<option value="${r.v}" ${r.v===assignedRole?'selected':''}>${r.l}</option>`).join('')}
        </select>
      </div>
      <div class="flex gap-2">
        <button onclick="saveObItemEdit(${clId},${itemId})" class="btn-primary text-xs px-3 py-1">Save</button>
        <button onclick="openObDetail(${clId})" class="text-xs text-slate-500 hover:text-slate-700 px-2">Cancel</button>
      </div>
    </div>`;
}

async function saveObItemEdit(clId,itemId) {
  const title=document.getElementById('obedit-title-'+itemId)?.value.trim();
  const desc=document.getElementById('obedit-desc-'+itemId)?.value.trim();
  const role=document.getElementById('obedit-role-'+itemId)?.value;
  if(!title){alert('Title is required');return;}
  await api(`/api/ob/checklists/${clId}/items/${itemId}`,{method:'PUT',body:JSON.stringify({title,description:desc||null,assigned_role:role})});
  openObDetail(clId);
}

async function deleteObItem(clId,itemId) {
  if(!confirm('Remove this item from the checklist?')) return;
  await api(`/api/ob/checklists/${clId}/items/${itemId}`,{method:'DELETE'});
  openObDetail(clId);
}

async function addObItem(clId) {
  const title=document.getElementById('obAddTitle')?.value.trim();
  const role=document.getElementById('obAddRole')?.value;
  if(!title){alert('Title is required');return;}
  await api(`/api/ob/checklists/${clId}/items`,{method:'POST',body:JSON.stringify({title,assigned_role:role})});
  openObDetail(clId);
}

async function deleteObChecklist(clId,type) {
  if(!confirm('Delete this checklist? This cannot be undone.')) return;
  await api(`/api/ob/checklists/${clId}`,{method:'DELETE'});
  loadObChecklists(type);
}

let obTmplCoursesCache=[];

async function showObTemplates(type) {
  document.getElementById('obTmplType').value=type;
  document.getElementById('obTemplatesTitle').textContent=`${type==='onboarding'?'Onboarding':'Offboarding'} Templates`;
  document.getElementById('obTmplTitle').value='';
  document.getElementById('obTmplDesc').value='';
  document.getElementById('obTmplLdCourse').value='';
  const coursesRes=await api('/api/ld/courses');
  obTmplCoursesCache=coursesRes?.ok?await coursesRes.json():[];
  document.getElementById('obTmplLdCourse').innerHTML='<option value="">No linked course — manual completion</option>'+
    obTmplCoursesCache.map(c=>`<option value="${c.id}">${esc(c.title)}</option>`).join('');
  await refreshObTemplatesList(type);
  document.getElementById('obTemplatesModal').classList.remove('hidden');
}
function closeObTemplates(){document.getElementById('obTemplatesModal').classList.add('hidden');}

async function refreshObTemplatesList(type) {
  const res=await api(`/api/ob/templates?type=${type}`);
  if(!res||!res.ok) return;
  const items=await res.json();
  const canManage=['superadmin','hr_manager','hr_admin'].includes(currentUser?.role);
  document.getElementById('obTemplatesList').innerHTML=items.length?items.map(t=>{
    const linkedCourse=obTmplCoursesCache.find(c=>c.id===t.linked_ld_course_id);
    return `<div class="flex items-center gap-2 py-2 border-b border-slate-100">
      <span class="badge ${OB_ROLE_COLORS[t.assigned_role]||'bg-slate-100'} text-xs flex-shrink-0">${OB_ROLE_LABELS[t.assigned_role]||t.assigned_role}</span>
      <span class="flex-1 text-sm text-slate-700">${esc(t.title)}</span>
      ${linkedCourse?`<span class="badge text-xs bg-green-100 text-green-700 flex-shrink-0" title="Auto-completes via this course">🎓 ${esc(linkedCourse.title)}</span>`:''}
      ${canManage?`<button onclick="deleteObTemplate(${t.id},'${type}')" class="text-slate-300 hover:text-red-500 flex-shrink-0"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>`:''}
    </div>`;
  }).join(''):'<p class="text-slate-400 text-sm py-4 text-center">No template items yet.</p>';
}

async function addObTemplate() {
  const type=document.getElementById('obTmplType').value;
  const title=document.getElementById('obTmplTitle').value.trim();
  if(!title) return;
  const courseVal=document.getElementById('obTmplLdCourse').value;
  const body={
    type,title,description:document.getElementById('obTmplDesc').value.trim()||null,
    assigned_role:document.getElementById('obTmplRole').value,order_index:99,
    linked_ld_course_id:courseVal?parseInt(courseVal):null
  };
  const res=await api('/api/ob/templates',{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok) return;
  document.getElementById('obTmplTitle').value='';
  document.getElementById('obTmplDesc').value='';
  document.getElementById('obTmplLdCourse').value='';
  refreshObTemplatesList(type);
}

async function deleteObTemplate(id,type) {
  await api(`/api/ob/templates/${id}`,{method:'DELETE'});
  refreshObTemplatesList(type);
}

// Onboarding / Offboarding
// ---------------------------------------------------------------------------
let viewingObId=null, obCurrentType='onboarding', obTemplatesCache={};
const OB_ROLE_LABELS={employee:'Employee',manager:'Manager',hr_admin:'HR Admin',hr_manager:'HR Manager',payroll_manager:'Payroll Manager',compensation_manager:'Compensation Manager'};
// Custom roles (Settings > Roles) have no fixed color/label above — fall
// back to a neutral badge and the role's own display_name from rolesCache.
// Colors come from core.js's shared ROLE_BADGE_COLORS, not a local map —
// see its own comment for why role colors specifically are shared across
// files rather than kept per-module like the other *_COLORS maps.
function obRoleColor(role){ return statusColor(ROLE_BADGE_COLORS, role); }
function obRoleLabel(role){ return OB_ROLE_LABELS[role]||rolesCache.find(r=>r.role_key===role)?.display_name||role; }

// Matches routers/onboarding.py's OB_DUE_DATE_RULES — a template item's
// due date is picked as a RULE (no employee in context yet); it's resolved
// into an actual per-employee date only once a checklist starts from that
// template (see _compute_due_date in routers/onboarding.py).
const OB_DUE_DATE_RULE_LABELS={
  '1_month_from_start':'1 Month from Start of Checklist',
  '2_months_from_start':'2 Months from Start of Checklist',
  '3_months_from_start':'3 Months from Start of Checklist',
  'joining_anniversary':'On Anniversary of Joining Date',
  'birthday_anniversary':'On Anniversary of Birth Date',
};

// Checklists list — one createListState per type (onboarding/offboarding
// are separate tables with independent sort/page state), sorting and
// paginating client-side over whatever the current status filter fetched.
function obProgressValue(c) { return c.total_items ? c.done_items / c.total_items : 0; }
const obListStates = {
  onboarding: createListState({ sortKey: 'employee_name', sortValue: (c,key)=> key==='progress' ? obProgressValue(c) : c[key] }),
  offboarding: createListState({ sortKey: 'employee_name', sortValue: (c,key)=> key==='progress' ? obProgressValue(c) : c[key] }),
};
let obRowsCache = { onboarding: [], offboarding: [] };

function setObSort(type, key) { obListStates[type].setSort(key); renderObTable(type); }
function setObPageSize(type, size) { obListStates[type].setPageSize(size); renderObTable(type); }
function obPagePrev(type) { obListStates[type].prevPage(); renderObTable(type); }
function obPageNext(type) { obListStates[type].nextPage(obRowsCache[type].length); renderObTable(type); }

async function loadObChecklists(type, statusFilter) {
  obCurrentType=type;
  const tbody=document.getElementById(`${type}TableBody`);
  const emptyEl=document.getElementById(`${type}Empty`);
  const pagination=document.getElementById(`${type}Pagination`);
  tbody.innerHTML=`<tr><td colspan="9" class="text-center text-slate-400 text-sm py-8">Loading…</td></tr>`;
  let url=`/api/ob/checklists?type=${type}`;
  if(statusFilter&&statusFilter!=='all') url+=`&status=${encodeURIComponent(statusFilter)}`;
  const res=await api(url);
  if(!res||!res.ok){tbody.innerHTML='';pagination?.classList.add('hidden');return;}
  obRowsCache[type]=await res.json();
  obListStates[type].resetPage();
  renderObTable(type);
}

function renderObTable(type) {
  const tbody=document.getElementById(`${type}TableBody`);
  const emptyEl=document.getElementById(`${type}Empty`);
  const pagination=document.getElementById(`${type}Pagination`);
  const rows=obRowsCache[type];
  obListStates[type].updateSortArrows(`#${type}List .ob-sort-arrow`);
  if(!rows.length){tbody.innerHTML='';emptyEl?.classList.remove('hidden');pagination?.classList.add('hidden');return;}
  emptyEl?.classList.add('hidden');
  pagination?.classList.remove('hidden');
  document.getElementById(`${type}PageSize`).value=String(obListStates[type].pageSize);
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  const { pageItems, start, total } = obListStates[type].view(rows);
  document.getElementById(`${type}PageInfo`).textContent =
    `${start + 1}-${Math.min(start + obListStates[type].pageSize, total)} of ${total}`;
  tbody.innerHTML=pageItems.map(c=>{
    const pct=c.total_items?Math.round((c.done_items/c.total_items)*100):0;
    const myPending=c.my_pending>0;
    return `<tr class="hover:bg-slate-50 cursor-pointer" onclick="openObDetail(${c.id})">
      <td class="px-4 py-3">
        <div class="flex items-center gap-2">
          <span class="font-medium text-slate-800">${esc(displayName(c.employee_name, c.employee_preferred_name))}</span>
          ${myPending?`<span class="badge bg-orange-100 text-orange-700 text-xs shrink-0">Action Required</span>`:''}
        </div>
      </td>
      <td class="px-4 py-3 hidden md:table-cell text-slate-600">${fmtDate(c.start_date)}</td>
      <td class="px-4 py-3 hidden md:table-cell text-slate-600">${fmtDate(c.probation_end_date)}</td>
      <td class="px-4 py-3 hidden lg:table-cell text-slate-600">${esc(c.phone||'—')}</td>
      <td class="px-4 py-3 hidden lg:table-cell text-slate-600">${esc(c.work_email||'—')}</td>
      <td class="px-4 py-3 hidden md:table-cell text-slate-600">${esc(c.employee_id)}</td>
      <td class="px-4 py-3">
        <div class="flex items-center gap-2">
          <div class="w-16 bg-slate-100 rounded-full h-1.5"><div class="bg-blue-500 h-1.5 rounded-full" style="width:${pct}%"></div></div>
          <span class="text-xs text-slate-500 shrink-0">${c.done_items}/${c.total_items}</span>
        </div>
      </td>
      <td class="px-4 py-3"><span class="badge ${c.status==='Completed'?'bg-green-100 text-green-700':'bg-blue-100 text-blue-700'}">${c.status}</span></td>
      <td class="px-4 py-3 text-right">${canManage?`<button onclick="event.stopPropagation();deleteObChecklist(${c.id},'${type}')" class="text-slate-300 hover:text-red-500 text-xs" title="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>`:''}</td>
    </tr>`;
  }).join('');
}

function setObFilter(type, status) {
  document.querySelectorAll('.ob-filter-btn').forEach(b=>b.classList.remove('ob-filter-active'));
  event?.target?.classList?.add('ob-filter-active');
  loadObChecklists(type, status);
}

// ---------------------------------------------------------------------------
// Probation Review (Month 1/2/3) — employee-scoped Performance cycles, opted
// into per-employee by HR (not every employee goes through probation). Fully
// reuses the Performance module's own Self/Manager review UI — "View" just
// deep-links into My Goals & Appraisal / Team Appraisals with the relevant
// cycle preselected, rather than duplicating that UI here.
// ---------------------------------------------------------------------------
async function renderObProbationPanel(clId, cl) {
  const panel = document.getElementById('obProbationPanel');
  const canManage = HR_MANAGE_ROLES.includes(currentUser?.role);
  if (!cl.probation_enabled) {
    panel.innerHTML = (canManage && cl.status === 'In Progress')
      ? `<button onclick="enableProbationReviewFromDetail(${clId})" class="btn-ghost text-xs mb-4">+ Enable Probation Review (Month 1/2/3)</button>`
      : '';
    return;
  }
  const res = await api(`/api/ob/checklists/${clId}/probation-reviews`);
  const reviews = res?.ok ? await res.json() : [];
  if (!reviews.length) { panel.innerHTML = ''; return; }
  const statusLabel = r => r.appraisal_status === 'Finalized' ? `Final rating: ${r.final_rating ?? '—'}/5`
    : r.appraisal_status === 'Calibration' ? 'Awaiting HR finalization'
    : r.appraisal_status === 'ManagerReview' ? 'Awaiting manager review'
    : 'Awaiting self-review';
  panel.innerHTML = `<div class="mb-4">
    <p class="text-xs font-medium text-slate-500 mb-2">Probation Review</p>
    <div class="grid grid-cols-3 gap-2">
      ${reviews.map((r, i) => `
        <div class="border border-slate-200 rounded-lg p-3">
          <p class="text-xs font-semibold text-slate-700">Month ${i + 1}</p>
          <p class="text-xs ${r.appraisal_status === 'Finalized' ? 'text-green-600' : 'text-slate-500'} mt-1">${statusLabel(r)}</p>
          <button onclick="viewProbationReview(${r.cycle_id})" class="text-xs text-blue-600 hover:underline mt-1">View →</button>
        </div>`).join('')}
    </div>
  </div>`;
}

async function enableProbationReviewFromDetail(clId) {
  if (!confirm('Enable Probation Review (Month 1/2/3) for this employee? This creates three linked Performance reviews right away.')) return;
  const res = await api(`/api/ob/checklists/${clId}/enable-probation-review`, { method: 'POST' });
  if (!res?.ok) { const d = await res?.json().catch(() => ({})); alert(d?.detail || 'Failed to enable'); return; }
  await openObDetail(clId);
}

async function viewProbationReview(cycleId) {
  closeObDetail();
  const isEmployee = currentUser?.role === 'employee';
  const targetPage = isEmployee ? 'perf-my' : 'perf-team';
  const selId = isEmployee ? 'perfMyCycleSelect' : 'perfTeamCycleSelect';
  const loadFn = isEmployee ? loadMyPerformancePage : loadTeamAppraisalsPage;
  showPage(targetPage);
  await loadFn();
  const sel = document.getElementById(selId);
  if (sel) sel.value = cycleId;
  await loadFn();
}

async function openObDetail(clId) {
  viewingObId=clId;
  const res=await api(`/api/ob/checklists/${clId}`);
  if(!res||!res.ok) return;
  const cl=await res.json();
  const type=cl.type;
  document.getElementById('obDetailTitle').textContent=`${type==='onboarding'?'Onboarding':'Offboarding'} — ${esc(displayName(cl.employee_name, cl.employee_preferred_name))}`;
  document.getElementById('obDetailMeta').textContent=`${esc(cl.department||'')}${cl.designation?' · '+esc(cl.designation):''} · Started ${fmtDate(cl.created_at)}`;
  const total=cl.items.length;
  const done=cl.items.filter(i=>i.status==='Done'||i.status==='N/A').length;
  const pct=total?Math.round((done/total)*100):0;
  document.getElementById('obProgressBar').style.width=pct+'%';
  document.getElementById('obProgressLabel').textContent=`${done} / ${total}`;
  const badge=document.getElementById('obStatusBadge');
  badge.textContent=cl.status;
  badge.className=`badge ${cl.status==='Completed'?'bg-green-100 text-green-700':'bg-blue-100 text-blue-700'}`;
  if(type==='onboarding') await renderObProbationPanel(clId, cl);
  else document.getElementById('obProbationPanel').innerHTML='';
  // Group items by role
  const roles=OB_ROLES_ORDER;
  const grouped={};
  roles.forEach(r=>grouped[r]=[]);
  cl.items.forEach(i=>{ if(grouped[i.assigned_role]) grouped[i.assigned_role].push(i); });
  const canComplete=role=>role===currentUser?.role||HR_MANAGE_ROLES.includes(currentUser?.role);
  const canEdit=HR_MANAGE_ROLES.includes(currentUser?.role);
  let html='';
  roles.forEach(role=>{
    const items=grouped[role];
    if(!items.length) return;
    html+=`<div class="mb-4">
      <div class="flex items-center gap-2 mb-2">
        <span class="badge ${obRoleColor(role)} text-xs">${esc(obRoleLabel(role))}</span>
        <span class="text-xs text-slate-400">${items.filter(i=>i.status==='Done'||i.status==='N/A').length}/${items.length} done</span>
      </div>
      ${items.map(item=>{
        const isDone=item.status==='Done'||item.status==='N/A';
        const isHR=HR_MANAGE_ROLES.includes(currentUser?.role);
        const isLinked=!!item.linked_ld_course_id;
        const canAct=canComplete(role)&&cl.status==='In Progress'&&!(isLinked&&!isHR);
        return `<div class="flex items-start gap-3 py-2.5 border-b border-slate-100 last:border-0" id="obitem-${item.id}">
          <div class="mt-0.5 shrink-0">
            ${canAct?`<input type="checkbox" class="w-4 h-4 cursor-pointer" ${isDone?'checked':''} onchange="toggleObItem(${clId},${item.id},this.checked)"/>`
              :`<div class="w-4 h-4 rounded-sm border-2 ${isDone?'bg-blue-500 border-blue-500':'border-slate-300'} flex items-center justify-center">${isDone?'<svg class="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>':''}</div>`}
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <p class="text-sm ${isDone?'line-through text-slate-400':'text-slate-700'}">${esc(item.title)}</p>
              ${isLinked?`<span class="badge text-xs bg-green-100 text-green-700" title="Auto-completes via linked L&D course">🎓 Linked course</span>`:''}
            </div>
            ${item.description?`<p class="text-xs text-slate-400 mt-0.5">${esc(item.description)}</p>`:''}
            ${item.due_date?`<p class="text-xs text-indigo-600 mt-0.5">📅 Due ${fmtDate(item.due_date)}, ${esc(item.due_date.slice(11,16))}</p>`:''}
            ${isLinked&&!isDone&&!isHR?`<p class="text-xs text-blue-600 mt-0.5">Complete this in <a href="#" onclick="closeObDetail();document.querySelector('[data-page=\\'ld-trainings\\']')?.click();return false;" class="underline">My Trainings</a> to auto-complete this item.</p>`:''}
            ${item.completed_by?`<p class="text-xs text-green-600 mt-0.5">✓ ${esc(item.completed_by)} · ${fmtDate(item.completed_at)}</p>`:''}
            ${item.notes?`<p class="text-xs text-slate-500 italic mt-0.5">${esc(item.notes)}</p>`:''}
            <div id="obitem-attach-${item.id}" class="hidden mt-1.5 space-y-1"></div>
          </div>
          <div class="flex items-center gap-1 shrink-0">
            ${canAct&&isDone?`<button onclick="toggleObItem(${clId},${item.id},false)" class="text-xs text-slate-400 hover:text-orange-500 px-1">Undo</button>`:''}
            ${canComplete(role)?`<button onclick="toggleObItemAttachments(${clId},${item.id})" class="text-slate-300 hover:text-blue-500 relative" title="Attach proof (optional)">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.485 8.486L20.5 13"/></svg>
              <span id="obitem-attach-badge-${item.id}" class="${item.attachment_count>0?'':'hidden'} absolute -top-1.5 -right-1.5 bg-blue-500 text-white text-[9px] rounded-full min-w-[14px] h-3.5 px-0.5 flex items-center justify-center">${item.attachment_count||''}</span>
            </button>`:''}
            ${canEdit?`<button onclick="showObItemEdit(${clId},${item.id},'${esc(item.title).replace(/'/g,"\\'")}','${esc(item.description||'').replace(/'/g,"\\'")}','${item.assigned_role}','${item.due_date||''}')" class="text-slate-300 hover:text-blue-500" title="Edit"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
            <button onclick="deleteObItem(${clId},${item.id})" class="text-slate-300 hover:text-red-500" title="Remove"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>`:''}
          </div>
        </div>`;
      }).join('')}
    </div>`;
  });
  // Add item form at bottom (HR only)
  if(canEdit&&cl.status==='In Progress'){
    html+=`<div class="border-t border-slate-200 pt-3 mt-2">
      <p class="text-xs font-medium text-slate-500 mb-2">Add Action Item to the Employee</p>
      <div class="flex gap-2 flex-wrap">
        <input id="obAddTitle" class="inp flex-1 text-sm" placeholder="Item title…"/>
        <select id="obAddRole" class="inp text-sm" style="width:120px">
          <option value="employee">Employee</option>
          <option value="manager">Manager</option>
          <option value="hr_admin" selected>HR Admin</option>
          <option value="hr_manager">HR Manager</option>
        </select>
        <input id="obAddDueDate" type="datetime-local" class="inp text-sm" title="Due date/time (optional) — shows on the assigned role's calendar"/>
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

function closeObDetail(){closeModal('obDetailModal', () => viewingObId=null);}

// ---------------------------------------------------------------------------
// Checklist item attachments (optional proof-of-completion, e.g. a photo of
// laptop handover) — not required to mark an item Done, attachable any time.
// ---------------------------------------------------------------------------
const OB_ATTACH_MAX_BYTES = 6 * 1024 * 1024;

async function toggleObItemAttachments(clId, itemId) {
  const wrap = document.getElementById(`obitem-attach-${itemId}`);
  if (!wrap) return;
  const willShow = wrap.classList.contains('hidden');
  wrap.classList.toggle('hidden');
  if (willShow) await loadObItemAttachments(clId, itemId);
}

async function loadObItemAttachments(clId, itemId) {
  const res = await api(`/api/ob/checklists/${clId}/items/${itemId}/attachments`);
  const atts = res?.ok ? await res.json() : [];
  renderObItemAttachments(clId, itemId, atts);
}

function renderObItemAttachments(clId, itemId, atts) {
  const wrap = document.getElementById(`obitem-attach-${itemId}`);
  if (wrap) {
    wrap.innerHTML = atts.map(a=>`
      <div class="flex items-center gap-2 text-xs bg-slate-50 rounded-sm px-2 py-1">
        <a href="${a.data_url}" download="${esc(a.file_name)}" class="text-blue-600 hover:underline truncate flex-1">${esc(a.file_name)}</a>
        <span class="text-slate-400 shrink-0">${esc(a.uploaded_by)} · ${fmtDate(a.created_at)}</span>
        <button onclick="deleteObItemAttachment(${clId},${itemId},${a.id})" class="text-slate-400 hover:text-red-600 shrink-0">✕</button>
      </div>`).join('') +
      `<label class="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline cursor-pointer">
        + Attach photo/document
        <input type="file" multiple class="hidden" onchange="handleObAttachFiles(event,${clId},${itemId})"/>
      </label>`;
  }
  const badge = document.getElementById(`obitem-attach-badge-${itemId}`);
  if (badge) {
    badge.textContent = atts.length || '';
    badge.classList.toggle('hidden', atts.length === 0);
  }
}

async function handleObAttachFiles(e, clId, itemId) {
  const files = [...(e.target.files||[])];
  e.target.value = '';
  const payload = [];
  for (const file of files) {
    if (file.size > OB_ATTACH_MAX_BYTES) { alert(`"${file.name}" is too large. Please choose a file under ~6MB.`); continue; }
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    payload.push({file_name: file.name, mime_type: file.type||'application/octet-stream', data_url: dataUrl});
  }
  if (!payload.length) return;
  const res = await api(`/api/ob/checklists/${clId}/items/${itemId}/attachments`, {method:'POST', body: JSON.stringify(payload)});
  if (!res?.ok) { const d = await res?.json().catch(()=>({})); alert(d?.detail || 'Failed to upload'); return; }
  const atts = await res.json();
  renderObItemAttachments(clId, itemId, atts);
}

async function deleteObItemAttachment(clId, itemId, attachmentId) {
  if (!confirm('Remove this attachment?')) return;
  const res = await api(`/api/ob/checklists/${clId}/items/${itemId}/attachments/${attachmentId}`, {method:'DELETE'});
  if (!res?.ok) { const d = await res?.json().catch(()=>({})); alert(d?.detail || 'Failed to remove attachment'); return; }
  await loadObItemAttachments(clId, itemId);
}


async function openStartObModal(type) {
  document.getElementById('startObType').value=type;
  document.getElementById('startObTitle').textContent=type==='onboarding'?'Start Onboarding':'Start Offboarding';
  document.getElementById('startObSubmitBtn').textContent=type==='onboarding'?'Start Onboarding':'Start Offboarding';
  document.getElementById('startObNotes').value='';
  document.getElementById('startObErr').classList.add('hidden');
  document.getElementById('startObEnableProbation').checked=false;
  document.getElementById('startObProbationWrap').classList.toggle('hidden', type!=='onboarding');
  const sel=document.getElementById('startObEmpId');
  sel.innerHTML='<option value="">Select employee…</option>';
  employees.filter(e=>e.status==='Active').forEach(e=>{const o=document.createElement('option');o.value=e.employee_id;o.textContent=`${e.employee_id} — ${esc(displayName(e.full_name,e.preferred_name))}`;sel.appendChild(o);});
  initEmployeeSearchSelect('startObEmpId', 'Search employee…');
  const setSel=document.getElementById('startObTemplateSet');
  setSel.innerHTML='<option value="">Loading…</option>';
  const res=await api(`/api/ob/template-sets?type=${type}`);
  const sets=res?.ok?await res.json():[];
  setSel.innerHTML=sets.length?sets.map(s=>`<option value="${s.id}" ${s.is_default?'selected':''}>${esc(s.name)}${s.is_default?' (Default)':''} — ${s.item_count} item${s.item_count===1?'':'s'}</option>`).join(''):'<option value="">No templates configured</option>';
  document.getElementById('startObModal').classList.remove('hidden');
}
function closeStartObModal(){closeModal('startObModal');}

async function submitStartOb(e) {
  e.preventDefault();
  const err=document.getElementById('startObErr');
  err.classList.add('hidden');
  const type=document.getElementById('startObType').value;
  const setId=document.getElementById('startObTemplateSet').value;
  const body={employee_id:document.getElementById('startObEmpId').value,type,template_set_id:setId?parseInt(setId):null,notes:document.getElementById('startObNotes').value||null,enable_probation_review:type==='onboarding'&&document.getElementById('startObEnableProbation').checked};
  const res=await api('/api/ob/checklists',{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok){const d=await res?.json();err.textContent=d?.detail||'Failed';err.classList.remove('hidden');return;}
  closeStartObModal();
  loadObChecklists(type);
}

async function showObItemEdit(clId,itemId,title,description,assignedRole,dueDate) {
  const roles=[{v:'employee',l:'Employee'},{v:'manager',l:'Manager'},{v:'hr_admin',l:'HR Admin'},{v:'hr_manager',l:'HR Manager'}];
  const el=document.getElementById('obitem-'+itemId);
  if(!el) return;
  // due_date is stored 'YYYY-MM-DD HH:MI:SS' — a datetime-local input wants
  // 'YYYY-MM-DDTHH:MM' (no seconds, 'T' separator).
  const dueDateLocal=dueDate?dueDate.slice(0,16).replace(' ','T'):'';
  el.innerHTML=`
    <div class="flex-1 space-y-2 py-1">
      <input id="obedit-title-${itemId}" class="inp text-sm w-full" value="${esc(title)}"/>
      <div class="flex gap-2">
        <input id="obedit-desc-${itemId}" class="inp text-sm flex-1" placeholder="Description…" value="${esc(description)}"/>
        <select id="obedit-role-${itemId}" class="inp text-sm" style="width:120px">
          ${roles.map(r=>`<option value="${r.v}" ${r.v===assignedRole?'selected':''}>${r.l}</option>`).join('')}
        </select>
      </div>
      <div class="flex items-center gap-2">
        <label class="text-xs text-slate-500 whitespace-nowrap">Due date/time</label>
        <input id="obedit-duedate-${itemId}" type="datetime-local" class="inp text-sm" value="${dueDateLocal}"/>
        ${dueDate?`<button type="button" onclick="document.getElementById('obedit-duedate-${itemId}').value=''" class="text-xs text-slate-400 hover:text-red-500">Clear</button>`:''}
      </div>
      <div class="flex gap-2">
        <button onclick="saveObItemEdit(${clId},${itemId})" class="btn-primary text-xs px-3 py-1">Save</button>
        <button onclick="openObDetail(${clId})" class="text-xs text-slate-500 hover:text-slate-700 px-2">Cancel</button>
      </div>
    </div>`;
}

const saveObItemEdit = guardAsync(async function(clId,itemId) {
  const title=document.getElementById('obedit-title-'+itemId)?.value.trim();
  const desc=document.getElementById('obedit-desc-'+itemId)?.value.trim();
  const role=document.getElementById('obedit-role-'+itemId)?.value;
  const dueDate=document.getElementById('obedit-duedate-'+itemId)?.value||null;
  if(!title){alert('Title is required');return;}
  await api(`/api/ob/checklists/${clId}/items/${itemId}`,{method:'PUT',body:JSON.stringify({title,description:desc||null,assigned_role:role,due_date:dueDate})});
  openObDetail(clId);
});

async function deleteObItem(clId,itemId) {
  if(!confirm('Remove this item from the checklist?')) return;
  await api(`/api/ob/checklists/${clId}/items/${itemId}`,{method:'DELETE'});
  openObDetail(clId);
}

const addObItem = guardAsync(async function(clId) {
  const title=document.getElementById('obAddTitle')?.value.trim();
  const role=document.getElementById('obAddRole')?.value;
  const dueDate=document.getElementById('obAddDueDate')?.value||null;
  if(!title){alert('Title is required');return;}
  await api(`/api/ob/checklists/${clId}/items`,{method:'POST',body:JSON.stringify({title,assigned_role:role,due_date:dueDate})});
  openObDetail(clId);
});

async function deleteObChecklist(clId,type) {
  if(!confirm('Delete this checklist? This cannot be undone.')) return;
  await api(`/api/ob/checklists/${clId}`,{method:'DELETE'});
  loadObChecklists(type);
}

// ---------------------------------------------------------------------------
// Manage Templates — now an in-page tab (per type) instead of a modal. Each
// element id is suffixed with the type (`_onboarding`/`_offboarding`) since
// both pages can hold independent state; `oid()` builds those ids so the
// functions below stay type-agnostic.
// ---------------------------------------------------------------------------
const OB_ROLES_ORDER=['employee','manager','hr_admin','hr_manager'];
let obTmplCoursesCache={onboarding:[],offboarding:[]};
let obTmplSetsCache={onboarding:[],offboarding:[]};
let obTmplItemsCache={onboarding:[],offboarding:[]};
let obCurrentSetId={onboarding:null,offboarding:null};
let obTemplatesLoaded={onboarding:false,offboarding:false};
let obActiveTmplType='onboarding';

function oid(type,base){return `${base}_${type}`;}
function oel(type,base){return document.getElementById(oid(type,base));}

function switchObSubTab(type,tab) {
  document.getElementById(`obSubTab_${type}_checklists`)?.classList.remove('view-tab-active');
  document.getElementById(`obSubTab_${type}_templates`)?.classList.remove('view-tab-active');
  document.getElementById(`obSubTab_${type}_${tab}`)?.classList.add('view-tab-active');
  document.getElementById(`obSubPanel_${type}_checklists`).classList.toggle('hidden', tab!=='checklists');
  document.getElementById(`obSubPanel_${type}_templates`).classList.toggle('hidden', tab!=='templates');
  if(tab==='templates' && !obTemplatesLoaded[type]) {
    obTemplatesLoaded[type]=true;
    loadObTemplatesTab(type);
  }
}

function populateObRoleSelect(el, selected) {
  if(!el || !rolesCache.length) return;  // keep the static HTML fallback if roles failed to load
  el.innerHTML=rolesCache.map(r=>`<option value="${r.role_key}">${esc(r.display_name)}</option>`).join('');
  el.value=selected||'hr_admin';
}

async function loadObTemplatesTab(type) {
  hideObSetForm(type);
  if(!rolesCache.length) await loadRolesCache();
  populateObRoleSelect(oel(type,'obTmplRole'));
  populateObRoleSelect(document.getElementById('obTmplItemRole'));
  const coursesRes=await api('/api/ld/courses');
  obTmplCoursesCache[type]=coursesRes?.ok?await coursesRes.json():[];
  const courseOptions='<option value="">No linked course — manual completion</option>'+
    obTmplCoursesCache[type].map(c=>`<option value="${c.id}">${esc(c.title)}</option>`).join('');
  oel(type,'obTmplLdCourse').innerHTML=courseOptions;
  await loadObTemplateSets(type);
}

async function loadObTemplateSets(type, selectId) {
  const res=await api(`/api/ob/template-sets?type=${type}`);
  obTmplSetsCache[type]=res?.ok?await res.json():[];
  const sel=oel(type,'obTmplSetSelect');
  if(!obTmplSetsCache[type].length){
    sel.innerHTML='<option value="">No templates yet</option>';
    obCurrentSetId[type]=null;
    oel(type,'obTemplatesEmpty').classList.remove('hidden');
    renderObSwimlane(type);
    return;
  }
  oel(type,'obTemplatesEmpty').classList.add('hidden');
  sel.innerHTML=obTmplSetsCache[type].map(s=>`<option value="${s.id}">${esc(s.name)}${s.is_default?' (Default)':''} — ${s.item_count} item${s.item_count===1?'':'s'}</option>`).join('');
  obCurrentSetId[type]=selectId&&obTmplSetsCache[type].some(s=>s.id===selectId)?selectId:obTmplSetsCache[type][0].id;
  sel.value=String(obCurrentSetId[type]);
  await refreshObTemplatesList(type);
}

function switchObTemplateSet(type) {
  obCurrentSetId[type]=parseInt(oel(type,'obTmplSetSelect').value);
  refreshObTemplatesList(type);
}

function showObSetForm(type){
  oel(type,'obSetName').value='';
  oel(type,'obSetIsDefault').checked=false;
  oel(type,'obSetForm').classList.remove('hidden');
}
function hideObSetForm(type){oel(type,'obSetForm')?.classList.add('hidden');}

const saveObTemplateSet = guardAsync(async function(type) {
  const name=oel(type,'obSetName').value.trim();
  if(!name){alert('Template name is required');return;}
  const res=await api('/api/ob/template-sets',{method:'POST',body:JSON.stringify({type,name})});
  if(!res||!res.ok) return;
  const created=await res.json();
  if(oel(type,'obSetIsDefault').checked){
    await api(`/api/ob/template-sets/${created.id}`,{method:'PUT',body:JSON.stringify({name,is_default:true})});
  }
  hideObSetForm(type);
  await loadObTemplateSets(type, created.id);
});

async function renameObTemplateSet(type) {
  const setId=obCurrentSetId[type];
  if(!setId) return;
  const current=obTmplSetsCache[type].find(s=>s.id===setId);
  const name=prompt('Template name:', current?.name||'');
  if(!name||!name.trim()) return;
  const res=await api(`/api/ob/template-sets/${setId}`,{method:'PUT',body:JSON.stringify({name:name.trim(),is_default:!!current?.is_default})});
  if(!res||!res.ok) return;
  await loadObTemplateSets(type, setId);
}

async function setObTemplateSetDefault(type) {
  const setId=obCurrentSetId[type];
  if(!setId) return;
  const current=obTmplSetsCache[type].find(s=>s.id===setId);
  await api(`/api/ob/template-sets/${setId}`,{method:'PUT',body:JSON.stringify({name:current?.name||'', is_default:true})});
  await loadObTemplateSets(type, setId);
}

async function deleteObTemplateSet(type) {
  const setId=obCurrentSetId[type];
  if(!setId) return;
  if(!confirm('Delete this template? All its checklist items must be removed first.')) return;
  const res=await api(`/api/ob/template-sets/${setId}`,{method:'DELETE'});
  if(!res||!res.ok){const d=await res?.json();alert(d?.detail||'Failed to delete');return;}
  await loadObTemplateSets(type);
}

async function refreshObTemplatesList(type) {
  const setId=obCurrentSetId[type];
  if(!setId){obTmplItemsCache[type]=[];renderObSwimlane(type);return;}
  const res=await api(`/api/ob/templates?template_set_id=${setId}`);
  if(!res||!res.ok) return;
  obTmplItemsCache[type]=await res.json();
  renderObSwimlane(type);
}

async function moveObTemplate(type,id,direction) {
  await api(`/api/ob/templates/${id}/move`,{method:'POST',body:JSON.stringify({direction})});
  refreshObTemplatesList(type);
}

const addObTemplate = guardAsync(async function(type) {
  const title=oel(type,'obTmplTitle').value.trim();
  if(!title) return;
  const setId=obCurrentSetId[type];
  if(!setId){alert('Create a template first');return;}
  const courseVal=oel(type,'obTmplLdCourse').value;
  const dueRuleVal=oel(type,'obTmplDueRule').value;
  const body={
    type,template_set_id:setId,title,description:oel(type,'obTmplDesc').value.trim()||null,
    assigned_role:oel(type,'obTmplRole').value,
    linked_ld_course_id:courseVal?parseInt(courseVal):null,
    due_date_rule:dueRuleVal||null
  };
  const res=await api('/api/ob/templates',{method:'POST',body:JSON.stringify(body)});
  if(!res||!res.ok) return;
  oel(type,'obTmplTitle').value='';
  oel(type,'obTmplDesc').value='';
  oel(type,'obTmplLdCourse').value='';
  oel(type,'obTmplDueRule').value='';
  await loadObTemplateSets(type, setId);
});

async function deleteObTemplate(type,id) {
  await api(`/api/ob/templates/${id}`,{method:'DELETE'});
  await loadObTemplateSets(type, obCurrentSetId[type]);
}

function openObTmplItemModal(type,id) {
  const item=obTmplItemsCache[type].find(t=>t.id===id);
  if(!item) return;
  obActiveTmplType=type;
  document.getElementById('obTmplItemId').value=item.id;
  document.getElementById('obTmplItemTitle').value=item.title;
  document.getElementById('obTmplItemDesc').value=item.description||'';
  document.getElementById('obTmplItemRole').value=item.assigned_role;
  document.getElementById('obTmplItemDueRule').value=item.due_date_rule||'';
  const courseSel=document.getElementById('obTmplItemCourse');
  courseSel.innerHTML='<option value="">No linked course — manual completion</option>'+
    obTmplCoursesCache[type].map(c=>`<option value="${c.id}">${esc(c.title)}</option>`).join('');
  courseSel.value=item.linked_ld_course_id||'';
  document.getElementById('obTmplItemModal').classList.remove('hidden');
}
function closeObTmplItemModal(){closeModal('obTmplItemModal');}

const saveObTmplItemDetail = guardAsync(async function() {
  const type=obActiveTmplType;
  const id=document.getElementById('obTmplItemId').value;
  const title=document.getElementById('obTmplItemTitle').value.trim();
  if(!title){alert('Title is required');return;}
  const courseVal=document.getElementById('obTmplItemCourse').value;
  const dueRuleVal=document.getElementById('obTmplItemDueRule').value;
  const body={
    type,title,description:document.getElementById('obTmplItemDesc').value.trim()||null,
    assigned_role:document.getElementById('obTmplItemRole').value,
    linked_ld_course_id:courseVal?parseInt(courseVal):null,
    due_date_rule:dueRuleVal||null
  };
  const res=await api(`/api/ob/templates/${id}`,{method:'PUT',body:JSON.stringify(body)});
  if(!res||!res.ok) return;
  closeObTmplItemModal();
  await refreshObTemplatesList(type);
});

// ---------------------------------------------------------------------------
// Swimlane visualization — 4 role rows, steps placed left-to-right in
// checklist order (order_index), with elbow-connector arrows tracing the
// full sequence across lanes so a role handoff is visible at a glance
// (see the reference HR-workflow diagram this was modeled after).
// ---------------------------------------------------------------------------
function renderObSwimlane(type) {
  const items=obTmplItemsCache[type]||[];
  const wrap=oel(type,'obSwimlaneWrap');
  const grid=oel(type,'obSwimlaneGrid');
  const svg=oel(type,'obSwimlaneSvg');
  const emptyEl=oel(type,'obSwimlaneEmpty');
  if(!items.length){
    wrap.classList.add('hidden');
    emptyEl.classList.remove('hidden');
    grid.innerHTML='';
    svg.innerHTML='';
    return;
  }
  wrap.classList.remove('hidden');
  emptyEl.classList.add('hidden');

  // Base 4 built-in roles, plus any custom role actually assigned to one
  // of this set's items (appended in the order first seen) — so an
  // "IT Infra" item still gets its own swimlane row instead of vanishing.
  const rolesOrder=[...OB_ROLES_ORDER];
  items.forEach(item=>{ if(!rolesOrder.includes(item.assigned_role)) rolesOrder.push(item.assigned_role); });

  const colWidth=190, labelWidth=120, gap=12;
  grid.style.display='grid';
  grid.style.gridTemplateColumns=`${labelWidth}px repeat(${items.length}, ${colWidth}px)`;
  grid.style.gridTemplateRows=`repeat(${rolesOrder.length}, minmax(80px,auto))`;
  grid.style.gap=`${gap}px`;

  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  let html='';
  rolesOrder.forEach((role,rIdx)=>{
    html+=`<div style="grid-column:1;grid-row:${rIdx+1}" class="flex items-center">
      <span class="badge ${obRoleColor(role)} text-xs whitespace-nowrap">${esc(obRoleLabel(role))}</span>
    </div>`;
  });
  items.forEach((item,cIdx)=>{
    const rIdx=rolesOrder.indexOf(item.assigned_role);
    const linkedCourse=obTmplCoursesCache[type].find(c=>c.id===item.linked_ld_course_id);
    html+=`<div style="grid-column:${cIdx+2};grid-row:${rIdx+1}">
      <div id="${oid(type,'obSwimStep')}_${item.id}" class="${obRoleColor(item.assigned_role)} rounded-lg p-2 h-full flex flex-col shadow-xs border border-black/5">
        <div class="flex items-center justify-between gap-1 mb-1">
          <button onclick="moveObTemplate('${type}',${item.id},'up')" ${cIdx===0?'disabled':''} class="opacity-60 hover:opacity-100 disabled:opacity-20" title="Move earlier"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 19l-7-7 7-7"/></svg></button>
          <span class="text-[10px] font-semibold opacity-60">${cIdx+1}</span>
          <button onclick="moveObTemplate('${type}',${item.id},'down')" ${cIdx===items.length-1?'disabled':''} class="opacity-60 hover:opacity-100 disabled:opacity-20" title="Move later"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"/></svg></button>
        </div>
        <div class="flex-1 cursor-pointer" onclick="openObTmplItemModal('${type}',${item.id})">
          <p class="text-xs font-semibold leading-tight">${esc(item.title)}</p>
          ${linkedCourse?`<p class="text-[10px] mt-1 opacity-80 truncate" title="${esc(linkedCourse.title)}">🎓 ${esc(linkedCourse.title)}</p>`:''}
          ${item.due_date_rule?`<p class="text-[10px] mt-1 opacity-80 truncate" title="${esc(OB_DUE_DATE_RULE_LABELS[item.due_date_rule]||item.due_date_rule)}">📅 ${esc(OB_DUE_DATE_RULE_LABELS[item.due_date_rule]||item.due_date_rule)}</p>`:''}
        </div>
        ${canManage?`<div class="flex justify-end mt-1">
          <button onclick="deleteObTemplate('${type}',${item.id})" class="opacity-50 hover:opacity-100 hover:text-red-600" title="Remove"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"/></svg></button>
        </div>`:''}
      </div>
    </div>`;
  });
  grid.innerHTML=html;

  requestAnimationFrame(()=>drawObSwimlaneArrows(type,items));
}

function drawObSwimlaneArrows(type,items) {
  const svg=oel(type,'obSwimlaneSvg');
  const grid=oel(type,'obSwimlaneGrid');
  if(!svg||!grid||items.length<2) { if(svg) svg.innerHTML=''; return; }
  const gridRect=grid.getBoundingClientRect();
  const originRect=svg.getBoundingClientRect();
  svg.style.width=gridRect.width+'px';
  svg.style.height=gridRect.height+'px';
  svg.setAttribute('viewBox',`0 0 ${gridRect.width} ${gridRect.height}`);

  const markerId=`obArrowHead_${type}`;
  let defs=`<defs><marker id="${markerId}" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#334155"/></marker></defs>`;
  let paths='';
  for(let i=0;i<items.length-1;i++){
    const a=document.getElementById(`${oid(type,'obSwimStep')}_${items[i].id}`);
    const b=document.getElementById(`${oid(type,'obSwimStep')}_${items[i+1].id}`);
    if(!a||!b) continue;
    const ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
    const x1=ra.right-originRect.left, y1=ra.top+ra.height/2-originRect.top;
    const x2=rb.left-originRect.left, y2=rb.top+rb.height/2-originRect.top;
    let d;
    if(Math.abs(y1-y2)<2){
      d=`M${x1},${y1} L${x2-4},${y2}`;
    } else {
      const midX=x1+(x2-x1)/2;
      d=`M${x1},${y1} H${midX} V${y2} H${x2-4}`;
    }
    paths+=`<path d="${d}" stroke="#334155" stroke-width="1.5" fill="none" marker-end="url(#${markerId})"/>`;
  }
  svg.innerHTML=defs+paths;
}

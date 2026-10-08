// Onboarding / Offboarding
// ---------------------------------------------------------------------------
let viewingObId=null, obCurrentType='onboarding', obTemplatesCache={};
const OB_ROLE_LABELS={employee:'Employee',manager:'Manager',hr_admin:'HR Admin',hr_manager:'HR Manager',payroll_manager:'Payroll Manager',compensation_manager:'Compensation Manager'};
// Custom roles (Settings > Roles) have no fixed color/label above — fall
// back to a neutral badge and the role's own display_name from rolesCache.
// Colors come from core.js's shared ROLE_BADGE_COLORS, not a local map —
// see its own comment for why role colors specifically are shared across
// files rather than kept per-module like the other *_COLORS maps.
// Roles an item can be assigned to: every built-in plus this institution's
// custom roles (rolesCache), falling back to the 4 classic ones if the cache
// hasn't loaded.
function obAssignableRoles(){
  if(rolesCache.length) return rolesCache.map(r=>({v:r.role_key,l:r.display_name}));
  return OB_ROLES_ORDER.map(r=>({v:r,l:OB_ROLE_LABELS[r]||r}));
}
// The 4 classic roles first, then any other role actually holding an item
// (a custom role like IT Infra) in the order first seen — otherwise those
// items were counted in the progress bar but never shown, or tickable.
function obGroupItemsByRole(items){
  const roles=[...OB_ROLES_ORDER];
  items.forEach(i=>{ if(!roles.includes(i.assigned_role)) roles.push(i.assigned_role); });
  const grouped={};
  roles.forEach(r=>grouped[r]=[]);
  items.forEach(i=>grouped[i.assigned_role].push(i));
  return {roles,grouped};
}
// "Waiting for" text for a blocked checklist item. An employee isn't shown the
// titles of other roles' items (the server sends title:null for those).
function obWaitingForLabel(list){
  return (list||[]).map(w=>w.title||`a ${obRoleLabel(w.assigned_role)} task`).join(', ');
}
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
          ${myPending?`<span class="badge status-pending text-xs shrink-0">Action Required</span>`:''}
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
      <td class="px-4 py-3"><span class="badge ${c.status==='Completed'?'status-positive':'status-info'}">${c.status}</span></td>
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
// deep-links into My Goals & Appraisal / Team Review with the relevant
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
  badge.className=`badge ${cl.status==='Completed'?'status-positive':'status-info'}`;
  if(type==='onboarding') await renderObProbationPanel(clId, cl);
  else document.getElementById('obProbationPanel').innerHTML='';
  // Group items by role
  const {roles,grouped}=obGroupItemsByRole(cl.items);
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
        const isBlocked=!!item.blocked;
        const canAct=canComplete(role)&&cl.status==='In Progress'&&!(isLinked&&!isHR)&&!(isBlocked&&!isHR);
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
            ${isBlocked?`<p class="text-xs text-amber-600 mt-0.5" title="${isHR?'HR can still tick this item.':'Available once these are done.'}">⏳ Waiting for: ${esc(obWaitingForLabel(item.waiting_for))}${isHR?' (HR can override)':''}</p>`:''}
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
        <select id="obAddRole" class="inp text-sm" style="width:150px">
          ${obAssignableRoles().map(r=>`<option value="${esc(r.v)}"${r.v==='hr_admin'?' selected':''}>${esc(r.l)}</option>`).join('')}
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
  if(!res) return;
  if(!res.ok){
    // e.g. 403 "waiting for: …" when someone else finished/undid a prerequisite meanwhile.
    const d=await res.json().catch(()=>null);
    if(d?.detail) alert(apiErrorText(d.detail));
    await openObDetail(clId);
    return;
  }
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
  const roles=obAssignableRoles();
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
        <select id="obedit-role-${itemId}" class="inp text-sm" style="width:150px">
          ${roles.map(r=>`<option value="${esc(r.v)}" ${r.v===assignedRole?'selected':''}>${esc(r.l)}</option>`).join('')}
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
  await openObDetail(clId);
  loadObChecklists(obCurrentType); // the list's progress column counts items live — refresh it behind the modal
}

const addObItem = guardAsync(async function(clId) {
  const title=document.getElementById('obAddTitle')?.value.trim();
  const role=document.getElementById('obAddRole')?.value;
  const dueDate=document.getElementById('obAddDueDate')?.value||null;
  if(!title){alert('Title is required');return;}
  await api(`/api/ob/checklists/${clId}/items`,{method:'POST',body:JSON.stringify({title,assigned_role:role,due_date:dueDate})});
  await openObDetail(clId);
  loadObChecklists(obCurrentType);
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
  obModalDeps=[...(item.depends_on||[])];
  obModalDepsOriginal=[...obModalDeps];
  renderObTmplItemDeps();
  document.getElementById('obTmplItemModal').classList.remove('hidden');
}

// "Starts after" in the item dialog — the non-drag way to link items.
let obModalDeps=[], obModalDepsOriginal=[];
function renderObTmplItemDeps(){
  const type=obActiveTmplType;
  const id=+document.getElementById('obTmplItemId').value;
  const items=obTmplItemsCache[type]||[];
  const title=i=>items.find(x=>x.id===i)?.title||'';
  document.getElementById('obTmplItemDeps').innerHTML=obModalDeps.map(d=>
    `<span class="inline-flex items-center gap-1 text-xs bg-slate-100 border border-slate-200 rounded-md px-2 py-0.5">${esc(title(d))}<button type="button" onclick="removeObTmplItemDep(${d})" class="text-slate-400 hover:text-red-500" title="Remove">&times;</button></span>`
  ).join('')||'<span class="text-xs text-slate-400">Nothing — it can start straight away.</span>';
  // Offer every other item that isn't already chosen and wouldn't make a loop
  // (i.e. doesn't itself start after this item).
  const options=items.filter(i=>i.id!==id&&!obModalDeps.includes(i.id)&&!obStartsAfter(items,i.id,id));
  document.getElementById('obTmplItemDepAdd').innerHTML='<option value="">Add an item this one starts after…</option>'+
    options.map(i=>`<option value="${i.id}">${esc(i.title)} — ${esc(obRoleLabel(i.assigned_role))}</option>`).join('');
}
function addObTmplItemDep(){
  const sel=document.getElementById('obTmplItemDepAdd');
  const v=parseInt(sel.value);
  if(v&&!obModalDeps.includes(v)) obModalDeps.push(v);
  renderObTmplItemDeps();
}
function removeObTmplItemDep(id){
  obModalDeps=obModalDeps.filter(d=>d!==id);
  renderObTmplItemDeps();
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
  if(JSON.stringify([...obModalDeps].sort())!==JSON.stringify([...obModalDepsOriginal].sort())){
    const dres=await api(`/api/ob/templates/${id}/dependencies`,{method:'PUT',body:JSON.stringify({depends_on:obModalDeps})});
    if(!dres||!dres.ok){
      const d=await dres?.json().catch(()=>null);
      alert(d?.detail?apiErrorText(d.detail):'Could not save "Starts after".');
      await refreshObTemplatesList(type);
      return;
    }
  }
  closeObTmplItemModal();
  await refreshObTemplatesList(type);
});

// ---------------------------------------------------------------------------
// Template board — one column per role (every role is always shown, even
// with no items), each holding that role's checklist items top to bottom in
// order. Cards drag within a column (re-order) or onto another column (hand
// the item to that role); every change is saved on drop through one
// PUT .../template-sets/{id}/layout call carrying the whole set's order.
// There are no arrows: nothing in the data says one item depends on another
// (order_index is just a list order), so none are drawn until real
// dependencies exist.
// ---------------------------------------------------------------------------
let obDragId=null;

// Columns: the 4 classic roles first, then every other role this institution
// has (rolesCache), then any role an item still holds that is no longer in
// the cache (e.g. a deleted custom role) so its cards never vanish.
function obBoardRoles(items){
  const roles=[...OB_ROLES_ORDER];
  rolesCache.forEach(r=>{ if(!roles.includes(r.role_key)) roles.push(r.role_key); });
  items.forEach(i=>{ if(!roles.includes(i.assigned_role)) roles.push(i.assigned_role); });
  return roles;
}

// Pure: the set's new ordered [{id, assigned_role}] after dragging `dragId`
// into `targetRole`, just before card `beforeId` (null = bottom of that
// column). Other items keep their relative order.
function obApplyDrop(items, dragId, targetRole, beforeId){
  const moved=items.find(i=>i.id===dragId);
  if(!moved) return items.map(i=>({id:i.id,assigned_role:i.assigned_role}));
  const rest=items.filter(i=>i.id!==dragId).map(i=>({id:i.id,assigned_role:i.assigned_role}));
  const entry={id:dragId,assigned_role:targetRole};
  let at=beforeId==null?-1:rest.findIndex(i=>i.id===beforeId);
  if(at<0){
    let last=-1;
    rest.forEach((i,n)=>{ if(i.assigned_role===targetRole) last=n; });
    at=last>=0?last+1:rest.length;
  }
  rest.splice(at,0,entry);
  return rest;
}

function obLayoutChanged(items, layout){
  return layout.some((l,n)=>items[n].id!==l.id||items[n].assigned_role!==l.assigned_role);
}

async function obSaveLayout(type, layout){
  const items=obTmplItemsCache[type];
  if(!obLayoutChanged(items,layout)) return;
  const setId=obCurrentSetId[type];
  const before=items;
  // Optimistic: show the new arrangement immediately, roll back on failure.
  const byId=new Map(items.map(i=>[i.id,i]));
  obTmplItemsCache[type]=layout.map(l=>({...byId.get(l.id),assigned_role:l.assigned_role}));
  renderObSwimlane(type);
  const res=await api(`/api/ob/template-sets/${setId}/layout`,{method:'PUT',body:JSON.stringify({items:layout})});
  if(res&&res.ok){ obTmplItemsCache[type]=await res.json(); renderObSwimlane(type); return; }
  const d=await res?.json().catch(()=>null);
  alert(d?.detail?apiErrorText(d.detail):'Could not save the new arrangement.');
  if(res&&res.status===409) await refreshObTemplatesList(type);
  else { obTmplItemsCache[type]=before; renderObSwimlane(type); }
}

// ---- Dependencies ("this item starts after those") -----------------------
// Pure: row of every item. A card with no prerequisites sits at the top of
// its role's column; one with prerequisites sits below ALL of them (so a
// chain reads top to bottom), and two cards never share a cell — the later
// one in the set's order is pushed down a row.
function obComputeRows(items){
  const rows={}, taken={};
  let pending=[...items], progressed=true;
  while(pending.length&&progressed){
    progressed=false;
    pending=pending.filter(it=>{
      const pre=(it.depends_on||[]).filter(id=>items.some(x=>x.id===id));
      if(pre.some(id=>rows[id]===undefined)) return true;
      let row=pre.length?Math.max(...pre.map(id=>rows[id]))+1:0;
      taken[it.assigned_role]=taken[it.assigned_role]||new Set();
      while(taken[it.assigned_role].has(row)) row++;
      taken[it.assigned_role].add(row);
      rows[it.id]=row; progressed=true; return false;
    });
  }
  // Defensive: a (server-rejected) loop would leave items unplaced — park them at the bottom.
  let bottom=Math.max(-1,...Object.values(rows))+1;
  pending.forEach(it=>{ rows[it.id]=bottom++; });
  return rows;
}

// Pure: does `id` already start after `targetId`, directly or through a chain?
function obStartsAfter(items, id, targetId){
  const byId=new Map(items.map(i=>[i.id,i]));
  const seen=new Set(), stack=[id];
  while(stack.length){
    const n=stack.pop();
    if(n===targetId&&n!==id) return true;
    if(seen.has(n)) continue;
    seen.add(n);
    (byId.get(n)?.depends_on||[]).forEach(p=>stack.push(p));
  }
  return false;
}

function obBoardNotice(type,text,isError){
  const el=oel(type,'obBoardMsg');
  if(!el) return;
  el.textContent=text||'';
  el.classList.toggle('hidden',!text);
  el.classList.toggle('text-red-600',!!isError);
  el.classList.toggle('text-slate-500',!isError);
}

let obSelectedLink=null; // {type, from, to} — the arrow showing a remove cross

async function obSetDependencies(type, itemId, dependsOn){
  const items=obTmplItemsCache[type];
  const before=obComputeRows(items);
  const res=await api(`/api/ob/templates/${itemId}/dependencies`,{method:'PUT',body:JSON.stringify({depends_on:dependsOn})});
  if(!res||!res.ok){
    const d=await res?.json().catch(()=>null);
    obBoardNotice(type,d?.detail?apiErrorText(d.detail):'Could not save the link.',true);
    return false;
  }
  const saved=await res.json();
  const item=obTmplItemsCache[type].find(i=>i.id===itemId);
  if(item) item.depends_on=saved.depends_on;
  obSelectedLink=null;
  const after=obComputeRows(obTmplItemsCache[type]);
  const moved=obTmplItemsCache[type].filter(i=>after[i.id]!==before[i.id]).length;
  renderObSwimlane(type);
  obBoardNotice(type,moved?`${moved} card${moved===1?'':'s'} moved down to stay below ${moved===1?'its prerequisites':'their prerequisites'}.`:'',false);
  return true;
}

// Cards as shown, top to bottom, for one role — what up/down and drops mean.
function obColumnOrder(items, role){
  const rows=obComputeRows(items);
  return items.filter(i=>i.assigned_role===role)
    .sort((a,b)=>rows[a.id]-rows[b.id]);
}

// Move a card one place up/down inside its own column (touch/keyboard
// alternative to dragging).
function moveObTemplateInColumn(type,id,direction){
  const items=obTmplItemsCache[type];
  const me=items.find(i=>i.id===id); if(!me) return;
  const col=obColumnOrder(items,me.assigned_role);
  const idx=col.findIndex(i=>i.id===id);
  let beforeId;
  if(direction==='up'){ if(idx<=0) return; beforeId=col[idx-1].id; }
  else { if(idx>=col.length-1) return; beforeId=idx+2<col.length?col[idx+2].id:null; }
  obSaveLayout(type,obApplyDrop(items,id,me.assigned_role,beforeId));
}

function addObTemplateForRole(type,role){
  const sel=oel(type,'obTmplRole');
  if(sel) sel.value=role;
  const title=oel(type,'obTmplTitle');
  title?.scrollIntoView({behavior:'smooth',block:'center'});
  title?.focus();
}

function renderObSwimlane(type) {
  const items=obTmplItemsCache[type]||[];
  const wrap=oel(type,'obSwimlaneWrap');
  const grid=oel(type,'obSwimlaneGrid');
  const emptyEl=oel(type,'obSwimlaneEmpty');
  // No template selected/created yet: nothing to arrange.
  if(!obCurrentSetId[type]){
    wrap.classList.add('hidden'); emptyEl.classList.add('hidden'); grid.innerHTML='';
    return;
  }
  wrap.classList.remove('hidden');
  emptyEl.classList.add('hidden');

  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  const roles=obBoardRoles(items);
  const rows=obComputeRows(items);
  const maxRow=Math.max(-1,...Object.values(rows));
  const totalRows=maxRow+3; // header + card rows + the "Add item" row
  const arrow=(d)=>`<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${d}"/></svg>`;

  let html=`<svg id="${oid(type,'obArrows')}" class="absolute left-0 top-0" style="pointer-events:none;z-index:0;overflow:visible"></svg>`;
  roles.forEach((role,ci)=>{
    const mine=obColumnOrder(items,role);
    html+=`<div data-ob-col="${esc(role)}" style="grid-column:${ci+1};grid-row:1 / span ${totalRows}" class="rounded-lg border border-dashed border-slate-200"></div>`;
    html+=`<div style="grid-column:${ci+1};grid-row:1;z-index:1" class="text-center pt-1.5">
      <span class="badge ${obRoleColor(role)} text-xs whitespace-nowrap">${esc(obRoleLabel(role))}</span>
      <p class="text-[10px] text-slate-400 mt-0.5">${mine.length} item${mine.length===1?'':'s'}</p>
    </div>`;
    html+=canManage?`<div style="grid-column:${ci+1};grid-row:${totalRows};z-index:1" class="self-end px-1.5 pb-1.5">
      <button type="button" onclick="addObTemplateForRole('${type}','${esc(role)}')" data-ob-add class="w-full text-xs text-slate-500 hover:text-blue-600 border border-dashed border-slate-300 rounded-lg py-1.5 bg-white">+ Add item${mine.length?'':'<span class="block text-[10px] text-slate-400">or drop a card here</span>'}</button>
    </div>`:'';
    mine.forEach((item,n)=>{
      const linkedCourse=obTmplCoursesCache[type].find(c=>c.id===item.linked_ld_course_id);
      const dueLabel=item.due_date_rule?(OB_DUE_DATE_RULE_LABELS[item.due_date_rule]||item.due_date_rule):'';
      const after=(item.depends_on||[]).length;
      html+=`<div draggable="${canManage}" data-ob-card="${item.id}" data-ob-role="${esc(role)}" id="${oid(type,'obSwimStep')}_${item.id}" style="grid-column:${ci+1};grid-row:${rows[item.id]+2};z-index:1" class="${obRoleColor(role)} rounded-lg p-2 mx-1.5 self-start flex flex-col shadow-xs border border-black/5 relative ${canManage?'cursor-grab':''}">
        <div class="flex items-start gap-1.5 ${canManage?'pr-5':''}">
          <span class="text-[10px] font-semibold opacity-60 mt-0.5 min-w-3">${n+1}</span>
          <div class="flex-1 cursor-pointer min-w-0" onclick="openObTmplItemModal('${type}',${item.id})">
            <p class="text-xs font-semibold leading-tight break-words">${esc(item.title)}</p>
            ${after?`<p class="text-[10px] mt-1 opacity-80">↳ after ${after} item${after===1?'':'s'}</p>`:''}
            ${linkedCourse?`<p class="text-[10px] mt-1 opacity-80 truncate" title="${esc(linkedCourse.title)}">🎓 ${esc(linkedCourse.title)}</p>`:''}
            ${dueLabel?`<p class="text-[10px] mt-1 opacity-80 truncate" title="${esc(dueLabel)}">📅 ${esc(dueLabel)}</p>`:''}
          </div>
        </div>
        ${canManage?`<span data-ob-link="${item.id}" draggable="false" title="Drag onto another card to make that card start after this one" class="absolute right-1 top-1/2 -mt-2.5 w-5 h-5 rounded-full bg-white/80 border border-slate-300 text-slate-500 flex items-center justify-center cursor-crosshair" style="touch-action:none"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg></span>
        <div class="flex items-center justify-between mt-1.5">
          <div class="flex gap-1">
            <button onclick="moveObTemplateInColumn('${type}',${item.id},'up')" ${n===0?'disabled':''} class="opacity-60 hover:opacity-100 disabled:opacity-20" title="Move up">${arrow('M5 15l7-7 7 7')}</button>
            <button onclick="moveObTemplateInColumn('${type}',${item.id},'down')" ${n===mine.length-1?'disabled':''} class="opacity-60 hover:opacity-100 disabled:opacity-20" title="Move down">${arrow('M19 9l-7 7-7-7')}</button>
          </div>
          <button onclick="deleteObTemplate('${type}',${item.id})" class="opacity-50 hover:opacity-100 hover:text-red-600" title="Remove"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
        </div>`:''}
      </div>`;
    });
  });
  grid.className='relative';
  grid.style.cssText=`display:grid;grid-template-columns:repeat(${roles.length},11.5rem);column-gap:1.75rem;row-gap:1.5rem;width:max-content;min-height:8rem`;
  grid.innerHTML=html;
  bindObBoardDnD(type,grid);
  requestAnimationFrame(()=>drawObArrows(type));
}

// Straight arrows between linked cards: centre to centre, clipped to the
// cards' edges. They sit under the cards (a line crossing another card is
// hidden there), above the column backgrounds.
function drawObArrows(type){
  const grid=oel(type,'obSwimlaneGrid');
  const svg=oel(type,'obArrows');
  if(!grid||!svg) return;
  const items=obTmplItemsCache[type]||[];
  const gr=grid.getBoundingClientRect();
  svg.setAttribute('width',grid.scrollWidth); svg.setAttribute('height',grid.scrollHeight);
  const box=id=>{
    const el=document.getElementById(`${oid(type,'obSwimStep')}_${id}`);
    if(!el) return null;
    const r=el.getBoundingClientRect();
    return {cx:r.left+r.width/2-gr.left, cy:r.top+r.height/2-gr.top, hw:r.width/2+3, hh:r.height/2+3};
  };
  const edge=(b,dx,dy,sign)=>{
    const k=Math.min(dx===0?Infinity:b.hw/Math.abs(dx), dy===0?Infinity:b.hh/Math.abs(dy));
    return {x:b.cx+sign*dx*k, y:b.cy+sign*dy*k};
  };
  const markerId=`obArrowHead_${type}`;
  let out=`<defs><marker id="${markerId}" markerWidth="9" markerHeight="9" refX="7" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#334155"/></marker></defs>`;
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  items.forEach(it=>(it.depends_on||[]).forEach(fromId=>{
    const a=box(fromId), b=box(it.id);
    if(!a||!b) return;
    const dx=b.cx-a.cx, dy=b.cy-a.cy;
    const p1=edge(a,dx,dy,1), p2=edge(b,dx,dy,-1);
    const on=obSelectedLink&&obSelectedLink.type===type&&obSelectedLink.from===fromId&&obSelectedLink.to===it.id;
    out+=`<g style="color:${on?'#dc2626':'#334155'}">
      ${canManage?`<line data-ob-arrow="${fromId}:${it.id}" x1="${p1.x}" y1="${p1.y}" x2="${p2.x}" y2="${p2.y}" stroke="transparent" stroke-width="14" style="pointer-events:stroke;cursor:pointer"/>`:''}
      <line x1="${p1.x}" y1="${p1.y}" x2="${p2.x}" y2="${p2.y}" stroke="currentColor" stroke-width="${on?2:1.5}" marker-end="url(#${markerId})"/>`;
    if(on&&canManage){
      const mx=(p1.x+p2.x)/2, my=(p1.y+p2.y)/2;
      out+=`<g data-ob-unlink="${fromId}:${it.id}" style="pointer-events:all;cursor:pointer"><title>Remove this link</title><circle cx="${mx}" cy="${my}" r="9" fill="white" stroke="currentColor"/><path d="M${mx-3},${my-3} L${mx+3},${my+3} M${mx+3},${my-3} L${mx-3},${my+3}" stroke="currentColor" stroke-width="1.5"/></g>`;
    }
    out+='</g>';
  }));
  if(obLinkDrag&&obLinkDrag.type===type){
    out+=`<line x1="${obLinkDrag.x0}" y1="${obLinkDrag.y0}" x2="${obLinkDrag.x}" y2="${obLinkDrag.y}" stroke="#2563eb" stroke-width="2" stroke-dasharray="5 4"/>`;
  }
  svg.innerHTML=out;
}
window.addEventListener('resize',()=>{ ['onboarding','offboarding'].forEach(t=>{ if(oel(t,'obArrows')) drawObArrows(t); }); });

let obLinkDrag=null; // {type, from, x0, y0, x, y}

// Which column (role) a pointer x position is over, from the column backgrounds.
function obColumnAt(grid,x){
  return [...grid.querySelectorAll('[data-ob-col]')].find(c=>{const r=c.getBoundingClientRect(); return x>=r.left&&x<=r.right;})||null;
}

// First card (as displayed, top to bottom) in `role`'s column whose midpoint
// is below the pointer; null = drop at the bottom of that column.
function obCardAfter(grid,role,y,dragId){
  return [...grid.querySelectorAll(`[data-ob-card][data-ob-role="${CSS.escape(role)}"]`)]
    .filter(c=>+c.dataset.obCard!==dragId)
    .sort((a,b)=>a.getBoundingClientRect().top-b.getBoundingClientRect().top)
    .find(c=>{const b=c.getBoundingClientRect(); return y<b.top+b.height/2;})||null;
}

function bindObBoardDnD(type,grid){
  if(!HR_MANAGE_ROLES.includes(currentUser?.role)) return;
  const clearMarks=()=>{
    grid.querySelectorAll('.ob-drop-ind').forEach(x=>x.remove());
    grid.querySelectorAll('[data-ob-col]').forEach(c=>c.classList.remove('bg-blue-50'));
  };
  const pt=(e)=>{const r=grid.getBoundingClientRect(); return {x:e.clientX-r.left,y:e.clientY-r.top};};

  // ---- Move a card (re-order / hand to another role) ----
  grid.ondragstart=e=>{
    const card=e.target.closest?.('[data-ob-card]'); if(!card) return;
    obDragId=+card.dataset.obCard;
    e.dataTransfer.effectAllowed='move';
    e.dataTransfer.setData('text/plain',String(obDragId));
    setTimeout(()=>card.classList.add('opacity-40'),0);
  };
  grid.ondragend=()=>{ obDragId=null; clearMarks(); grid.querySelectorAll('[data-ob-card]').forEach(c=>c.classList.remove('opacity-40')); };
  grid.ondragover=e=>{
    if(obDragId==null) return;
    const col=obColumnAt(grid,e.clientX);
    if(!col) return;
    e.preventDefault();
    clearMarks();
    col.classList.add('bg-blue-50');
    const before=obCardAfter(grid,col.dataset.obCol,e.clientY,obDragId);
    const gr=grid.getBoundingClientRect(), cr=col.getBoundingClientRect();
    let top;
    if(before) top=before.getBoundingClientRect().top-gr.top-8;
    else {
      const mine=[...grid.querySelectorAll(`[data-ob-card][data-ob-role="${CSS.escape(col.dataset.obCol)}"]`)].filter(c=>+c.dataset.obCard!==obDragId);
      top=mine.length?Math.max(...mine.map(c=>c.getBoundingClientRect().bottom))-gr.top+8:cr.top-gr.top+52;
    }
    const ind=document.createElement('div');
    ind.className='ob-drop-ind absolute h-1 rounded bg-blue-500';
    ind.style.cssText=`left:${cr.left-gr.left+6}px;width:${cr.width-12}px;top:${top}px;z-index:2;pointer-events:none`;
    grid.appendChild(ind);
  };
  grid.ondragleave=e=>{ if(!grid.contains(e.relatedTarget)) clearMarks(); };
  grid.ondrop=e=>{
    if(obDragId==null) return;
    const col=obColumnAt(grid,e.clientX);
    if(!col) return;
    e.preventDefault();
    const dragId=obDragId, role=col.dataset.obCol;
    const before=obCardAfter(grid,role,e.clientY,dragId);
    obDragId=null; clearMarks();
    obSaveLayout(type,obApplyDrop(obTmplItemsCache[type],dragId,role,before?+before.dataset.obCard:null));
  };

  // ---- Link two cards: drag a card's link handle onto another card ----
  grid.onpointerdown=e=>{
    const h=e.target.closest?.('[data-ob-link]');
    if(!h) return;
    e.preventDefault();
    const card=h.closest('[data-ob-card]'); if(card) card.draggable=false;
    const gr=grid.getBoundingClientRect(), hr=h.getBoundingClientRect();
    const x0=hr.left+hr.width/2-gr.left, y0=hr.top+hr.height/2-gr.top;
    obLinkDrag={type,from:+h.dataset.obLink,x0,y0,x:x0,y:y0,card};
    obSelectedLink=null;
    try{ h.setPointerCapture(e.pointerId); }catch(_){}
  };
  grid.onpointermove=e=>{
    if(!obLinkDrag||obLinkDrag.type!==type) return;
    const p=pt(e); obLinkDrag.x=p.x; obLinkDrag.y=p.y;
    grid.querySelectorAll('[data-ob-card]').forEach(c=>c.classList.remove('ring-2','ring-blue-500'));
    const t=document.elementFromPoint(e.clientX,e.clientY)?.closest?.('[data-ob-card]');
    if(t&&+t.dataset.obCard!==obLinkDrag.from) t.classList.add('ring-2','ring-blue-500');
    drawObArrows(type);
  };
  const endLink=async e=>{
    if(!obLinkDrag||obLinkDrag.type!==type) return;
    const {from,card}=obLinkDrag; obLinkDrag=null;
    if(card) card.draggable=true;
    grid.querySelectorAll('[data-ob-card]').forEach(c=>c.classList.remove('ring-2','ring-blue-500'));
    const t=e.type==='pointerup'?document.elementFromPoint(e.clientX,e.clientY)?.closest?.('[data-ob-card]'):null;
    if(!t||+t.dataset.obCard===from){ drawObArrows(type); return; }
    const toId=+t.dataset.obCard, items=obTmplItemsCache[type];
    const target=items.find(i=>i.id===toId);
    const title=id=>items.find(i=>i.id===id)?.title||'';
    if((target.depends_on||[]).includes(from)){ obBoardNotice(type,'Already linked.',false); drawObArrows(type); return; }
    if(obStartsAfter(items,from,toId)){
      obBoardNotice(type,`Can't link: "${title(from)}" already starts after "${title(toId)}", so this would make a loop.`,true);
      drawObArrows(type); return;
    }
    obBoardNotice(type,'',false);
    await obSetDependencies(type,toId,[...(target.depends_on||[]),from]);
  };
  grid.onpointerup=endLink;
  grid.onpointercancel=endLink;

  // ---- Click an arrow to show its remove cross; click the cross to remove ----
  grid.onclick=e=>{
    const un=e.target.closest?.('[data-ob-unlink]');
    if(un){
      const [from,to]=un.dataset.obUnlink.split(':').map(Number);
      const target=obTmplItemsCache[type].find(i=>i.id===to);
      obSetDependencies(type,to,(target?.depends_on||[]).filter(x=>x!==from));
      return;
    }
    const ar=e.target.closest?.('[data-ob-arrow]');
    if(ar){
      const [from,to]=ar.dataset.obArrow.split(':').map(Number);
      obSelectedLink={type,from,to}; drawObArrows(type); return;
    }
    if(obSelectedLink){ obSelectedLink=null; drawObArrows(type); }
  };
}

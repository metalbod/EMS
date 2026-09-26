// Audit Log
// ---------------------------------------------------------------------------
// Server-paginated (routers/audit.py's limit/offset + X-Total-Count
// response header) — an active institution's audit trail can run into the
// thousands of rows, and used to be silently capped at the most recent
// 200 with no way to reach anything older. Deliberately a small,
// dedicated page/pageSize/total state here rather than createListState
// (list-state.js): that module sorts+slices an already-fully-fetched
// array client-side, which is exactly the "fetch everything up front"
// pattern this page is moving away from — and Audit Log has no
// interactive column-sort UI to preserve anyway (unlike the tables that
// use createListState), just the action filter it already had.
let auditPage = 1, auditPageSize = 50, auditTotal = 0;

async function loadAuditLog() {
  if(currentUser.role==='superadmin'&&!currentInstitution) return;
  const action=document.getElementById('auditActionFilter')?.value||'';
  const offset=(auditPage-1)*auditPageSize;
  const params=new URLSearchParams({limit:String(auditPageSize), offset:String(offset)});
  if(action) params.set('action', action);
  const res=await api(`/api/audit-logs?${params}`);
  if(!res||!res.ok) return;
  const logs=await res.json();
  auditTotal=parseInt(res.headers.get('X-Total-Count')||'0',10);
  const tbody=document.getElementById('auditTableBody');
  const empty=document.getElementById('auditEmpty');
  const pagination=document.getElementById('auditPagination');
  if(!logs.length){
    tbody.innerHTML='';
    empty.classList.remove('hidden');
    pagination?.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');
  pagination?.classList.remove('hidden');
  document.getElementById('auditPageSize').value=String(auditPageSize);
  document.getElementById('auditPageInfo').textContent=
    `${offset+1}-${Math.min(offset+auditPageSize, auditTotal)} of ${auditTotal}`;
  const colors={CREATE:'bg-blue-100 text-blue-700',UPDATE:'bg-amber-100 text-amber-700',ACTIVATE:'bg-emerald-100 text-emerald-700',DEACTIVATE:'bg-slate-100 text-slate-600'};
  tbody.innerHTML=logs.map(l=>`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3 text-xs text-slate-500">${fmtDateTime(l.timestamp, true)}</td>
      <td class="px-4 py-3"><p class="text-sm font-medium">${esc(l.actor_username)}</p><p class="text-xs text-slate-400">${esc(l.actor_role)}</p></td>
      <td class="px-4 py-3"><p class="text-sm">${esc(l.target_employee_name)}</p><p class="text-xs text-slate-400">${esc(l.target_employee_id)}</p></td>
      <td class="px-4 py-3"><span class="badge ${colors[l.action]||''}">${l.action}</span></td>
      <td class="px-4 py-3 hidden lg:table-cell">
        ${l.changes?.length?`<details class="text-xs"><summary class="text-slate-500 cursor-pointer">${l.changes.length} field(s)</summary>
          <div class="mt-1 space-y-0.5">${l.changes.map(c=>`<span class="block text-slate-600"><b>${esc(c.label)}:</b> <s class="text-red-400">${esc(c.old)}</s> → <span class="text-emerald-600">${esc(c.new)}</span></span>`).join('')}</div></details>`
        :'<span class="text-slate-300">—</span>'}
      </td>
    </tr>`).join('');
}

function setAuditPageSize(size) { auditPageSize=parseInt(size)||50; auditPage=1; loadAuditLog(); }
function auditPagePrev() { if(auditPage>1){ auditPage--; loadAuditLog(); } }
function auditPageNext() {
  const totalPages=Math.max(1, Math.ceil(auditTotal/auditPageSize));
  if(auditPage<totalPages){ auditPage++; loadAuditLog(); }
}

// Login Attempts tab — same server-paginated shape as the Activity Log
// above (routers/audit.py's list_login_audit_log), just a separate
// page/pageSize/total state since the two tabs paginate independently.
let loginAuditPage = 1, loginAuditPageSize = 50, loginAuditTotal = 0;

function switchAuditTab(tab) {
  document.querySelectorAll('[data-atab]').forEach(b=>{
    b.classList.toggle('view-tab-active', b.dataset.atab===tab);
    b.classList.toggle('text-slate-500', b.dataset.atab!==tab);
  });
  document.getElementById('at-activity').classList.toggle('hidden', tab!=='at-activity');
  document.getElementById('at-system').classList.toggle('hidden', tab!=='at-system');
  document.getElementById('at-logins').classList.toggle('hidden', tab!=='at-logins');
  if(tab==='at-system') loadSystemActivity();
  if(tab==='at-logins') loadLoginAuditLog();
}

// System Activity tab — GET /api/entity-audit-log (routers/audit.py): the
// generic entity_audit_log (users, roles & permissions, approval workflows,
// payroll, institution/secret settings, …) plus a read-only union of the
// older per-module trails (recruitment, onboarding, L&D, leave, timesheet,
// appraisal). Same server-paginated shape as the tabs above.
let sysAuditPage = 1, sysAuditPageSize = 50, sysAuditTotal = 0;

async function loadSystemActivity() {
  if(currentUser.role==='superadmin'&&!currentInstitution) return;
  const offset=(sysAuditPage-1)*sysAuditPageSize;
  const params=new URLSearchParams({limit:String(sysAuditPageSize), offset:String(offset)});
  const val=id=>document.getElementById(id)?.value||'';
  if(val('sysAuditModule')) params.set('module', val('sysAuditModule'));
  if(val('sysAuditActor').trim()) params.set('actor', val('sysAuditActor').trim());
  if(val('sysAuditFrom')) params.set('date_from', val('sysAuditFrom'));
  if(val('sysAuditTo')) params.set('date_to', val('sysAuditTo'));
  const res=await api(`/api/entity-audit-log?${params}`);
  if(!res||!res.ok) return;
  const rows=await res.json();
  sysAuditTotal=parseInt(res.headers.get('X-Total-Count')||'0',10);
  const tbody=document.getElementById('sysAuditTableBody');
  const empty=document.getElementById('sysAuditEmpty');
  const pagination=document.getElementById('sysAuditPagination');
  if(!rows.length){
    tbody.innerHTML='';
    empty.classList.remove('hidden');
    pagination?.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');
  pagination?.classList.remove('hidden');
  document.getElementById('sysAuditPageSize').value=String(sysAuditPageSize);
  document.getElementById('sysAuditPageInfo').textContent=
    `${offset+1}-${Math.min(offset+sysAuditPageSize, sysAuditTotal)} of ${sysAuditTotal}`;
  tbody.innerHTML=rows.map(r=>`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">${fmtDateTime(r.created_at, true)}</td>
      <td class="px-4 py-3 text-sm whitespace-nowrap">${esc(r.module)}</td>
      <td class="px-4 py-3"><p class="text-sm">${esc(r.entity_label||r.entity_id||'—')}</p><p class="text-xs text-slate-400">${esc(r.entity_type)}${r.entity_id?` #${esc(r.entity_id)}`:''}</p></td>
      <td class="px-4 py-3"><span class="badge status-neutral">${esc(r.action)}</span></td>
      <td class="px-4 py-3 text-xs text-slate-600 max-w-md">${r.detail?`<p>${esc(r.detail)}</p>`:''}${auditChangesHtml(r.changes)}${!r.detail&&!(r.changes||[]).length?'<span class="text-slate-300">—</span>':''}</td>
      <td class="px-4 py-3"><p class="text-sm font-medium">${esc(r.actor_username||'system')}</p><p class="text-xs text-slate-400">${esc(r.actor_role||'')}</p></td>
    </tr>`).join('');
}

function setSysAuditPageSize(size) { sysAuditPageSize=parseInt(size)||50; sysAuditPage=1; loadSystemActivity(); }
function sysAuditPagePrev() { if(sysAuditPage>1){ sysAuditPage--; loadSystemActivity(); } }
function sysAuditPageNext() {
  const totalPages=Math.max(1, Math.ceil(sysAuditTotal/sysAuditPageSize));
  if(sysAuditPage<totalPages){ sysAuditPage++; loadSystemActivity(); }
}

async function loadLoginAuditLog() {
  if(currentUser.role==='superadmin'&&!currentInstitution) return;
  const success=document.getElementById('loginAuditSuccessFilter')?.value||'';
  const offset=(loginAuditPage-1)*loginAuditPageSize;
  const params=new URLSearchParams({limit:String(loginAuditPageSize), offset:String(offset)});
  if(success) params.set('success', success);
  const res=await api(`/api/login-audit-log?${params}`);
  if(!res||!res.ok) return;
  const logs=await res.json();
  loginAuditTotal=parseInt(res.headers.get('X-Total-Count')||'0',10);
  const tbody=document.getElementById('loginAuditTableBody');
  const empty=document.getElementById('loginAuditEmpty');
  const pagination=document.getElementById('loginAuditPagination');
  if(!logs.length){
    tbody.innerHTML='';
    empty.classList.remove('hidden');
    pagination?.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');
  pagination?.classList.remove('hidden');
  document.getElementById('loginAuditPageSize').value=String(loginAuditPageSize);
  document.getElementById('loginAuditPageInfo').textContent=
    `${offset+1}-${Math.min(offset+loginAuditPageSize, loginAuditTotal)} of ${loginAuditTotal}`;
  const reasonLabels={invalid_credentials:'Invalid credentials', inactive:'Account deactivated', institution_suspended:'Institution suspended'};
  tbody.innerHTML=logs.map(l=>`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3 text-xs text-slate-500">${fmtDateTime(l.created_at, true)}</td>
      <td class="px-4 py-3 text-sm font-medium">${esc(l.username)}</td>
      <td class="px-4 py-3"><span class="badge ${l.success?'bg-emerald-100 text-emerald-700':'bg-red-100 text-red-700'}">${l.success?'Success':'Failed'}</span></td>
      <td class="px-4 py-3 text-xs text-slate-500 hidden lg:table-cell">${l.reason?esc(reasonLabels[l.reason]||l.reason):'<span class="text-slate-300">—</span>'}</td>
      <td class="px-4 py-3 text-xs text-slate-500 hidden md:table-cell">${l.ip_address?esc(l.ip_address):'<span class="text-slate-300">—</span>'}</td>
    </tr>`).join('');
}

function setLoginAuditPageSize(size) { loginAuditPageSize=parseInt(size)||50; loginAuditPage=1; loadLoginAuditLog(); }
function loginAuditPagePrev() { if(loginAuditPage>1){ loginAuditPage--; loadLoginAuditLog(); } }
function loginAuditPageNext() {
  const totalPages=Math.max(1, Math.ceil(loginAuditTotal/loginAuditPageSize));
  if(loginAuditPage<totalPages){ loginAuditPage++; loadLoginAuditLog(); }
}

// ---------------------------------------------------------------------------

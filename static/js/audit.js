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

// ---------------------------------------------------------------------------

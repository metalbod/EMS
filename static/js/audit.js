// Audit Log
// ---------------------------------------------------------------------------
async function loadAuditLog() {
  if(currentUser.role==='superadmin'&&!currentInstitution) return;
  const action=document.getElementById('auditActionFilter')?.value||'';
  const res=await api(`/api/audit-logs${action?`?action=${action}`:''}`);
  if(!res||!res.ok) return;
  const logs=await res.json();
  const tbody=document.getElementById('auditTableBody');
  const empty=document.getElementById('auditEmpty');
  if(!logs.length){tbody.innerHTML='';empty.classList.remove('hidden');return;}
  empty.classList.add('hidden');
  const colors={CREATE:'bg-blue-100 text-blue-700',UPDATE:'bg-amber-100 text-amber-700',ACTIVATE:'bg-emerald-100 text-emerald-700',DEACTIVATE:'bg-slate-100 text-slate-600'};
  tbody.innerHTML=logs.map(l=>`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3 text-xs text-slate-500">${l.timestamp.replace('T',' ')}</td>
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

// ---------------------------------------------------------------------------

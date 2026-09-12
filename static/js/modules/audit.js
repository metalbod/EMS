let auditPage=1,auditPageSize=50,auditTotal=0;async function loadAuditLog(){var r;if(currentUser.role==="superadmin"&&!currentInstitution)return;const e=((r=document.getElementById("auditActionFilter"))==null?void 0:r.value)||"",n=(auditPage-1)*auditPageSize,i=new URLSearchParams({limit:String(auditPageSize),offset:String(n)});e&&i.set("action",e);const a=await api(`/api/audit-logs?${i}`);if(!a||!a.ok)return;const c=await a.json();auditTotal=parseInt(a.headers.get("X-Total-Count")||"0",10);const l=document.getElementById("auditTableBody"),o=document.getElementById("auditEmpty"),s=document.getElementById("auditPagination");if(!c.length){l.innerHTML="",o.classList.remove("hidden"),s==null||s.classList.add("hidden");return}o.classList.add("hidden"),s==null||s.classList.remove("hidden"),document.getElementById("auditPageSize").value=String(auditPageSize),document.getElementById("auditPageInfo").textContent=`${n+1}-${Math.min(n+auditPageSize,auditTotal)} of ${auditTotal}`;const u={CREATE:"bg-blue-100 text-blue-700",UPDATE:"bg-amber-100 text-amber-700",ACTIVATE:"bg-emerald-100 text-emerald-700",DEACTIVATE:"bg-slate-100 text-slate-600"};l.innerHTML=c.map(t=>{var m;return`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3 text-xs text-slate-500">${fmtDateTime(t.timestamp,!0)}</td>
      <td class="px-4 py-3"><p class="text-sm font-medium">${esc(t.actor_username)}</p><p class="text-xs text-slate-400">${esc(t.actor_role)}</p></td>
      <td class="px-4 py-3"><p class="text-sm">${esc(t.target_employee_name)}</p><p class="text-xs text-slate-400">${esc(t.target_employee_id)}</p></td>
      <td class="px-4 py-3"><span class="badge ${u[t.action]||""}">${t.action}</span></td>
      <td class="px-4 py-3 hidden lg:table-cell">
        ${(m=t.changes)!=null&&m.length?`<details class="text-xs"><summary class="text-slate-500 cursor-pointer">${t.changes.length} field(s)</summary>
          <div class="mt-1 space-y-0.5">${t.changes.map(d=>`<span class="block text-slate-600"><b>${esc(d.label)}:</b> <s class="text-red-400">${esc(d.old)}</s> \u2192 <span class="text-emerald-600">${esc(d.new)}</span></span>`).join("")}</div></details>`:'<span class="text-slate-300">\u2014</span>'}
      </td>
    </tr>`}).join("")}function setAuditPageSize(e){auditPageSize=parseInt(e)||50,auditPage=1,loadAuditLog()}function auditPagePrev(){auditPage>1&&(auditPage--,loadAuditLog())}function auditPageNext(){const e=Math.max(1,Math.ceil(auditTotal/auditPageSize));auditPage<e&&(auditPage++,loadAuditLog())}

//# sourceMappingURL=audit.js.map

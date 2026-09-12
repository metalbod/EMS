async function loadRolesPage(){await loadRolesCache(),renderRolesTable()}function renderRolesTable(){const e=document.getElementById("rolesTableBody");e&&(e.innerHTML=rolesCache.map(t=>`
    <tr class="border-t border-slate-100">
      <td class="px-4 py-3 font-medium text-slate-800">${esc(t.display_name)}</td>
      <td class="px-4 py-3 text-slate-500 font-mono text-xs">${esc(t.role_key)}</td>
      <td class="px-4 py-3">
        <span class="badge text-xs ${t.is_builtin?"bg-slate-100 text-slate-500":"bg-blue-100 text-blue-700"}">${t.is_builtin?"Built-in":"Custom"}</span>
      </td>
      <td class="px-4 py-3 text-right">
        ${t.is_builtin?"":`<button onclick="deleteRole(${t.id})" class="text-slate-300 hover:text-red-500" title="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>`}
      </td>
    </tr>`).join(""))}const createRole=guardAsync(async function(){const e=document.getElementById("roleFormErr");e.classList.add("hidden");const t=document.getElementById("roleNewName"),l=t.value.trim();if(!l){e.textContent="Role name is required",e.classList.remove("hidden");return}const s=await api("/api/roles",{method:"POST",body:JSON.stringify({display_name:l})});if(!(s!=null&&s.ok)){const a=await(s==null?void 0:s.json().catch(()=>({})));e.textContent=(a==null?void 0:a.detail)||"Failed to add role",e.classList.remove("hidden");return}t.value="",await loadRolesCache(),renderRolesTable()});async function deleteRole(e){if(!confirm("Delete this role?"))return;const t=await api(`/api/roles/${e}`,{method:"DELETE"});if(!(t!=null&&t.ok)){const l=await(t==null?void 0:t.json().catch(()=>({})));alert((l==null?void 0:l.detail)||"Failed to delete role");return}await loadRolesCache(),renderRolesTable()}let permissionMatrixData=null,matrixExpanded=new Set;function switchRolesTab(e){document.getElementById("rolesTab_roles").classList.toggle("view-tab-active",e==="roles"),document.getElementById("rolesTab_roles").classList.toggle("text-slate-500",e!=="roles"),document.getElementById("rolesTab_matrix").classList.toggle("view-tab-active",e==="matrix"),document.getElementById("rolesTab_matrix").classList.toggle("text-slate-500",e!=="matrix"),document.getElementById("rolesTabPanel_roles").classList.toggle("hidden",e!=="roles"),document.getElementById("rolesTabPanel_matrix").classList.toggle("hidden",e!=="matrix"),e==="matrix"&&!permissionMatrixData&&loadPermissionMatrix()}async function loadPermissionMatrix(){const e=await api("/api/roles/permission-matrix");e!=null&&e.ok&&(permissionMatrixData=await e.json(),renderPermissionMatrix())}function matrixToggleModule(e){matrixExpanded.has(e)?matrixExpanded.delete(e):matrixExpanded.add(e),renderPermissionMatrix()}async function matrixSetOverride(e,t,l){const s=await api("/api/roles/permission-matrix/override",{method:"PUT",body:JSON.stringify({action_key:e,role:t,access_value:l})});if(!(s!=null&&s.ok)){const a=await(s==null?void 0:s.json().catch(()=>({})));alert((a==null?void 0:a.detail)||"Failed to update permission");return}await loadPermissionMatrix()}async function matrixResetOverride(e,t){const l=await api(`/api/roles/permission-matrix/override?action_key=${encodeURIComponent(e)}&role=${encodeURIComponent(t)}`,{method:"DELETE"});if(!(l!=null&&l.ok)){const s=await(l==null?void 0:l.json().catch(()=>({})));alert((s==null?void 0:s.detail)||"Failed to reset permission");return}await loadPermissionMatrix()}const MATRIX_CELL_STYLE={allow:{cls:"bg-emerald-100 text-emerald-700",label:"Allowed"},deny:{cls:"bg-slate-100 text-slate-400",label:"Denied"},own:{cls:"bg-blue-100 text-blue-700",label:"Own record"},subordinate:{cls:"bg-purple-100 text-purple-700",label:"Subordinates"},configurable:{cls:"bg-amber-100 text-amber-700",label:"Configurable"},no_restriction:{cls:"bg-indigo-100 text-indigo-700",label:"No restriction"}};function renderPermissionMatrix(){var u;const e=document.getElementById("matrixWrap");if(!e||!permissionMatrixData)return;const t=(((u=document.getElementById("matrixSearch"))==null?void 0:u.value)||"").trim().toLowerCase(),l=[...permissionMatrixData.roles,...permissionMatrixData.custom_roles||[]],s=permissionMatrixData.role_labels,a=permissionMatrixData.modules.map(i=>{const c=t?i.actions.filter(o=>o.action.toLowerCase().includes(t)||i.module.toLowerCase().includes(t)):i.actions;if(!c.length)return"";const x=t?!0:matrixExpanded.has(i.module),g=c.map(o=>`
      <tr class="border-t border-slate-100">
        <td class="px-4 py-2.5 align-top">
          <div class="text-sm font-medium text-slate-800">${esc(o.action)}</div>
          <div class="text-[11px] text-slate-400 font-mono">${esc(o.path)}</div>
          ${o.note?`<div class="text-[11px] text-slate-500 mt-1">${esc(o.note)}</div>`:""}
        </td>
        ${l.map(n=>{const d=o.access[n]||"deny",r=MATRIX_CELL_STYLE[d]||MATRIX_CELL_STYLE.deny,p=!!(o.editable&&o.editable[n]),m=p&&o.access_default&&o.access_default[n]!==d;if(!p)return`<td class="px-2 py-2.5 text-center align-top">
              <span class="inline-block text-[10px] font-semibold px-2 py-1 rounded-sm ${r.cls}" title="${esc(s[n]||n)}: ${r.label}">${r.label}</span>
            </td>`;const b=d==="allow"?"deny":"allow";return`<td class="px-2 py-2.5 text-center align-top">
            <button onclick="matrixSetOverride('${esc(o.key)}','${esc(n)}','${b}')"
                    class="inline-block text-[10px] font-semibold px-2 py-1 rounded-sm ${r.cls} ring-2 ring-offset-1 ${m?"ring-slate-400":"ring-transparent"} hover:ring-slate-300 cursor-pointer"
                    title="${esc(s[n]||n)}: ${r.label} \u2014 click to set ${b==="allow"?"Allowed":"Denied"}${m?" (customized for this institution)":""}">
              ${r.label}
            </button>
            ${m?`<button onclick="matrixResetOverride('${esc(o.key)}','${esc(n)}')" class="block mx-auto mt-0.5 text-[9px] text-slate-400 hover:text-slate-600 underline" title="Reset to default">reset</button>`:""}
          </td>`}).join("")}
      </tr>`).join("");return`
      <div class="border-t border-slate-200 first:border-t-0">
        <button onclick="matrixToggleModule('${esc(i.module)}')" class="w-full flex items-center gap-2 px-4 py-2.5 bg-slate-50 hover:bg-slate-100 text-left">
          <svg class="w-3.5 h-3.5 text-slate-400 transition-transform shrink-0 ${x?"rotate-90":""}" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.21 5.23a.75.75 0 011.06.02l4.5 4.75a.75.75 0 010 1.04l-4.5 4.75a.75.75 0 11-1.08-1.04L11.168 10 7.23 5.79a.75.75 0 01-.02-1.06z" clip-rule="evenodd"/></svg>
          <span class="text-sm font-semibold text-slate-700">${esc(i.module)}</span>
          <span class="text-xs text-slate-400">${c.length} action${c.length!==1?"s":""}</span>
        </button>
        ${x?`<div class="overflow-x-auto"><table class="w-full text-sm">
          <thead><tr class="bg-white text-[10px] uppercase text-slate-400">
            <th class="px-4 py-2 text-left font-medium">Action</th>
            ${l.map(o=>`<th class="px-2 py-2 text-center font-medium whitespace-nowrap">${esc(s[o]||o)}</th>`).join("")}
          </tr></thead>
          <tbody>${g}</tbody>
        </table></div>`:""}
      </div>`}).join("");e.innerHTML=a||'<p class="text-sm text-slate-400 p-4">No actions match your search.</p>'}

//# sourceMappingURL=roles.js.map

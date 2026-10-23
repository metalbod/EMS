async function loadRolesPage(){await loadRolesCache(),renderRolesTable()}function renderRolesTable(){const t=document.getElementById("rolesTableBody");t&&(t.innerHTML=rolesCache.map(e=>`
    <tr class="border-t border-slate-100">
      <td class="px-4 py-3 font-medium text-slate-800">${esc(e.display_name)}</td>
      <td class="px-4 py-3 text-slate-500 font-mono text-xs">${esc(e.role_key)}</td>
      <td class="px-4 py-3">
        <span class="badge text-xs ${e.is_builtin?"bg-slate-100 text-slate-500":"bg-blue-100 text-blue-700"}">${e.is_builtin?"Built-in":"Custom"}</span>
      </td>
      <td class="px-4 py-3 text-right">
        ${e.is_builtin?"":`<button onclick="deleteRole(${e.id})" class="text-slate-300 hover:text-red-500" title="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>`}
      </td>
    </tr>`).join(""))}const createRole=guardAsync(async function(){const t=document.getElementById("roleFormErr");t.classList.add("hidden");const e=document.getElementById("roleNewName"),l=e.value.trim();if(!l){t.textContent="Role name is required",t.classList.remove("hidden");return}const s=await api("/api/roles",{method:"POST",body:JSON.stringify({display_name:l})});if(!(s!=null&&s.ok)){const a=await(s==null?void 0:s.json().catch(()=>({})));t.textContent=(a==null?void 0:a.detail)||"Failed to add role",t.classList.remove("hidden");return}e.value="",await loadRolesCache(),renderRolesTable()});async function deleteRole(t){if(!confirm("Delete this role?"))return;const e=await api(`/api/roles/${t}`,{method:"DELETE"});if(!(e!=null&&e.ok)){const l=await(e==null?void 0:e.json().catch(()=>({})));notify((l==null?void 0:l.detail)||"Failed to delete role");return}await loadRolesCache(),renderRolesTable()}let permissionMatrixData=null,matrixExpanded=new Set;function switchRolesTab(t){document.getElementById("rolesTab_roles").classList.toggle("view-tab-active",t==="roles"),document.getElementById("rolesTab_roles").classList.toggle("text-slate-500",t!=="roles"),document.getElementById("rolesTab_matrix").classList.toggle("view-tab-active",t==="matrix"),document.getElementById("rolesTab_matrix").classList.toggle("text-slate-500",t!=="matrix"),document.getElementById("rolesTabPanel_roles").classList.toggle("hidden",t!=="roles"),document.getElementById("rolesTabPanel_matrix").classList.toggle("hidden",t!=="matrix"),t==="matrix"&&!permissionMatrixData&&loadPermissionMatrix()}async function loadPermissionMatrix(){const t=await api("/api/roles/permission-matrix");t!=null&&t.ok&&(permissionMatrixData=await t.json(),renderPermissionMatrix())}function matrixToggleModule(t){matrixExpanded.has(t)?matrixExpanded.delete(t):matrixExpanded.add(t),renderPermissionMatrix()}async function matrixSetOverride(t,e,l){const s=await api("/api/roles/permission-matrix/override",{method:"PUT",body:JSON.stringify({action_key:t,role:e,access_value:l})});if(!(s!=null&&s.ok)){const a=await(s==null?void 0:s.json().catch(()=>({})));notify((a==null?void 0:a.detail)||"Failed to update permission");return}await loadPermissionMatrix()}async function matrixResetOverride(t,e){const l=await api(`/api/roles/permission-matrix/override?action_key=${encodeURIComponent(t)}&role=${encodeURIComponent(e)}`,{method:"DELETE"});if(!(l!=null&&l.ok)){const s=await(l==null?void 0:l.json().catch(()=>({})));notify((s==null?void 0:s.detail)||"Failed to reset permission");return}await loadPermissionMatrix()}const MATRIX_CELL_STYLE={allow:{cls:"bg-emerald-100 text-emerald-700",label:"Allowed"},deny:{cls:"bg-slate-100 text-slate-400",label:"Denied"},own:{cls:"bg-blue-100 text-blue-700",label:"Own record"},subordinate:{cls:"bg-purple-100 text-purple-700",label:"Subordinates"},configurable:{cls:"bg-amber-100 text-amber-700",label:"Configurable"},no_restriction:{cls:"bg-indigo-100 text-indigo-700",label:"No restriction"}};function renderPermissionMatrix(){var u;const t=document.getElementById("matrixWrap");if(!t||!permissionMatrixData)return;const e=(((u=document.getElementById("matrixSearch"))==null?void 0:u.value)||"").trim().toLowerCase(),l=[...permissionMatrixData.roles,...permissionMatrixData.custom_roles||[]],s=permissionMatrixData.role_labels,a=permissionMatrixData.modules.map(i=>{const r=e?i.actions.filter(o=>o.action.toLowerCase().includes(e)||i.module.toLowerCase().includes(e)):i.actions;if(!r.length)return"";const x=e?!0:matrixExpanded.has(i.module),g=r.map(o=>`
      <tr class="border-t border-slate-100">
        <td class="px-4 py-2.5 align-top">
          <div class="text-sm font-medium text-slate-800">${esc(o.action)}</div>
          <div class="text-[11px] text-slate-400 font-mono">${esc(o.path)}</div>
          ${o.note?`<div class="text-[11px] text-slate-500 mt-1">${esc(o.note)}</div>`:""}
        </td>
        ${l.map(n=>{const d=o.access[n]||"deny",c=MATRIX_CELL_STYLE[d]||MATRIX_CELL_STYLE.deny,p=!!(o.editable&&o.editable[n]),m=p&&o.access_default&&o.access_default[n]!==d;if(!p)return`<td class="px-2 py-2.5 text-center align-top">
              <span class="inline-block text-[10px] font-semibold px-2 py-1 rounded-sm ${c.cls}" title="${esc(s[n]||n)}: ${c.label}">${c.label}</span>
            </td>`;const b=d==="allow"?"deny":"allow";return`<td class="px-2 py-2.5 text-center align-top">
            <button onclick="matrixSetOverride('${esc(o.key)}','${esc(n)}','${b}')"
                    class="inline-block text-[10px] font-semibold px-2 py-1 rounded-sm ${c.cls} ring-2 ring-offset-1 ${m?"ring-slate-400":"ring-transparent"} hover:ring-slate-300 cursor-pointer"
                    title="${esc(s[n]||n)}: ${c.label} \u2014 click to set ${b==="allow"?"Allowed":"Denied"}${m?" (customized for this institution)":""}">
              ${c.label}
            </button>
            ${m?`<button onclick="matrixResetOverride('${esc(o.key)}','${esc(n)}')" class="block mx-auto mt-0.5 text-[9px] text-slate-400 hover:text-slate-600 underline" title="Reset to default">reset</button>`:""}
          </td>`}).join("")}
      </tr>`).join("");return`
      <div class="border-t border-slate-200 first:border-t-0">
        <button onclick="matrixToggleModule('${esc(i.module)}')" class="w-full flex items-center gap-2 px-4 py-2.5 bg-slate-50 hover:bg-slate-100 text-left">
          <svg class="w-3.5 h-3.5 text-slate-400 transition-transform shrink-0 ${x?"rotate-90":""}" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.21 5.23a.75.75 0 011.06.02l4.5 4.75a.75.75 0 010 1.04l-4.5 4.75a.75.75 0 11-1.08-1.04L11.168 10 7.23 5.79a.75.75 0 01-.02-1.06z" clip-rule="evenodd"/></svg>
          <span class="text-sm font-semibold text-slate-700">${esc(i.module)}</span>
          <span class="text-xs text-slate-400">${r.length} action${r.length!==1?"s":""}</span>
        </button>
        ${x?`<div class="table-scroll" style="max-height:40vh"><table class="w-full text-sm">
          <thead class="bg-white sticky top-0 z-10"><tr class="bg-white text-[10px] uppercase text-slate-400">
            <th class="px-4 py-2 text-left font-medium">Action</th>
            ${l.map(o=>`<th class="px-2 py-2 text-center font-medium whitespace-nowrap">${esc(s[o]||o)}</th>`).join("")}
          </tr></thead>
          <tbody>${g}</tbody>
        </table></div>`:""}
      </div>`}).join("");t.innerHTML=a||'<p class="text-sm text-slate-400 p-4">No actions match your search.</p>'}

//# sourceMappingURL=roles.js.map

let instLogoDataUrl=null;function setInstLogoPreview(e){instLogoDataUrl=e||null;const t=document.getElementById("instLogoPreview"),n=document.getElementById("instLogoPlaceholder"),a=document.getElementById("instLogoRemoveBtn");instLogoDataUrl?(t.src=instLogoDataUrl,t.classList.remove("hidden"),n.classList.add("hidden"),a.classList.remove("hidden")):(t.src="",t.classList.add("hidden"),n.classList.remove("hidden"),a.classList.add("hidden"))}function handleInstLogoFile(e){var a;const t=(a=e.target.files)==null?void 0:a[0];if(!t)return;if(t.size>500*1024){alert("Logo image is too large. Please choose a file under ~500KB."),e.target.value="";return}const n=new FileReader;n.onload=()=>setInstLogoPreview(n.result),n.readAsDataURL(t)}function removeInstLogo(){setInstLogoPreview(null),document.getElementById("instLogoFile").value=""}const instList=createListState({sortKey:"created_at",sortDir:"desc",sortValue:(e,t)=>t==="created_at"?new Date(e[t]).getTime():e[t]});async function loadInstitutions(){const e=await api("/api/institutions");!e||!e.ok||(institutions=await e.json(),instList.resetPage(),loadActiveUsers())}async function loadActiveUsers(){var l;const e=((l=document.getElementById("activeUsersWindow"))==null?void 0:l.value)||5,t=await api(`/api/admin/active-users?minutes=${e}`);if(!t||!t.ok)return;const n=await t.json();document.getElementById("activeUsersCount").textContent=`${n.active_count} active`,document.getElementById("activeUsersTotal").textContent=n.total_users;const a=document.getElementById("activeUsersList"),i=document.getElementById("activeUsersEmpty");if(!n.active_users.length){a.innerHTML="",i.classList.remove("hidden");return}i.classList.add("hidden"),a.innerHTML=n.active_users.map(o=>`
    <div class="flex items-center justify-between text-sm px-3 py-2 rounded-lg bg-slate-50">
      <div>
        <span class="font-medium">${esc(o.full_name)}</span>
        <span class="text-slate-400"> \xB7 ${esc(o.username)} \xB7 ${esc(o.role)}</span>
        ${o.institution_name?`<span class="text-slate-400"> \xB7 ${esc(o.institution_name)}</span>`:""}
      </div>
      <span class="text-xs text-slate-400">${esc(o.last_active)}</span>
    </div>`).join("")}function setInstSort(e){instList.setSort(e),renderInstTable()}function setInstPageSize(e){instList.setPageSize(e),renderInstTable()}function instPagePrev(){instList.prevPage(),renderInstTable()}function instPageNext(){instList.nextPage(institutions.length),renderInstTable()}function renderInstTable(){const e=document.getElementById("instTableBody"),t=document.getElementById("instEmpty"),n=document.getElementById("instPagination"),a={starter:"bg-slate-100 text-slate-600",professional:"bg-blue-100 text-blue-700",enterprise:"bg-violet-100 text-violet-700"},i={byok:{label:"Own key",cls:"bg-violet-100 text-violet-700"},platform:{label:"Platform",cls:"bg-slate-100 text-slate-600"},none:{label:"None",cls:"bg-amber-100 text-amber-700"}};if(instList.updateSortArrows(".inst-sort-arrow"),!institutions.length){e.innerHTML="",t.classList.remove("hidden"),n.classList.add("hidden");return}t.classList.add("hidden"),n.classList.remove("hidden"),document.getElementById("instPageSize").value=String(instList.pageSize);const{pageItems:l,start:o,total:d}=instList.view(institutions);document.getElementById("instPageInfo").textContent=`${o+1}-${Math.min(o+instList.pageSize,d)} of ${d}`,e.innerHTML=l.map(s=>{var c,m,r;return`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <div class="flex items-center gap-3">
          ${s.logo_url?`<img src="${s.logo_url}" class="w-9 h-9 rounded-lg object-cover shrink-0"/>`:`<div class="w-9 h-9 bg-blue-100 rounded-lg flex items-center justify-center text-blue-700 text-xs font-bold shrink-0">${esc(s.code.slice(0,2).toUpperCase())}</div>`}
          <div>
            <p class="font-medium">${esc(s.name)}</p>
            <p class="text-xs text-slate-400">${esc(s.code)}</p>
          </div>
        </div>
      </td>
      <td class="px-4 py-3 hidden sm:table-cell">
        <p class="text-sm">${esc(s.contact_name||"\u2014")}</p>
        <p class="text-xs text-slate-400">${esc(s.contact_email)}</p>
      </td>
      <td class="px-4 py-3"><span class="badge ${a[s.plan]||""}">${((c=meta.plan_labels)==null?void 0:c[s.plan])||s.plan}</span></td>
      <td class="px-4 py-3 text-center">
        <p class="text-sm font-semibold">${s.employee_count}</p>
        <p class="text-xs text-slate-400">/ ${s.max_employees}</p>
      </td>
      <td class="px-4 py-3"><span class="badge ${s.status==="Active"?"status-positive":"status-negative"}">${s.status}</span></td>
      <td class="px-4 py-3"><span class="badge ${((m=i[s.ai_key_status])==null?void 0:m.cls)||""}">${((r=i[s.ai_key_status])==null?void 0:r.label)||"\u2014"}</span></td>
      <td class="px-4 py-3">
        <p class="text-sm">${fmtDate(s.created_at)}</p>
        <p class="text-xs text-slate-400">${s.created_at.slice(11,19)}</p>
      </td>
      <td class="px-4 py-3">
        <div class="flex justify-end gap-1 flex-wrap">
          <button onclick="enterInstitutionContext(this.dataset.inst)" data-inst='${JSON.stringify(s).replace(/'/g,"&apos;")}' class="btn-primary" style="font-size:.75rem;padding:.25rem .75rem">Manage</button>
          <button onclick="openInstModal(this.dataset.inst)" data-inst='${JSON.stringify(s).replace(/'/g,"&apos;")}' class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem">Edit</button>
          <button onclick="toggleInstStatus(${s.id},'${s.status==="Active"?"Suspended":"Active"}')" class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem;color:${s.status==="Active"?"#dc2626":"#059669"}">${s.status==="Active"?"Suspend":"Activate"}</button>
        </div>
      </td>
    </tr>
  `}).join("")}function openInstModal(e=null){const t=typeof e=="string"?JSON.parse(e):e,n=!!(t!=null&&t.id);document.getElementById("instModalTitle").textContent=n?"Edit Institution":"Add Institution",document.getElementById("instSubmitBtn").textContent=n?"Save Changes":"Create Institution",document.getElementById("instId").value=(t==null?void 0:t.id)||"",document.getElementById("instLogoFile").value="",setInstLogoPreview((t==null?void 0:t.logo_url)||null),document.getElementById("instName").value=(t==null?void 0:t.name)||"",document.getElementById("instCode").value=(t==null?void 0:t.code)||"",document.getElementById("instCode").disabled=n,document.getElementById("instPlan").value=(t==null?void 0:t.plan)||"starter",document.getElementById("instMaxEmp").value=(t==null?void 0:t.max_employees)||50,document.getElementById("instContactName").value=(t==null?void 0:t.contact_name)||"",document.getElementById("instContactEmail").value=(t==null?void 0:t.contact_email)||"",document.getElementById("instPhone").value=(t==null?void 0:t.phone)||"",document.getElementById("instAddress").value=(t==null?void 0:t.address)||"",document.getElementById("instAdminSection").classList.toggle("hidden",n),["instAdminUser","instAdminName","instAdminPass","instAdminEmail"].forEach(a=>{const i=document.getElementById(a);i.required=!n&&a!=="instAdminEmail",i.value=""}),document.getElementById("instFormErr").classList.add("hidden"),document.getElementById("instModal").classList.remove("hidden")}function closeInstModal(){closeModal("instModal")}async function submitInstForm(e){e.preventDefault();const t=document.getElementById("instId").value,n=!!t,a=document.getElementById("instFormErr");a.classList.add("hidden");const i={name:document.getElementById("instName").value.trim(),code:document.getElementById("instCode").value.trim().toUpperCase(),logo_url:instLogoDataUrl,contact_name:document.getElementById("instContactName").value.trim()||null,contact_email:document.getElementById("instContactEmail").value.trim(),phone:document.getElementById("instPhone").value.trim()||null,address:document.getElementById("instAddress").value.trim()||null,plan:document.getElementById("instPlan").value,max_employees:parseInt(document.getElementById("instMaxEmp").value)||50};n||(i.admin_username=document.getElementById("instAdminUser").value.trim(),i.admin_full_name=document.getElementById("instAdminName").value.trim(),i.admin_password=document.getElementById("instAdminPass").value,i.admin_email=document.getElementById("instAdminEmail").value.trim()||null);const l=await api(n?`/api/institutions/${t}`:"/api/institutions",{method:n?"PUT":"POST",body:JSON.stringify(i)});if(l){if(!l.ok){const o=await l.json();a.textContent=o.detail||"Failed to save institution",a.classList.remove("hidden");return}closeInstModal(),await loadInstitutions(),renderInstTable()}}async function toggleInstStatus(e,t){const n=await api(`/api/institutions/${e}/status`,{method:"PATCH",body:JSON.stringify({status:t})});n!=null&&n.ok&&(await loadInstitutions(),renderInstTable())}

//# sourceMappingURL=institutions.js.map

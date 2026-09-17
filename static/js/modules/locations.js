let locations=[],editingLocationId=null;async function loadLocations(){const o=await api("/api/institutions/"+currentUser.institution_id+"/locations");if(!o||!o.ok)return;locations=(await o.json()).locations||[],renderLocationsTable()}function renderLocationsTable(){var a;const o=document.getElementById("locTableBody"),e=document.getElementById("locEmpty"),t=HR_MANAGE_ROLES.includes(currentUser==null?void 0:currentUser.role);if((a=document.getElementById("addLocationBtn"))==null||a.classList.toggle("hidden",!t),!locations.length){o.innerHTML="",e.classList.remove("hidden");return}e.classList.add("hidden"),o.innerHTML=locations.map(n=>`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <div>
          <p class="font-medium text-slate-800">${esc(n.name)}</p>
          <p class="text-xs text-slate-400">${n.location_type==="hq"?"\u2B50 HQ":n.location_type}</p>
        </div>
      </td>
      <td class="px-4 py-3 hidden md:table-cell text-sm text-slate-600 font-mono">${esc(n.code)}</td>
      <td class="px-4 py-3 hidden lg:table-cell text-sm text-slate-600 capitalize">${n.location_type}</td>
      <td class="px-4 py-3 hidden md:table-cell text-sm text-slate-600">${esc(n.city||"\u2014")}</td>
      <td class="px-4 py-3 text-center text-sm font-medium text-slate-700">${n.employee_count||0}</td>
      <td class="px-4 py-3 text-right">
        ${t?`
        <div class="flex items-center justify-end gap-2">
          <button onclick="editLocation(${n.id})" class="text-slate-400 hover:text-slate-600 p-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
          </button>
          <button onclick="deleteLocation(${n.id})" class="text-slate-400 hover:text-red-600 p-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
        </div>`:""}
      </td>
    </tr>
  `).join("")}function openLocationModal(){editingLocationId=null,document.getElementById("locModalTitle").textContent="Add Location",document.getElementById("locModal").querySelector("form").reset(),document.getElementById("locFormErr").classList.add("hidden"),document.getElementById("locModal").classList.remove("hidden")}function editLocation(o){var a,n,i;const e=locations.find(c=>c.id===o);if(!e)return;editingLocationId=o,document.getElementById("locModalTitle").textContent=`Edit \u2014 ${e.name}`;const t=c=>document.getElementById(c);t("fLocName").value=e.name||"",t("fLocCode").value=e.code||"",t("fLocCity").value=e.city||"",t("fLocState").value=e.state||"",t("fLocType").value=e.location_type||"branch",t("fLocCapacity").value=e.capacity||"",t("fLocAddress").value=e.address||"",t("fLocPhone").value=e.phone||"",t("fLocLat").value=(a=e.latitude)!=null?a:"",t("fLocLng").value=(n=e.longitude)!=null?n:"",t("fLocRadius").value=(i=e.radius_meters)!=null?i:"",document.getElementById("locFormErr").classList.add("hidden"),document.getElementById("locModal").classList.remove("hidden")}function closeLocationModal(){document.getElementById("locModal").classList.add("hidden"),editingLocationId=null}async function submitLocationForm(o){o.preventDefault();const e=document.getElementById("locFormErr");e.classList.add("hidden");const t=c=>document.getElementById(c).value,a={name:t("fLocName").trim(),code:t("fLocCode").trim().toUpperCase(),city:t("fLocCity").trim()||null,state:t("fLocState").trim()||null,location_type:t("fLocType"),capacity:parseInt(t("fLocCapacity"))||null,address:t("fLocAddress").trim()||null,phone:t("fLocPhone").trim()||null,latitude:t("fLocLat").trim()?parseFloat(t("fLocLat")):null,longitude:t("fLocLng").trim()?parseFloat(t("fLocLng")):null,radius_meters:t("fLocRadius").trim()?parseInt(t("fLocRadius"),10):null},n=editingLocationId?`/api/locations/${editingLocationId}`:"/api/locations",i=await api(n,{method:editingLocationId?"PUT":"POST",body:JSON.stringify(a)});if(i){if(!i.ok){const c=await i.json();e.textContent=c.detail||"Failed to save location",e.classList.remove("hidden");return}closeLocationModal(),loadLocations()}}async function deleteLocation(o){const e=locations.find(a=>a.id===o);if(!e||!confirm(`Delete location "${e.name}"? This cannot be undone.`))return;const t=await api(`/api/locations/${o}`,{method:"DELETE"});if(!t||!t.ok){alert("Failed to delete location");return}loadLocations()}async function loadLocationDropdown(){const o=document.getElementById("fDefaultLocation");if(!o)return;const e=await api("/api/institutions/"+currentUser.institution_id+"/locations?is_active=1");if(!e||!e.ok)return;const a=(await e.json()).locations||[];for(;o.options.length>1;)o.remove(1);a.forEach(n=>{const i=document.createElement("option");i.value=n.id,i.textContent=`${n.name} (${n.code})`,o.appendChild(i)})}

//# sourceMappingURL=locations.js.map

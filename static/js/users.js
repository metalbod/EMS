// Users
// ---------------------------------------------------------------------------
async function loadUsers() {
  const res=await api('/api/users');
  if(!res||!res.ok) return;
  users=await res.json();
  renderUserTable();
}

function renderUserTable() {
  const tbody=document.getElementById('userTableBody');
  const empty=document.getElementById('userEmpty');
  if(!users.length){tbody.innerHTML='';empty.classList.remove('hidden');return;}
  empty.classList.add('hidden');
  const rc={superadmin:'bg-purple-100 text-purple-700',hr_manager:'bg-blue-100 text-blue-700',hr_admin:'bg-cyan-100 text-cyan-700',manager:'bg-amber-100 text-amber-700',payroll_manager:'bg-emerald-100 text-emerald-700',employee:'bg-slate-100 text-slate-600'};
  tbody.innerHTML=users.map(u=>`
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 bg-slate-100 rounded-full flex items-center justify-center text-slate-600 text-xs font-bold">${u.full_name.split(' ').slice(0,2).map(w=>w[0]||'').join('').toUpperCase()}</div>
          <div>
            <p class="font-medium">${esc(u.full_name)}</p>
            <p class="text-xs text-slate-400">@${esc(u.username)}${u.email?' · '+esc(u.email):''}</p>
          </div>
        </div>
      </td>
      <td class="px-4 py-3 hidden md:table-cell"><span class="badge ${rc[u.role]||''}">${meta.role_labels?.[u.role]||u.role}</span></td>
      <td class="px-4 py-3 hidden lg:table-cell text-xs text-slate-500">${esc(u.institution_name||u.institution_code||'Platform Admin')}</td>
      <td class="px-4 py-3"><span class="badge ${u.is_active?'bg-emerald-100 text-emerald-700':'bg-slate-100 text-slate-500'}">${u.is_active?'Active':'Inactive'}</span></td>
      <td class="px-4 py-3">
        <div class="flex justify-end gap-1">
          <button onclick="openUserModal(this.dataset.u)" data-u='${JSON.stringify(u).replace(/'/g,"&apos;")}' class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem">Edit</button>
          ${u.id!==currentUser.id?`<button onclick="deleteUser(${u.id})" class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem;color:#dc2626">Delete</button>`:''}
        </div>
      </td>
    </tr>`).join('');
}

function openUserModal(uData=null) {
  const u=typeof uData==='string'?JSON.parse(uData):uData;
  editingUserId=u?.id||null;
  document.getElementById('userModalTitle').textContent=u?'Edit User':'Add User';
  document.getElementById('editingUserId').value=u?.id||'';
  document.getElementById('uUsername').value=u?.username||'';
  document.getElementById('uUsername').disabled=!!u;
  document.getElementById('uFullName').value=u?.full_name||'';
  document.getElementById('uEmail').value=u?.email||'';
  document.getElementById('uPassword').value='';
  document.getElementById('uIsActive').checked=u?!!u.is_active:true;
  populateMetaSelects();
  // Set role checkboxes
  const userRoles=u?.roles||(u?.role?[u.role]:['employee']);
  document.querySelectorAll('.uRoleCheck').forEach(cb=>{cb.checked=userRoles.includes(cb.value);});
  syncRolePrimary();
  document.getElementById('uRole').value=u?.role||'employee';
  // Employee links
  const empSel=document.getElementById('uEmployeeId');
  empSel.innerHTML='<option value="">Not linked</option>';
  employees.forEach(e=>{const o=document.createElement('option');o.value=e.employee_id;o.textContent=`${e.employee_id} — ${e.full_name}`;empSel.appendChild(o);});
  empSel.value=u?.employee_id||'';
  // Institution picker (superadmin no context)
  const instWrap=document.getElementById('uInstWrap');
  if(currentUser.role==='superadmin'&&!currentInstitution){
    instWrap.classList.remove('hidden');
    const instSel=document.getElementById('uInstitution');
    instSel.innerHTML='<option value="">Platform Admin (no institution)</option>';
    institutions.forEach(i=>{const o=document.createElement('option');o.value=i.id;o.textContent=`${i.name} (${i.code})`;instSel.appendChild(o);});
    instSel.value=u?.institution_id||'';
  } else instWrap.classList.add('hidden');
  document.getElementById('userFormErr').classList.add('hidden');
  document.getElementById('userModal').classList.remove('hidden');
}

function closeUserModal() { document.getElementById('userModal').classList.add('hidden'); editingUserId=null; }

async function submitUserForm(e) {
  e.preventDefault();
  const err=document.getElementById('userFormErr');
  err.classList.add('hidden');
  const isEdit=!!editingUserId;
  const body={
    username:document.getElementById('uUsername').value.trim(),
    full_name:document.getElementById('uFullName').value.trim(),
    email:document.getElementById('uEmail').value.trim()||null,
    password:document.getElementById('uPassword').value||undefined,
    role:document.getElementById('uRole').value,
    roles:[...document.querySelectorAll('.uRoleCheck:checked')].map(c=>c.value),
    employee_id:document.getElementById('uEmployeeId').value||null,
    is_active:document.getElementById('uIsActive').checked,
  };
  if(!isEdit) delete body.is_active;
  if(currentUser.role==='superadmin'&&!currentInstitution){
    const v=document.getElementById('uInstitution').value;
    body.institution_id=v?parseInt(v):null;
  }
  const res=await api(isEdit?`/api/users/${editingUserId}`:'/api/users',
    {method:isEdit?'PUT':'POST',body:JSON.stringify(body)});
  if(!res) return;
  if(!res.ok){const d=await res.json();err.textContent=d.detail||'Failed';err.classList.remove('hidden');return;}
  closeUserModal(); loadUsers();
}

async function deleteUser(id) {
  if(!confirm('Delete this user?')) return;
  const res=await api(`/api/users/${id}`,{method:'DELETE'});
  if(res?.ok||res?.status===204) loadUsers();
}

// ---------------------------------------------------------------------------

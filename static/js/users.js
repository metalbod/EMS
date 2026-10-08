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
      <td class="px-4 py-3 hidden md:table-cell"><span class="badge ${statusColor(ROLE_BADGE_COLORS, u.role)}">${meta.role_labels?.[u.role]||u.role}</span></td>
      <td class="px-4 py-3 hidden lg:table-cell text-xs text-slate-500">${esc(u.institution_name||u.institution_code||'Platform Admin')}</td>
      <td class="px-4 py-3"><span class="badge ${u.is_active?'status-positive':'status-neutral'}">${u.is_active?'Active':'Inactive'}</span></td>
      <td class="px-4 py-3">
        <div class="flex justify-end gap-1">
          <button onclick="openUserModal(this.dataset.u)" data-u='${JSON.stringify(u).replace(/'/g,"&apos;")}' class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem">Edit</button>
          ${canViewActivityLog()?`<button onclick="openEntityHistory({title:'User history — '+this.dataset.name,entity_type:'user',entity_id:${u.id}})" data-name="${esc(u.username)}" class="btn-ghost" style="font-size:.75rem;padding:.25rem .5rem">History</button>`:''}
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
  // Add-user only: tick to have the server generate + email the password.
  // Email is mandatory when adding; on edit it stays optional so accounts
  // that never had one (older users, platform admins) can still be saved.
  document.getElementById('uSendPassword').checked=false;
  document.getElementById('uSendPasswordWrap').classList.toggle('hidden',!!u);
  document.getElementById('uEmail').required=!u;
  document.getElementById('uEmailStar').classList.toggle('hidden',!!u);
  onSendPasswordToggle();
  // Edit: a "Re-send password" button replaces the add-time checkbox.
  document.getElementById('uCcSender').checked=false;
  document.getElementById('uResendWrap').classList.toggle('hidden',!u);
  document.getElementById('uResendMsg').classList.add('hidden');
  const resendBtn=document.getElementById('uResendBtn');
  resendBtn.disabled=!(u&&u.email);
  document.getElementById('uResendHint').textContent=u&&u.email
    ?`Sets a new random password and emails it to ${u.email}. Their current password stops working.`
    :'This user has no email address. Add one and save first.';
  loadUserEmailOptions(!!u);
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
  employees.forEach(e=>{const o=document.createElement('option');o.value=e.employee_id;o.textContent=`${e.employee_id} — ${displayName(e.full_name,e.preferred_name)}`;empSel.appendChild(o);});
  empSel.value=u?.employee_id||'';
  initEmployeeSearchSelect('uEmployeeId', 'Search employee…');
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

let userEmailOptions=null;
// What the form can offer depends on the institution: can it send email at
// all, and which sender mailbox would the Cc box copy.
async function loadUserEmailOptions(isEdit) {
  const wrap=document.getElementById('uCcWrap');
  document.getElementById('uEmailNotReady').classList.add('hidden');
  const res=await api('/api/users/email-options');
  if(!res||!res.ok) return;
  userEmailOptions=await res.json();
  document.getElementById('uCcLabel').textContent=userEmailOptions.cc_address?`CC ${userEmailOptions.cc_address}`:'CC the HR mailbox';
  const ready=userEmailOptions.email_ready;
  document.getElementById('uEmailNotReady').classList.toggle('hidden',ready);
  document.getElementById('uSendPassword').disabled=!ready;
  if(!ready){ document.getElementById('uSendPassword').checked=false; onSendPasswordToggle(); document.getElementById('uResendBtn').disabled=true; }
  wrap.dataset.available=userEmailOptions.cc_address?'1':'';
  syncCcVisibility();
}
function syncCcVisibility() {
  const wrap=document.getElementById('uCcWrap');
  const show=wrap.dataset.available==='1'&&(editingUserId||document.getElementById('uSendPassword').checked);
  wrap.classList.toggle('hidden',!show);
  if(!show) document.getElementById('uCcSender').checked=false;
}

async function resendUserPassword() {
  const u=users.find(x=>x.id===editingUserId);
  if(!u) return;
  if(!confirm(`Generate a new random password for ${u.username} and email it to ${u.email}? Their current password will stop working.`)) return;
  const btn=document.getElementById('uResendBtn'), msg=document.getElementById('uResendMsg');
  btn.disabled=true; msg.classList.add('hidden');
  const res=await api(`/api/users/${editingUserId}/resend-password`,{method:'POST',body:JSON.stringify({cc_sender:document.getElementById('uCcSender').checked})});
  btn.disabled=false;
  if(!res) return;
  const d=await res.json().catch(()=>({}));
  msg.textContent=res.ok?`Sent to ${d.sent_to}. They'll be asked to change it at first sign-in.`:apiErrorText(d.detail);
  msg.className=`text-sm mt-1 ${res.ok?'text-emerald-600':'text-red-600'}`;
}

function onSendPasswordToggle() {
  const send=document.getElementById('uSendPassword').checked;
  const pw=document.getElementById('uPassword');
  if(send) pw.value='';
  pw.disabled=send;
  // Password is only required when adding a user and not asking the system to generate one.
  pw.required=!editingUserId&&!send;
  document.getElementById('uPasswordStar').classList.toggle('hidden',send||!!editingUserId);
  document.getElementById('uSendPasswordHint').classList.toggle('hidden',!send);
  syncCcVisibility();
}

function closeUserModal() { closeModal('userModal', () => editingUserId=null); }

async function submitUserForm(e) {
  e.preventDefault();
  const err=document.getElementById('userFormErr');
  err.classList.add('hidden');
  const isEdit=!!editingUserId;
  const sendPassword=!isEdit&&document.getElementById('uSendPassword').checked;
  const body={
    username:document.getElementById('uUsername').value.trim(),
    full_name:document.getElementById('uFullName').value.trim(),
    email:document.getElementById('uEmail').value.trim()||null,
    password:sendPassword?undefined:(document.getElementById('uPassword').value||undefined),
    send_password:sendPassword,
    cc_sender:sendPassword&&document.getElementById('uCcSender').checked,
    role:document.getElementById('uRole').value,
    roles:[...document.querySelectorAll('.uRoleCheck:checked')].map(c=>c.value),
    employee_id:document.getElementById('uEmployeeId').value||null,
    is_active:document.getElementById('uIsActive').checked,
  };
  if(!isEdit) delete body.is_active;
  else { delete body.send_password; delete body.cc_sender; }
  if(currentUser.role==='superadmin'&&!currentInstitution){
    const v=document.getElementById('uInstitution').value;
    body.institution_id=v?parseInt(v):null;
  }
  const res=await api(isEdit?`/api/users/${editingUserId}`:'/api/users',
    {method:isEdit?'PUT':'POST',body:JSON.stringify(body)});
  if(!res) return;
  if(!res.ok){const d=await res.json();err.textContent=apiErrorText(d.detail);err.classList.remove('hidden');return;}
  closeUserModal(); loadUsers();
}

async function deleteUser(id) {
  if(!confirm('Delete this user?')) return;
  const res=await api(`/api/users/${id}`,{method:'DELETE'});
  if(res?.ok||res?.status===204) loadUsers();
}

// ---------------------------------------------------------------------------

// Settings > Roles — 6 built-in roles (fixed) + this institution's custom
// roles (see routers/roles.py), usable as a user's role and as an
// onboarding/offboarding checklist item's assigned_role.
// ---------------------------------------------------------------------------
async function loadRolesPage() {
  await loadRolesCache();
  renderRolesTable();
}

function renderRolesTable() {
  const tbody = document.getElementById('rolesTableBody');
  if (!tbody) return;
  tbody.innerHTML = rolesCache.map(r => `
    <tr class="border-t border-slate-100">
      <td class="px-4 py-3 font-medium text-slate-800">${esc(r.display_name)}</td>
      <td class="px-4 py-3 text-slate-500 font-mono text-xs">${esc(r.role_key)}</td>
      <td class="px-4 py-3">
        <span class="badge text-xs ${r.is_builtin ? 'bg-slate-100 text-slate-500' : 'bg-blue-100 text-blue-700'}">${r.is_builtin ? 'Built-in' : 'Custom'}</span>
      </td>
      <td class="px-4 py-3 text-right">
        ${r.is_builtin ? '' : `<button onclick="deleteRole(${r.id})" class="text-slate-300 hover:text-red-500" title="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>`}
      </td>
    </tr>`).join('');
}

async function createRole() {
  const err = document.getElementById('roleFormErr');
  err.classList.add('hidden');
  const input = document.getElementById('roleNewName');
  const display_name = input.value.trim();
  if (!display_name) { err.textContent = 'Role name is required'; err.classList.remove('hidden'); return; }
  const res = await api('/api/roles', {method: 'POST', body: JSON.stringify({display_name})});
  if (!res?.ok) {
    const d = await res?.json().catch(()=>({}));
    err.textContent = d?.detail || 'Failed to add role';
    err.classList.remove('hidden');
    return;
  }
  input.value = '';
  await loadRolesCache();
  renderRolesTable();
}

async function deleteRole(roleId) {
  if (!confirm('Delete this role?')) return;
  const res = await api(`/api/roles/${roleId}`, {method: 'DELETE'});
  if (!res?.ok) {
    const d = await res?.json().catch(()=>({}));
    alert(d?.detail || 'Failed to delete role');
    return;
  }
  await loadRolesCache();
  renderRolesTable();
}

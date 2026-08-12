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

// ---------------------------------------------------------------------------
// Permission Matrix tab — GET /api/roles/permission-matrix's static,
// hand-curated data (see core/permission_matrix.py). Fetched once and
// cached; the matrix doesn't change per-institution or over a session.
// ---------------------------------------------------------------------------
let permissionMatrixData = null;
let matrixExpanded = new Set();

function switchRolesTab(tab) {
  document.getElementById('rolesTab_roles').classList.toggle('view-tab-active', tab === 'roles');
  document.getElementById('rolesTab_roles').classList.toggle('text-slate-500', tab !== 'roles');
  document.getElementById('rolesTab_matrix').classList.toggle('view-tab-active', tab === 'matrix');
  document.getElementById('rolesTab_matrix').classList.toggle('text-slate-500', tab !== 'matrix');
  document.getElementById('rolesTabPanel_roles').classList.toggle('hidden', tab !== 'roles');
  document.getElementById('rolesTabPanel_matrix').classList.toggle('hidden', tab !== 'matrix');
  if (tab === 'matrix' && !permissionMatrixData) loadPermissionMatrix();
}

async function loadPermissionMatrix() {
  const res = await api('/api/roles/permission-matrix');
  if (!res?.ok) return;
  permissionMatrixData = await res.json();
  renderPermissionMatrix();
}

function matrixToggleModule(name) {
  if (matrixExpanded.has(name)) matrixExpanded.delete(name); else matrixExpanded.add(name);
  renderPermissionMatrix();
}

async function matrixSetOverride(actionKey, role, accessValue) {
  const res = await api('/api/roles/permission-matrix/override', {
    method: 'PUT',
    body: JSON.stringify({action_key: actionKey, role, access_value: accessValue}),
  });
  if (!res?.ok) {
    const d = await res?.json().catch(() => ({}));
    alert(d?.detail || 'Failed to update permission');
    return;
  }
  await loadPermissionMatrix();
}

async function matrixResetOverride(actionKey, role) {
  const res = await api(`/api/roles/permission-matrix/override?action_key=${encodeURIComponent(actionKey)}&role=${encodeURIComponent(role)}`, {
    method: 'DELETE',
  });
  if (!res?.ok) {
    const d = await res?.json().catch(() => ({}));
    alert(d?.detail || 'Failed to reset permission');
    return;
  }
  await loadPermissionMatrix();
}

const MATRIX_CELL_STYLE = {
  allow: {cls: 'bg-emerald-100 text-emerald-700', label: 'Allowed'},
  deny: {cls: 'bg-slate-100 text-slate-400', label: 'Denied'},
  own: {cls: 'bg-blue-100 text-blue-700', label: 'Own record'},
  subordinate: {cls: 'bg-purple-100 text-purple-700', label: 'Subordinates'},
  configurable: {cls: 'bg-amber-100 text-amber-700', label: 'Configurable'},
  no_restriction: {cls: 'bg-indigo-100 text-indigo-700', label: 'No restriction'},
};

function renderPermissionMatrix() {
  const wrap = document.getElementById('matrixWrap');
  if (!wrap || !permissionMatrixData) return;
  const q = (document.getElementById('matrixSearch')?.value || '').trim().toLowerCase();
  // Built-in roles, then this institution's actual custom roles (e.g. "IT
  // Infra") as their own columns — each one mirrors the Employee column
  // (see routers/roles.py's get_permission_matrix), since a custom role
  // never unlocks a manage permission.
  const roles = [...permissionMatrixData.roles, ...(permissionMatrixData.custom_roles || [])];
  const labels = permissionMatrixData.role_labels;

  const modulesHtml = permissionMatrixData.modules.map(mod => {
    const actions = q
      ? mod.actions.filter(a => a.action.toLowerCase().includes(q) || mod.module.toLowerCase().includes(q))
      : mod.actions;
    if (!actions.length) return '';
    const expanded = q ? true : matrixExpanded.has(mod.module);
    const rows = actions.map(a => `
      <tr class="border-t border-slate-100">
        <td class="px-4 py-2.5 align-top">
          <div class="text-sm font-medium text-slate-800">${esc(a.action)}</div>
          <div class="text-[11px] text-slate-400 font-mono">${esc(a.path)}</div>
          ${a.note ? `<div class="text-[11px] text-slate-500 mt-1">${esc(a.note)}</div>` : ''}
        </td>
        ${roles.map(r => {
          const status = a.access[r] || 'deny';
          const style = MATRIX_CELL_STYLE[status] || MATRIX_CELL_STYLE.deny;
          const isEditable = !!(a.editable && a.editable[r]);
          const isOverridden = isEditable && a.access_default && a.access_default[r] !== status;
          if (!isEditable) {
            return `<td class="px-2 py-2.5 text-center align-top">
              <span class="inline-block text-[10px] font-semibold px-2 py-1 rounded ${style.cls}" title="${esc(labels[r] || r)}: ${style.label}">${style.label}</span>
            </td>`;
          }
          const nextVal = status === 'allow' ? 'deny' : 'allow';
          return `<td class="px-2 py-2.5 text-center align-top">
            <button onclick="matrixSetOverride('${esc(a.key)}','${esc(r)}','${nextVal}')"
                    class="inline-block text-[10px] font-semibold px-2 py-1 rounded ${style.cls} ring-2 ring-offset-1 ${isOverridden ? 'ring-slate-400' : 'ring-transparent'} hover:ring-slate-300 cursor-pointer"
                    title="${esc(labels[r] || r)}: ${style.label} — click to set ${nextVal === 'allow' ? 'Allowed' : 'Denied'}${isOverridden ? ' (customized for this institution)' : ''}">
              ${style.label}
            </button>
            ${isOverridden ? `<button onclick="matrixResetOverride('${esc(a.key)}','${esc(r)}')" class="block mx-auto mt-0.5 text-[9px] text-slate-400 hover:text-slate-600 underline" title="Reset to default">reset</button>` : ''}
          </td>`;
        }).join('')}
      </tr>`).join('');
    return `
      <div class="border-t border-slate-200 first:border-t-0">
        <button onclick="matrixToggleModule('${esc(mod.module)}')" class="w-full flex items-center gap-2 px-4 py-2.5 bg-slate-50 hover:bg-slate-100 text-left">
          <svg class="w-3.5 h-3.5 text-slate-400 transition-transform flex-shrink-0 ${expanded ? 'rotate-90' : ''}" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.21 5.23a.75.75 0 011.06.02l4.5 4.75a.75.75 0 010 1.04l-4.5 4.75a.75.75 0 11-1.08-1.04L11.168 10 7.23 5.79a.75.75 0 01-.02-1.06z" clip-rule="evenodd"/></svg>
          <span class="text-sm font-semibold text-slate-700">${esc(mod.module)}</span>
          <span class="text-xs text-slate-400">${actions.length} action${actions.length !== 1 ? 's' : ''}</span>
        </button>
        ${expanded ? `<div class="overflow-x-auto"><table class="w-full text-sm">
          <thead><tr class="bg-white text-[10px] uppercase text-slate-400">
            <th class="px-4 py-2 text-left font-medium">Action</th>
            ${roles.map(r => `<th class="px-2 py-2 text-center font-medium whitespace-nowrap">${esc(labels[r] || r)}</th>`).join('')}
          </tr></thead>
          <tbody>${rows}</tbody>
        </table></div>` : ''}
      </div>`;
  }).join('');

  wrap.innerHTML = modulesHtml || '<p class="text-sm text-slate-400 p-4">No actions match your search.</p>';
}

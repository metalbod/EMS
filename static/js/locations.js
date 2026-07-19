// Locations Management
// ---------------------------------------------------------------------------

let locations = [];
let editingLocationId = null;

async function loadLocations() {
  const res = await api('/api/institutions/' + currentUser.institution_id + '/locations');
  if (!res || !res.ok) return;
  const data = await res.json();
  locations = data.locations || [];
  renderLocationsTable();
}

function renderLocationsTable() {
  const tbody = document.getElementById('locTableBody');
  const empty = document.getElementById('locEmpty');

  if (!locations.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }

  empty.classList.add('hidden');
  tbody.innerHTML = locations.map(loc => `
    <tr class="hover:bg-slate-50 transition">
      <td class="px-4 py-3">
        <div>
          <p class="font-medium text-slate-800">${esc(loc.name)}</p>
          <p class="text-xs text-slate-400">${loc.location_type === 'hq' ? '⭐ HQ' : loc.location_type}</p>
        </div>
      </td>
      <td class="px-4 py-3 hidden md:table-cell text-sm text-slate-600 font-mono">${esc(loc.code)}</td>
      <td class="px-4 py-3 hidden lg:table-cell text-sm text-slate-600 capitalize">${loc.location_type}</td>
      <td class="px-4 py-3 hidden md:table-cell text-sm text-slate-600">${esc(loc.city || '—')}</td>
      <td class="px-4 py-3 text-center text-sm font-medium text-slate-700">${loc.employee_count || 0}</td>
      <td class="px-4 py-3 text-right">
        <div class="flex items-center justify-end gap-2">
          <button onclick="editLocation(${loc.id})" class="text-slate-400 hover:text-slate-600 p-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
          </button>
          <button onclick="deleteLocation(${loc.id})" class="text-slate-400 hover:text-red-600 p-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
        </div>
      </td>
    </tr>
  `).join('');
}

function openLocationModal() {
  editingLocationId = null;
  document.getElementById('locModalTitle').textContent = 'Add Location';
  document.getElementById('locModal').querySelector('form').reset();
  document.getElementById('locFormErr').classList.add('hidden');
  document.getElementById('locModal').classList.remove('hidden');
}

function editLocation(locId) {
  const loc = locations.find(l => l.id === locId);
  if (!loc) return;

  editingLocationId = locId;
  document.getElementById('locModalTitle').textContent = `Edit — ${loc.name}`;

  const f = id => document.getElementById(id);
  f('fLocName').value = loc.name || '';
  f('fLocCode').value = loc.code || '';
  f('fLocCity').value = loc.city || '';
  f('fLocState').value = loc.state || '';
  f('fLocType').value = loc.location_type || 'branch';
  f('fLocCapacity').value = loc.capacity || '';
  f('fLocAddress').value = loc.address || '';
  f('fLocPhone').value = loc.phone || '';

  document.getElementById('locFormErr').classList.add('hidden');
  document.getElementById('locModal').classList.remove('hidden');
}

function closeLocationModal() {
  document.getElementById('locModal').classList.add('hidden');
  editingLocationId = null;
}

async function submitLocationForm(e) {
  e.preventDefault();

  const err = document.getElementById('locFormErr');
  err.classList.add('hidden');

  const g = id => document.getElementById(id).value;

  const body = {
    name: g('fLocName').trim(),
    code: g('fLocCode').trim().toUpperCase(),
    city: g('fLocCity').trim() || null,
    state: g('fLocState').trim() || null,
    location_type: g('fLocType'),
    capacity: parseInt(g('fLocCapacity')) || null,
    address: g('fLocAddress').trim() || null,
    phone: g('fLocPhone').trim() || null,
  };

  const url = editingLocationId
    ? `/api/locations/${editingLocationId}`
    : '/api/locations';

  const res = await api(url, {
    method: editingLocationId ? 'PUT' : 'POST',
    body: JSON.stringify(body)
  });

  if (!res) return;

  if (!res.ok) {
    const d = await res.json();
    err.textContent = d.detail || 'Failed to save location';
    err.classList.remove('hidden');
    return;
  }

  closeLocationModal();
  loadLocations();
}

async function deleteLocation(locId) {
  const loc = locations.find(l => l.id === locId);
  if (!loc) return;

  if (!confirm(`Delete location "${loc.name}"? This cannot be undone.`)) return;

  const res = await api(`/api/locations/${locId}`, { method: 'DELETE' });

  if (!res || !res.ok) {
    alert('Failed to delete location');
    return;
  }

  loadLocations();
}

// Load locations dropdown for employee forms
async function loadLocationDropdown() {
  const select = document.getElementById('fDefaultLocation');
  if (!select) return;

  const res = await api('/api/institutions/' + currentUser.institution_id + '/locations?is_active=1');
  if (!res || !res.ok) return;

  const data = await res.json();
  const locs = data.locations || [];

  // Clear and rebuild
  while (select.options.length > 1) select.remove(1);

  locs.forEach(loc => {
    const opt = document.createElement('option');
    opt.value = loc.id;
    opt.textContent = `${loc.name} (${loc.code})`;
    select.appendChild(opt);
  });
}

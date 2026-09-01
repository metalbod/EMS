// Attendance: Clock In/Out, HR Review, Shifts + Rules + Assignments settings
// ---------------------------------------------------------------------------
let attHistoryCache = [];
let attReviewCache = [];
let attShiftsCache = [];
let attCurrentGeo = null; // {lat, lng} captured once per page load

const ATT_STATUS_COLORS = {
  'Present': 'status-positive',
  'Late': 'status-pending',
  'Absent (Pending Review)': 'status-negative',
  'Excused': 'status-info',
  'Reclassified as Leave': 'status-special',
  'Confirmed Absent': 'status-neutral',
};

function attStatusBadge(status) {
  const cls = statusColor(ATT_STATUS_COLORS, status);
  return `<span class="px-2 py-0.5 rounded-sm text-xs font-medium ${cls}">${esc(status)}</span>`;
}

function attCaptureGeo() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => resolve(null),
      { timeout: 5000 }
    );
  });
}

// ---------------------------------------------------------------------------
// Clock In / Out (self-service)
// ---------------------------------------------------------------------------
async function loadAttendanceClockPage() {
  document.getElementById('attClockGeoNote').textContent = 'Requesting location for geofence check…';
  attCurrentGeo = await attCaptureGeo();
  document.getElementById('attClockGeoNote').textContent = attCurrentGeo
    ? 'Location captured.' : 'Location unavailable — clock-in will still work, just without a geofence check.';

  const res = await api('/api/attendance/mine?limit=30');
  if (!res || !res.ok) return;
  attHistoryCache = await res.json();
  renderAttClockStatus();
  renderAttHistory();
}

function renderAttClockStatus() {
  const open = attHistoryCache.find(r => r.clock_in_at && !r.clock_out_at);
  const inBtn = document.getElementById('attClockInBtn');
  const outBtn = document.getElementById('attClockOutBtn');
  const statusEl = document.getElementById('attClockStatus');
  const detailEl = document.getElementById('attClockDetail');

  if (open) {
    statusEl.textContent = 'Clocked In';
    detailEl.textContent = `Since ${fmtDateTime(open.clock_in_at)} (${esc(open.shift_name || 'no shift')})`;
    inBtn.classList.add('hidden');
    outBtn.classList.remove('hidden');
  } else {
    const today = attHistoryCache.find(r => r.work_date === new Date().toISOString().slice(0, 10));
    if (today && today.clock_out_at) {
      statusEl.textContent = 'Clocked Out';
      detailEl.textContent = `Worked ${today.worked_minutes ?? '—'} min today`;
    } else {
      statusEl.textContent = 'Not Clocked In';
      detailEl.textContent = '';
    }
    inBtn.classList.remove('hidden');
    outBtn.classList.add('hidden');
  }
}

function renderAttHistory() {
  const el = document.getElementById('attHistoryList');
  document.getElementById('attHistoryEmpty')?.classList.toggle('hidden', attHistoryCache.length > 0);
  el.innerHTML = attHistoryCache.map(r => `
    <tr class="border-t border-slate-100">
      <td class="px-4 py-2 text-sm">${fmtDate(r.work_date)}</td>
      <td class="px-4 py-2 text-sm text-slate-500">${esc(r.shift_name || '—')}</td>
      <td class="px-4 py-2 text-sm">${r.clock_in_at ? parseUTC(r.clock_in_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '—'}</td>
      <td class="px-4 py-2 text-sm">${r.clock_out_at ? parseUTC(r.clock_out_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '—'}</td>
      <td class="px-4 py-2 text-sm text-right">${r.worked_minutes != null ? r.worked_minutes + ' min' : '—'}</td>
      <td class="px-4 py-2">${attStatusBadge(r.status)}${r.outside_geofence ? ' <span class="text-xs text-amber-600">(outside geofence)</span>' : ''}</td>
    </tr>`).join('');
}

async function attendanceClockIn() {
  const res = await api('/api/attendance/clock-in', {
    method: 'POST',
    body: JSON.stringify({ lat: attCurrentGeo?.lat ?? null, lng: attCurrentGeo?.lng ?? null }),
  });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  loadAttendanceClockPage();
}

async function attendanceClockOut() {
  const res = await api('/api/attendance/clock-out', {
    method: 'POST',
    body: JSON.stringify({ lat: attCurrentGeo?.lat ?? null, lng: attCurrentGeo?.lng ?? null }),
  });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  loadAttendanceClockPage();
}

// ---------------------------------------------------------------------------
// HR Review
// ---------------------------------------------------------------------------
async function loadAttendanceReview() {
  const res = await api('/api/attendance/review');
  if (!res || !res.ok) return;
  attReviewCache = await res.json();
  const el = document.getElementById('attReviewList');
  document.getElementById('attReviewEmpty')?.classList.toggle('hidden', attReviewCache.length > 0);
  el.innerHTML = attReviewCache.map(r => `
    <tr class="border-t border-slate-100">
      <td class="px-4 py-2 text-sm">
        <div class="font-medium">${esc(r.employee_name ? displayName(r.employee_name, r.employee_preferred_name) : r.employee_id)}</div>
        <div class="text-xs text-slate-400">${esc(r.department || '')}</div>
      </td>
      <td class="px-4 py-2 text-sm">${fmtDate(r.work_date)}</td>
      <td class="px-4 py-2">${attStatusBadge(r.status)}</td>
      <td class="px-4 py-2 text-sm text-slate-500">${esc(r.suggested_action || '—')}</td>
      <td class="px-4 py-2 text-right"><button onclick="openAttResolveModal(${r.id})" class="text-xs text-blue-600 hover:underline">Resolve</button></td>
    </tr>`).join('');
}

let currentAttResolveId = null;

async function openAttResolveModal(id) {
  const rec = attReviewCache.find(r => r.id === id);
  if (!rec) return;
  currentAttResolveId = id;
  document.getElementById('attResolveInfo').textContent =
    `${rec.employee_name ? displayName(rec.employee_name, rec.employee_preferred_name) : rec.employee_id} — ${fmtDate(rec.work_date)} — currently ${rec.status}${rec.suggested_action ? ' (suggested: ' + rec.suggested_action + ')' : ''}`;
  document.getElementById('attResolveAction').value = rec.suggested_action === 'Half-Day Leave' ? 'ReclassifyAsLeave' : (rec.status === 'Late' ? 'Excuse' : 'ReclassifyAsLeave');
  document.getElementById('attResolveHalfDay').checked = rec.suggested_action === 'Half-Day Leave';
  document.getElementById('attResolveNotes').value = '';

  const ltRes = await api('/api/leave/types');
  const leaveTypes = ltRes && ltRes.ok ? await ltRes.json() : [];
  document.getElementById('attResolveLeaveType').innerHTML =
    '<option value="">— Select —</option>' + leaveTypes.map(lt => `<option value="${lt.id}">${esc(lt.name)}</option>`).join('');

  toggleAttResolveLeaveFields();
  document.getElementById('attResolveModal').classList.remove('hidden');
}

function closeAttResolveModal() {
  document.getElementById('attResolveModal').classList.add('hidden');
  currentAttResolveId = null;
}

function toggleAttResolveLeaveFields() {
  const isLeave = document.getElementById('attResolveAction').value === 'ReclassifyAsLeave';
  document.getElementById('attResolveLeaveWrap').classList.toggle('hidden', !isLeave);
}

async function submitAttResolveForm(e) {
  e.preventDefault();
  const action = document.getElementById('attResolveAction').value;
  const body = {
    action,
    notes: document.getElementById('attResolveNotes').value || null,
  };
  if (action === 'ReclassifyAsLeave') {
    body.leave_type_id = parseInt(document.getElementById('attResolveLeaveType').value, 10) || null;
    body.half_day = document.getElementById('attResolveHalfDay').checked;
    if (!body.leave_type_id) { alert('Select a leave type'); return; }
  }
  const res = await api(`/api/attendance/records/${currentAttResolveId}/resolve`, { method: 'PUT', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeAttResolveModal();
  loadAttendanceReview();
}

// ---------------------------------------------------------------------------
// Settings: Rules / Shifts / Assignments
// ---------------------------------------------------------------------------
function setAttSettingsTab(tab) {
  document.querySelectorAll('.att-tab-btn').forEach(b => b.classList.toggle('att-tab-active', b.dataset.tab === tab));
  document.querySelectorAll('.att-tab-panel').forEach(p => p.classList.toggle('hidden', p.id !== `attTab-${tab}`));
  if (tab === 'rules') loadAttRules();
  if (tab === 'shifts') loadAttShifts();
  if (tab === 'assignments') loadAttAssignments();
  if (tab === 'devices') loadAttDevices();
}

async function loadAttendanceSettingsPage() {
  setAttSettingsTab('rules');
}

async function _loadShiftsIntoSelects() {
  const res = await api('/api/attendance/shifts');
  attShiftsCache = res && res.ok ? await res.json() : [];
  const opts = '<option value="">— None —</option>' + attShiftsCache.filter(s => s.is_active).map(s => `<option value="${s.id}">${esc(s.name)} (${s.start_time}–${s.end_time})</option>`).join('');
  const ruleSel = document.getElementById('attRuleShift');
  if (ruleSel) ruleSel.innerHTML = opts;
  const assignSel = document.getElementById('assignShift');
  if (assignSel) assignSel.innerHTML = opts.replace('— None —', '— Select —');
}

// --- Rules ---
async function loadAttRules() {
  await _loadShiftsIntoSelects();
  const res = await api('/api/attendance/settings');
  if (!res || !res.ok) return;
  const rows = await res.json();
  const el = document.getElementById('attRulesList');
  document.getElementById('attRulesEmpty')?.classList.toggle('hidden', rows.length > 0);
  el.innerHTML = rows.map(r => `
    <tr class="border-t border-slate-100">
      <td class="px-4 py-2 text-sm">${r.employee_id ? 'Employee: ' + esc(r.employee_id) : 'Department: ' + esc(r.department)}</td>
      <td class="px-4 py-2 text-sm">${r.required ? 'Yes' : 'No'}</td>
      <td class="px-4 py-2 text-sm text-slate-500">${esc(r.default_shift_name || '—')}</td>
      <td class="px-4 py-2 text-right"><button onclick="deleteAttRule(${r.id})" class="text-xs text-red-600 hover:underline">Remove</button></td>
    </tr>`).join('');
}

function openAttRuleModal() {
  document.getElementById('attRuleForm').reset();

  const depts = [...new Set((employees || []).map(e => e.department).filter(Boolean))].sort();
  document.getElementById('attRuleDept').innerHTML =
    '<option value="">— Select —</option>' + depts.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('');

  const activeEmps = (employees || []).filter(e => e.status === 'Active').sort((a, b) => a.full_name.localeCompare(b.full_name));
  document.getElementById('attRuleEmp').innerHTML =
    '<option value="">— Select —</option>' + activeEmps.map(e => `<option value="${esc(e.employee_id)}">${esc(displayName(e.full_name,e.preferred_name))} (${esc(e.employee_id)})</option>`).join('');

  toggleAttRuleScopeInput();
  document.getElementById('attRuleModal').classList.remove('hidden');
}
function closeAttRuleModal() { closeModal('attRuleModal'); }
function toggleAttRuleScopeInput() {
  const isEmp = document.getElementById('attRuleScopeType').value === 'employee';
  document.getElementById('attRuleDeptWrap').classList.toggle('hidden', isEmp);
  document.getElementById('attRuleEmpWrap').classList.toggle('hidden', !isEmp);
}

async function submitAttRuleForm(e) {
  e.preventDefault();
  const isEmp = document.getElementById('attRuleScopeType').value === 'employee';
  const body = {
    department: isEmp ? null : (document.getElementById('attRuleDept').value || null),
    employee_id: isEmp ? (document.getElementById('attRuleEmp').value || null) : null,
    required: document.getElementById('attRuleRequired').checked,
    default_shift_id: parseInt(document.getElementById('attRuleShift').value, 10) || null,
  };
  const res = await api('/api/attendance/settings', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeAttRuleModal();
  loadAttRules();
}

async function deleteAttRule(id) {
  if (!confirm('Remove this attendance rule?')) return;
  const res = await api(`/api/attendance/settings/${id}`, { method: 'DELETE' });
  if (!res || !res.ok) { alert('Error removing rule'); return; }
  loadAttRules();
}

// --- Shifts ---
async function loadAttShifts() {
  const res = await api('/api/attendance/shifts');
  if (!res || !res.ok) return;
  attShiftsCache = await res.json();
  const el = document.getElementById('attShiftsList');
  document.getElementById('attShiftsEmpty')?.classList.toggle('hidden', attShiftsCache.length > 0);
  el.innerHTML = attShiftsCache.map(s => `
    <tr class="border-t border-slate-100">
      <td class="px-4 py-2 text-sm">${esc(s.name)}</td>
      <td class="px-4 py-2 text-sm">${s.start_time}</td>
      <td class="px-4 py-2 text-sm">${s.end_time}</td>
      <td class="px-4 py-2 text-sm">${s.crosses_midnight ? 'Yes' : 'No'}</td>
      <td class="px-4 py-2 text-sm text-right">${s.grace_period_minutes}</td>
      <td class="px-4 py-2 text-right"><button onclick="deleteShift(${s.id})" class="text-xs text-red-600 hover:underline">Deactivate</button></td>
    </tr>`).join('');
}

function openShiftModal() {
  document.getElementById('shiftForm').reset();
  document.getElementById('shiftId').value = '';
  document.getElementById('shiftModalTitle').textContent = 'Add Shift';
  document.getElementById('shiftModal').classList.remove('hidden');
}
function closeShiftModal() { closeModal('shiftModal'); }

async function submitShiftForm(e) {
  e.preventDefault();
  const body = {
    name: document.getElementById('shiftName').value,
    start_time: document.getElementById('shiftStart').value,
    end_time: document.getElementById('shiftEnd').value,
    grace_period_minutes: parseInt(document.getElementById('shiftGrace').value, 10) || 0,
  };
  const res = await api('/api/attendance/shifts', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeShiftModal();
  loadAttShifts();
}

async function deleteShift(id) {
  if (!confirm('Deactivate this shift?')) return;
  const res = await api(`/api/attendance/shifts/${id}`, { method: 'DELETE' });
  if (!res || !res.ok) { alert('Error deactivating shift'); return; }
  loadAttShifts();
}

// --- Assignments ---
async function loadAttAssignments() {
  await _loadShiftsIntoSelects();
  const res = await api('/api/attendance/shift-assignments');
  if (!res || !res.ok) return;
  const rows = await res.json();
  const el = document.getElementById('attAssignmentsList');
  document.getElementById('attAssignmentsEmpty')?.classList.toggle('hidden', rows.length > 0);
  el.innerHTML = rows.map(a => `
    <tr class="border-t border-slate-100">
      <td class="px-4 py-2 text-sm">${esc(a.employee_id)}</td>
      <td class="px-4 py-2 text-sm">${esc(a.shift_name || '')}</td>
      <td class="px-4 py-2 text-sm">${esc(a.effective_from)}</td>
      <td class="px-4 py-2 text-sm">${esc(a.effective_to || 'ongoing')}</td>
      <td class="px-4 py-2 text-right"><button onclick="deleteAssignment(${a.id})" class="text-xs text-red-600 hover:underline">Remove</button></td>
    </tr>`).join('');
}

function openAssignmentModal() {
  document.getElementById('assignmentForm').reset();
  const activeEmps = (employees || []).filter(e => e.status === 'Active').sort((a, b) => a.full_name.localeCompare(b.full_name));
  document.getElementById('assignEmp').innerHTML =
    '<option value="">— Select —</option>' + activeEmps.map(e => `<option value="${esc(e.employee_id)}">${esc(displayName(e.full_name,e.preferred_name))} (${esc(e.employee_id)})</option>`).join('');
  document.getElementById('assignmentModal').classList.remove('hidden');
}
function closeAssignmentModal() { closeModal('assignmentModal'); }

async function submitAssignmentForm(e) {
  e.preventDefault();
  const body = {
    employee_id: document.getElementById('assignEmp').value,
    shift_id: parseInt(document.getElementById('assignShift').value, 10),
    effective_from: document.getElementById('assignFrom').value,
    effective_to: document.getElementById('assignTo').value || null,
  };
  const res = await api('/api/attendance/shift-assignments', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  closeAssignmentModal();
  loadAttAssignments();
}

async function deleteAssignment(id) {
  if (!confirm('Remove this shift assignment?')) return;
  const res = await api(`/api/attendance/shift-assignments/${id}`, { method: 'DELETE' });
  if (!res || !res.ok) { alert('Error removing assignment'); return; }
  loadAttAssignments();
}

// --- Devices (external clock-in/out integrations) ---
async function loadAttDevices() {
  const res = await api('/api/attendance/devices');
  if (!res || !res.ok) return;
  const rows = await res.json();
  const el = document.getElementById('attDevicesList');
  document.getElementById('attDevicesEmpty')?.classList.toggle('hidden', rows.length > 0);
  el.innerHTML = rows.map(d => `
    <tr class="border-t border-slate-100">
      <td class="px-4 py-2 text-sm">${esc(d.name)}</td>
      <td class="px-4 py-2 text-sm text-slate-500">${esc(d.location_name || '—')}</td>
      <td class="px-4 py-2 text-sm font-mono text-xs">adk_${esc(d.key_prefix)}_…</td>
      <td class="px-4 py-2 text-sm text-slate-500">${d.last_used_at ? fmtDateTime(d.last_used_at) : 'Never'}</td>
      <td class="px-4 py-2 text-right"><button onclick="deleteDevice(${d.id})" class="text-xs text-red-600 hover:underline">Revoke</button></td>
    </tr>`).join('');
}

async function openDeviceModal() {
  document.getElementById('deviceForm').reset();
  document.getElementById('deviceForm').classList.remove('hidden');
  document.getElementById('deviceKeyReveal').classList.add('hidden');

  const res = await api(`/api/institutions/${currentUser.institution_id}/locations?is_active=1`);
  const data = res && res.ok ? await res.json() : { locations: [] };
  document.getElementById('deviceLocation').innerHTML =
    '<option value="">— None —</option>' + (data.locations || []).map(l => `<option value="${l.id}">${esc(l.name)} (${esc(l.code)})</option>`).join('');

  document.getElementById('deviceModal').classList.remove('hidden');
}

function closeDeviceModal() {
  document.getElementById('deviceModal').classList.add('hidden');
  loadAttDevices();
}

async function submitDeviceForm(e) {
  e.preventDefault();
  const body = {
    name: document.getElementById('deviceName').value,
    location_id: parseInt(document.getElementById('deviceLocation').value, 10) || null,
  };
  const res = await api('/api/attendance/devices', { method: 'POST', body: JSON.stringify(body) });
  if (!res || !res.ok) { alert('Error: ' + (await res.json()).detail); return; }
  const device = await res.json();
  document.getElementById('deviceForm').classList.add('hidden');
  document.getElementById('deviceKeyReveal').classList.remove('hidden');
  document.getElementById('deviceKeyValue').value = device.api_key;
}

function copyDeviceKey() {
  const input = document.getElementById('deviceKeyValue');
  input.select();
  navigator.clipboard?.writeText(input.value);
}

async function deleteDevice(id) {
  if (!confirm('Revoke this device? Any camera/hardware using its API key will stop working immediately.')) return;
  const res = await api(`/api/attendance/devices/${id}`, { method: 'DELETE' });
  if (!res || !res.ok) { alert('Error revoking device'); return; }
  loadAttDevices();
}

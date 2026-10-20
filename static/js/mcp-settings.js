// Settings — Claude access (HR Manager only). See routers/oauth.py. Switches the company's Claude/MCP connections on or off and
// lists who has connected, with a Disconnect button per person.

function mcpSetMsg(text, ok) {
  const el = document.getElementById('mcpMsg');
  if (!el) return;
  el.textContent = text || '';
  el.className = `text-xs mt-2 ${ok === false ? 'text-red-600' : ok ? 'text-green-600' : 'text-slate-500'}`;
}

function mcpScopeLabel(scope) {
  const names = { 'attendance:clock': 'clock in/out', 'attendance:read': 'attendance', 'leave:read': 'leave balance', 'timesheet:read': 'see timesheet hours, projects and their teams', 'timesheet:write': 'log hours (draft)', 'leave:colleagues': 'see who is on leave', 'holidays:read': 'see public holidays' };
  return String(scope || '').split(' ').filter(Boolean).map(s => names[s] || s).join(', ');
}

function renderMcpSettings(s) {
  document.getElementById('mcpEnabledToggle').checked = !!s.enabled;
  document.getElementById('mcpEnabledLabel').textContent = s.enabled ? 'On' : 'Off';
  document.getElementById('mcpUrl').value = s.mcp_url || '';
  const el = document.getElementById('mcpConnections');
  if (!s.connections.length) {
    el.innerHTML = '<p class="text-sm text-slate-400">Nobody has connected Claude yet.</p>';
    return;
  }
  el.innerHTML = `<table class="w-full text-sm"><thead><tr class="text-left text-xs text-slate-500">
    <th class="py-1 pr-3">Person</th><th class="py-1 pr-3">App</th><th class="py-1 pr-3">Can</th><th class="py-1 pr-3">Last used</th><th class="py-1 pr-3">Reconnect by</th><th></th></tr></thead><tbody>`
    + s.connections.map(c => `<tr class="border-t border-slate-100">
      <td class="py-2 pr-3">${esc(c.person || c.username || '—')}</td>
      <td class="py-2 pr-3">${esc(c.app || '—')}</td>
      <td class="py-2 pr-3 text-slate-500">${esc(mcpScopeLabel(c.scope))}</td>
      <td class="py-2 pr-3 text-slate-500">${c.last_used_at ? esc(fmtDateTime(c.last_used_at)) : '—'}</td>
      <td class="py-2 pr-3 text-slate-500">${c.reconnect_by ? esc(fmtDate(c.reconnect_by)) : '—'}</td>
      <td class="py-2 text-right"><button class="btn-ghost text-xs" onclick="disconnectMcp(${Number(c.id)})">Disconnect</button></td></tr>`).join('')
    + '</tbody></table>';
}

async function loadMcpSettingsPage() {
  mcpSetMsg('', null);
  const res = await api('/api/settings/mcp');
  if (!res?.ok) { mcpSetMsg('Only an HR Manager can open these settings.', false); return; }
  renderMcpSettings(await res.json());
}

async function toggleMcpEnabled(on) {
  const box = document.getElementById('mcpEnabledToggle');
  if (!on && !confirm('Turn off Claude access? Everyone who has connected Claude stops working at once.')) { box.checked = true; return; }
  const res = await api('/api/settings/mcp/enabled', { method: 'PUT', body: JSON.stringify({ enabled: on }) });
  if (!res?.ok) { box.checked = !on; mcpSetMsg('Could not change the setting.', false); return; }
  renderMcpSettings(await res.json());
  mcpSetMsg(on ? 'Claude access is on.' : 'Claude access is off.', true);
}

async function disconnectMcp(id) {
  if (!confirm('Disconnect this person? They will need to connect Claude again.')) return;
  const res = await api(`/api/settings/mcp/connections/${id}`, { method: 'DELETE' });
  if (!res?.ok) { mcpSetMsg('Could not disconnect.', false); return; }
  renderMcpSettings(await res.json());
  mcpSetMsg('Disconnected.', true);
}

function copyMcpUrl() {
  const el = document.getElementById('mcpUrl');
  navigator.clipboard?.writeText(el.value).then(() => mcpSetMsg('Address copied.', true), () => { el.select(); });
}

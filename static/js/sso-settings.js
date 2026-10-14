// Settings — Single Sign-On (Microsoft Entra ID), HR Manager only. See routers/sso.py. The client secret is never fetched
// back: only whether one is saved.

let ssoSettings = null;

function ssoSetMsg(id, text, ok) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text || '';
  el.className = `text-xs ${ok === false ? 'text-red-600' : ok ? 'text-green-600' : 'text-slate-500'}`;
}

function ssoStatus(s) {
  if (!s.configured) return { text: 'Not set up', cls: 'bg-slate-100 text-slate-500' };
  if (s.enabled) return { text: 'On', cls: 'bg-green-100 text-green-700' };
  if (s.last_test_ok) return { text: 'Tested, off', cls: 'bg-blue-100 text-blue-700' };
  return { text: 'Saved, not tested', cls: 'bg-amber-100 text-amber-700' };
}

function renderSsoSettings(s) {
  ssoSettings = s;
  document.getElementById('ssoRedirectUri').value = s.redirect_uri || '';
  document.getElementById('ssoTenantId').value = s.tenant_id || '';
  document.getElementById('ssoClientId').value = s.client_id || '';
  document.getElementById('ssoClientSecret').value = '';
  document.getElementById('ssoSecretHint').textContent = s.has_secret ? 'A secret is saved. Leave this blank to keep it.' : 'Required the first time.';
  const st = ssoStatus(s);
  const badge = document.getElementById('ssoStatusBadge');
  badge.textContent = st.text;
  badge.className = `inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${st.cls}`;
  document.getElementById('ssoLinkedNote').textContent = s.configured
    ? `${s.linked_users} of ${s.active_users} active users have signed in with Microsoft so far.` : '';
  const testBtn = document.getElementById('ssoTestBtn');
  testBtn.classList.toggle('hidden', !s.configured);
  if (s.last_test_at) ssoSetMsg('ssoTestResult', `${s.last_test_ok ? 'Last test worked' : 'Last test failed'} (${fmtDateTime(s.last_test_at)}): ${s.last_test_detail || ''}`, s.last_test_ok);
  else ssoSetMsg('ssoTestResult', s.configured ? 'Not tested yet.' : 'Save the details first.', null);
  const toggle = document.getElementById('ssoEnabledToggle');
  toggle.checked = !!s.enabled;
  toggle.disabled = !s.configured || (!s.last_test_ok && !s.enabled);
  document.getElementById('ssoEnabledNote').textContent = toggle.disabled
    ? 'Available after a successful test sign-in.' : 'Password sign-in keeps working either way.';
  ssoSetMsg('ssoEnabledMsg', '', null);
}

async function loadSsoSettingsPage() {
  ssoSetMsg('ssoSaveMsg', '', null);
  const res = await api('/api/settings/sso');
  if (!res?.ok) {
    document.getElementById('ssoStatusBadge').textContent = 'Unavailable';
    ssoSetMsg('ssoSaveMsg', 'Only an HR Manager can open these settings.', false);
    return;
  }
  renderSsoSettings(await res.json());
}

// Saves what is in the form; resolves true when it saved (or there was nothing to change).
async function ssoSaveForm() {
  const body = {
    tenant_id: document.getElementById('ssoTenantId').value.trim(),
    client_id: document.getElementById('ssoClientId').value.trim(),
    client_secret: document.getElementById('ssoClientSecret').value,
  };
  const res = await api('/api/settings/sso', { method: 'PUT', body: JSON.stringify(body) });
  if (!res?.ok) { const d = await res?.json().catch(() => null); ssoSetMsg('ssoSaveMsg', d?.detail ? apiErrorText(d.detail) : 'Could not save.', false); return false; }
  renderSsoSettings(await res.json());
  return true;
}

const saveSsoSettings = guardAsync(async function () {
  const wasOn = ssoSettings?.enabled;
  if (await ssoSaveForm()) ssoSetMsg('ssoSaveMsg', wasOn && !ssoSettings.enabled ? 'Saved. The details changed, so Microsoft sign-in was turned off until you test it again.' : 'Saved.', true);
});

const testSsoSignIn = guardAsync(async function () {
  const dirty = document.getElementById('ssoClientSecret').value
    || document.getElementById('ssoTenantId').value.trim() !== (ssoSettings?.tenant_id || '')
    || document.getElementById('ssoClientId').value.trim() !== (ssoSettings?.client_id || '');
  if (dirty && !(await ssoSaveForm())) return;
  const res = await api('/api/settings/sso/test-start', { method: 'POST' });
  if (!res?.ok) { const d = await res?.json().catch(() => null); ssoSetMsg('ssoTestResult', d?.detail ? apiErrorText(d.detail) : 'Could not start the test.', false); return; }
  window.location.href = (await res.json()).authorize_url;
});

const toggleSsoEnabled = guardAsync(async function () {
  const enabled = document.getElementById('ssoEnabledToggle').checked;
  const res = await api('/api/settings/sso/enabled', { method: 'PUT', body: JSON.stringify({ enabled }) });
  if (!res?.ok) {
    const d = await res?.json().catch(() => null);
    document.getElementById('ssoEnabledToggle').checked = !enabled;
    ssoSetMsg('ssoEnabledMsg', d?.detail ? apiErrorText(d.detail) : 'Could not change it.', false);
    return;
  }
  renderSsoSettings(await res.json());
  ssoSetMsg('ssoEnabledMsg', enabled ? 'Microsoft sign-in is on.' : 'Microsoft sign-in is off.', true);
});

function copySsoRedirect() {
  const input = document.getElementById('ssoRedirectUri');
  input.select();
  navigator.clipboard?.writeText(input.value).catch(() => {});
}

async function removeSsoSettings() {
  if (!ssoSettings?.configured) return;
  if (!confirm('Remove the Microsoft sign-in settings? The button disappears from the login screen. People already linked stay linked.')) return;
  const res = await api('/api/settings/sso', { method: 'DELETE' });
  if (!res?.ok) { ssoSetMsg('ssoSaveMsg', 'Could not remove.', false); return; }
  loadSsoSettingsPage();
}

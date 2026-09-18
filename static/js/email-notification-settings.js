// Settings — Email Notifications (hr_manager only): institution's own
// BYO-SMTP mailbox (see routers/notifications.py's EMAIL_SETTINGS_ROLES).
// Mirrors static/js/ai-assistant-settings.js's BYOK pattern — credentials
// are validated with a real login attempt before saving, and never
// fetched back once saved; only "configured" + non-secret metadata come
// back from GET.

function renderEmailSettingsStatus(s) {
  const badge = document.getElementById('emailSettingsStatusBadge');
  const detail = document.getElementById('emailSettingsStatusDetail');
  const removeBtn = document.getElementById('emailSettingsRemoveBtn');
  const testRow = document.getElementById('emailSettingsTestRow');
  if (s?.configured) {
    const on = s.notifications_email_enabled;
    badge.textContent = on ? 'Enabled' : 'Configured, but disabled';
    badge.className = `inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${on ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`;
    detail.textContent = `${esc(s.smtp_from_address || '')} · configured ${fmtDateTime(s.smtp_configured_at) || 'recently'}`;
    removeBtn.classList.remove('hidden');
    testRow.classList.remove('hidden');
  } else {
    badge.textContent = 'Not configured';
    badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-500';
    detail.textContent = 'No SMTP mailbox connected yet — approval emails will not be sent.';
    removeBtn.classList.add('hidden');
    testRow.classList.add('hidden');
  }
}

const EMAIL_LOG_STATUS_COLORS = {'sent':'status-positive', 'failed':'status-negative', 'skipped':'status-neutral'};

async function loadEmailLog() {
  const list = document.getElementById('emailLogList');
  const empty = document.getElementById('emailLogEmpty');
  const res = await api('/api/notifications/email-log');
  const rows = res?.ok ? await res.json() : [];
  if (!rows.length) { list.innerHTML = ''; empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');
  list.innerHTML = rows.map(r => `
    <tr class="border-t border-slate-100">
      <td class="px-3 py-2 text-slate-500 whitespace-nowrap">${fmtDateTime(r.created_at)}</td>
      <td class="px-3 py-2 text-slate-700">${esc(r.recipient_email)}</td>
      <td class="px-3 py-2 text-slate-500">${esc(r.category)}</td>
      <td class="px-3 py-2"><span class="badge text-xs ${statusColor(EMAIL_LOG_STATUS_COLORS, r.status)}" title="${esc(r.error||'')}">${esc(r.status)}</span></td>
    </tr>`).join('');
}

async function loadEmailNotificationSettingsPage() {
  document.getElementById('emailSettingsUsername').value = '';
  document.getElementById('emailSettingsPassword').value = '';
  document.getElementById('emailSettingsMsg').textContent = '';
  document.getElementById('emailSettingsTestTo').value = '';
  const badge = document.getElementById('emailSettingsStatusBadge');
  badge.textContent = 'Loading…';
  badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-500';
  document.getElementById('emailSettingsStatusDetail').textContent = '';
  loadEmailLog();
  const res = await api('/api/notifications/email-settings');
  if (res?.ok) {
    const s = await res.json();
    renderEmailSettingsStatus(s);
    document.getElementById('emailSettingsEnabled').checked = !!s.notifications_email_enabled;
    document.getElementById('emailSettingsHost').value = s.smtp_host || '';
    document.getElementById('emailSettingsPort').value = s.smtp_port || '';
    document.getElementById('emailSettingsUseTls').checked = s.smtp_use_tls !== false;
    document.getElementById('emailSettingsFromAddress').value = s.smtp_from_address || '';
    document.getElementById('emailSettingsFromName').value = s.smtp_from_name || '';
    return;
  }
  badge.textContent = 'Unavailable';
  badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-500';
  document.getElementById('emailSettingsStatusDetail').textContent =
    res?.status === 403
      ? "Only an institution's HR Manager can view or manage this."
      : 'Could not load email notification settings right now.';
}

const saveEmailSettings = guardAsync(async function() {
  const msg = document.getElementById('emailSettingsMsg');
  const body = {
    smtp_host: document.getElementById('emailSettingsHost').value.trim(),
    smtp_port: parseInt(document.getElementById('emailSettingsPort').value) || null,
    smtp_use_tls: document.getElementById('emailSettingsUseTls').checked,
    smtp_from_address: document.getElementById('emailSettingsFromAddress').value.trim(),
    smtp_from_name: document.getElementById('emailSettingsFromName').value.trim() || null,
    smtp_username: document.getElementById('emailSettingsUsername').value.trim(),
    smtp_password: document.getElementById('emailSettingsPassword').value,
    notifications_email_enabled: document.getElementById('emailSettingsEnabled').checked,
  };
  if (!body.smtp_host || !body.smtp_port || !body.smtp_from_address || !body.smtp_username || !body.smtp_password) {
    msg.textContent = 'Host, port, from address, username, and password are all required.';
    msg.className = 'text-xs mt-3 text-red-600';
    return;
  }
  msg.textContent = 'Validating with your mail server…';
  msg.className = 'text-xs mt-3 text-slate-400';
  const res = await api('/api/notifications/email-settings', { method: 'PUT', body: JSON.stringify(body) });
  if (res?.ok) {
    const s = await res.json();
    renderEmailSettingsStatus(s);
    document.getElementById('emailSettingsPassword').value = '';
    msg.textContent = 'Settings saved.';
    msg.className = 'text-xs mt-3 text-green-600';
  } else {
    const d = await res.json();
    msg.textContent = apiErrorText(d.detail, 'Failed to save settings.');
    msg.className = 'text-xs mt-3 text-red-600';
  }
});

const removeEmailSettings = guardAsync(async function() {
  if (!confirm('Remove this SMTP configuration? Email notifications will stop going out until reconfigured.')) return;
  const msg = document.getElementById('emailSettingsMsg');
  const res = await api('/api/notifications/email-settings', { method: 'DELETE' });
  if (res?.ok) {
    const s = await res.json();
    renderEmailSettingsStatus(s);
    document.getElementById('emailSettingsEnabled').checked = false;
    document.getElementById('emailSettingsHost').value = '';
    document.getElementById('emailSettingsPort').value = '';
    document.getElementById('emailSettingsFromAddress').value = '';
    document.getElementById('emailSettingsFromName').value = '';
    document.getElementById('emailSettingsUsername').value = '';
    document.getElementById('emailSettingsPassword').value = '';
    msg.textContent = 'Settings removed.';
    msg.className = 'text-xs mt-3 text-slate-500';
  } else {
    const d = await res.json();
    msg.textContent = apiErrorText(d.detail, 'Failed to remove settings.');
    msg.className = 'text-xs mt-3 text-red-600';
  }
});

const sendTestEmail = guardAsync(async function() {
  const to = document.getElementById('emailSettingsTestTo').value.trim();
  const msg = document.getElementById('emailSettingsMsg');
  if (!to) { msg.textContent = 'Enter an address to send the test to.'; msg.className = 'text-xs mt-3 text-red-600'; return; }
  msg.textContent = 'Sending test email…';
  msg.className = 'text-xs mt-3 text-slate-400';
  const res = await api('/api/notifications/email-settings/test', { method: 'POST', body: JSON.stringify({ to_email: to }) });
  if (res?.ok) {
    msg.textContent = `Test email sent to ${to}.`;
    msg.className = 'text-xs mt-3 text-green-600';
  } else {
    const d = await res.json();
    msg.textContent = apiErrorText(d.detail, 'Failed to send test email.');
    msg.className = 'text-xs mt-3 text-red-600';
  }
});

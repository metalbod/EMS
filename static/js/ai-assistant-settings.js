// Settings — AI Assistant (hr_manager only): institution's own Anthropic
// API key (BYOK — see routers/assistant.py's ASSISTANT_SETTINGS_ROLES).
// The key itself is never fetched back — only whether one is configured,
// its last 4 characters, and when it was added.

function renderAiAssistantStatus(s) {
  const badge = document.getElementById('aiAssistantStatusBadge');
  const detail = document.getElementById('aiAssistantStatusDetail');
  const removeBtn = document.getElementById('aiAssistantRemoveBtn');
  if (s?.configured) {
    badge.textContent = 'Using your own key';
    badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700';
    detail.textContent = `Key ending in ...${s.key_last4 || '????'} · added ${fmtDateTime(s.added_at) || 'recently'}`;
    removeBtn.classList.remove('hidden');
  } else {
    badge.textContent = 'Using platform key';
    badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-500';
    detail.textContent = 'No key of your own configured — falling back to the platform default, if any.';
    removeBtn.classList.add('hidden');
  }
}

async function loadAiAssistantSettingsPage() {
  document.getElementById('aiAssistantKeyInput').value = '';
  document.getElementById('aiAssistantMsg').textContent = '';
  const badge = document.getElementById('aiAssistantStatusBadge');
  badge.textContent = 'Loading…';
  badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-500';
  document.getElementById('aiAssistantStatusDetail').textContent = '';
  const res = await api('/api/assistant/settings');
  if (res?.ok) renderAiAssistantStatus(await res.json());
}

const saveAiAssistantKey = guardAsync(async function() {
  const input = document.getElementById('aiAssistantKeyInput');
  const msg = document.getElementById('aiAssistantMsg');
  const key = input.value.trim();
  if (!key) { msg.textContent = 'Enter an API key first.'; msg.className = 'text-xs mt-3 text-red-600'; return; }
  msg.textContent = 'Validating with Anthropic…';
  msg.className = 'text-xs mt-3 text-slate-400';
  const res = await api('/api/assistant/settings', { method: 'PUT', body: JSON.stringify({ api_key: key }) });
  if (res?.ok) {
    renderAiAssistantStatus(await res.json());
    input.value = '';
    msg.textContent = 'Key saved.';
    msg.className = 'text-xs mt-3 text-green-600';
  } else {
    const d = await res.json();
    msg.textContent = d.detail || 'Failed to save key.';
    msg.className = 'text-xs mt-3 text-red-600';
  }
});

const removeAiAssistantKey = guardAsync(async function() {
  if (!confirm("Remove your organization's Anthropic key? The assistant will fall back to the platform key, if any.")) return;
  const msg = document.getElementById('aiAssistantMsg');
  const res = await api('/api/assistant/settings', { method: 'DELETE' });
  if (res?.ok) {
    renderAiAssistantStatus(await res.json());
    msg.textContent = 'Key removed.';
    msg.className = 'text-xs mt-3 text-slate-500';
  } else {
    const d = await res.json();
    msg.textContent = d.detail || 'Failed to remove key.';
    msg.className = 'text-xs mt-3 text-red-600';
  }
});

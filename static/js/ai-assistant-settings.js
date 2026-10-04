// Settings — AI Assistant (hr_manager only, both tabs): institution's own
// Anthropic API key (BYOK — see routers/assistant.py's
// ASSISTANT_SETTINGS_ROLES) and token usage. The key itself is never
// fetched back — only whether one is configured, its last 4 characters, and
// when it was added.

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
  switchAiAssistantTab('ai-key'); // always land on the key tab on a fresh visit
  document.getElementById('aiAssistantKeyInput').value = '';
  document.getElementById('aiAssistantMsg').textContent = '';
  const badge = document.getElementById('aiAssistantStatusBadge');
  badge.textContent = 'Loading…';
  badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-500';
  document.getElementById('aiAssistantStatusDetail').textContent = '';
  const res = await api('/api/assistant/settings');
  if (res?.ok) {
    renderAiAssistantStatus(await res.json());
    return;
  }
  // Reachable by superadmin (e.g. browser back/forward) even though the nav
  // item is hidden for that role — ASSISTANT_SETTINGS_ROLES is hr_manager-only
  // by product decision (routers/assistant.py), so a 403 here is expected,
  // not a real error. Left "Loading…" forever with nothing shown otherwise.
  badge.textContent = 'Unavailable';
  badge.className = 'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-500';
  document.getElementById('aiAssistantStatusDetail').textContent =
    res?.status === 403
      ? "Only an institution's HR Manager can view or manage this key."
      : 'Could not load AI Assistant settings right now.';
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


// ---------------------------------------------------------------------------
// Usage tab — token counts per person by AI chat vs. resume extraction
// (GET /api/assistant/usage; recorded by core/ai_usage.py).
// ---------------------------------------------------------------------------
let aiUsageRows = [];
let aiUsageSort = { key: 'total_tokens', dir: 'desc' };

function switchAiAssistantTab(tabId) {
  document.querySelectorAll('.ai-tab-panel').forEach(el => el.classList.toggle('hidden', el.id !== tabId));
  document.querySelectorAll('[data-aitab]').forEach(el => el.classList.toggle('pill-tab-active', el.dataset.aitab === tabId));
  if (tabId === 'ai-usage') loadAiUsage();
}

function _isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Calendar-day range for the picked preset, from the browser's local date.
function aiUsageDateRange(preset, today = new Date()) {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const start = new Date(end);
  if (preset === 'this_month') start.setDate(1);
  else if (preset === 'last_30') start.setDate(start.getDate() - 29);
  else if (preset === 'last_90') start.setDate(start.getDate() - 89);
  else return { date_from: '2000-01-01', date_to: _isoDate(end) };
  return { date_from: _isoDate(start), date_to: _isoDate(end) };
}

function _fmtTokens(n) { return Number(n || 0).toLocaleString('en-MY'); }

async function loadAiUsage() {
  const preset = document.getElementById('aiUsageRange').value;
  const range = aiUsageDateRange(preset);
  const label = document.getElementById('aiUsageRangeLabel');
  label.textContent = preset === 'all' ? 'Since usage tracking began' : `${fmtDate(range.date_from)} – ${fmtDate(range.date_to)}`;
  document.getElementById('aiUsageTableBody').innerHTML = '';
  document.getElementById('aiUsageEmptyState').classList.add('hidden');
  const res = await api(`/api/assistant/usage?date_from=${range.date_from}&date_to=${range.date_to}`);
  if (!res?.ok) {
    const msg = document.getElementById('aiUsageEmptyState');
    msg.textContent = res?.status === 403 ? "Only an institution's HR Manager can view AI usage." : 'Could not load AI usage right now.';
    msg.classList.remove('hidden');
    return;
  }
  renderAiUsage(await res.json());
}

function renderAiUsage(d) {
  const cell = (idTokens, idDetail, c) => {
    document.getElementById(idTokens).textContent = _fmtTokens(c.total_tokens);
    document.getElementById(idDetail).textContent =
      `${_fmtTokens(c.requests)} request${c.requests === 1 ? '' : 's'} · ${_fmtTokens(c.input_tokens)} in / ${_fmtTokens(c.output_tokens)} out`;
  };
  cell('aiUsageTotalTokens', 'aiUsageTotalDetail', d.total);
  cell('aiUsageChatTokens', 'aiUsageChatDetail', d.chat);
  cell('aiUsageResumeTokens', 'aiUsageResumeDetail', d.resume_extraction);
  aiUsageRows = d.by_user;
  renderAiUsageTable();
}

function sortAiUsageRows(rows, sort) {
  const dir = sort.dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = a[sort.key], y = b[sort.key];
    const cmp = typeof x === 'string' ? x.localeCompare(y) : (x - y);
    return cmp * dir || a.name.localeCompare(b.name);
  });
}

function setAiUsageSort(key) {
  aiUsageSort = aiUsageSort.key === key
    ? { key, dir: aiUsageSort.dir === 'asc' ? 'desc' : 'asc' }
    : { key, dir: key === 'name' ? 'asc' : 'desc' };
  renderAiUsageTable();
}

function renderAiUsageTable() {
  document.querySelectorAll('.ai-usage-sort-arrow').forEach(el => {
    el.textContent = el.dataset.sortKey === aiUsageSort.key ? (aiUsageSort.dir === 'asc' ? ' ▲' : ' ▼') : '';
  });
  const empty = document.getElementById('aiUsageEmptyState');
  empty.textContent = 'No AI usage recorded in this period.';
  empty.classList.toggle('hidden', aiUsageRows.length > 0);
  document.getElementById('aiUsageTableBody').innerHTML = sortAiUsageRows(aiUsageRows, aiUsageSort).map(r => `
    <tr>
      <td class="px-4 py-3 font-medium text-slate-700">${esc(r.name)}</td>
      <td class="px-4 py-3 text-right text-slate-600">${_fmtTokens(r.chat_requests)}</td>
      <td class="px-4 py-3 text-right text-slate-600">${_fmtTokens(r.chat_tokens)}</td>
      <td class="px-4 py-3 text-right text-slate-600">${_fmtTokens(r.resume_requests)}</td>
      <td class="px-4 py-3 text-right text-slate-600">${_fmtTokens(r.resume_tokens)}</td>
      <td class="px-4 py-3 text-right font-semibold text-slate-800">${_fmtTokens(r.total_tokens)}</td>
    </tr>`).join('');
}

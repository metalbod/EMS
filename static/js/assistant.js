// ---------------------------------------------------------------------------
// AI Assistant chatbot — floating widget, all pages. Ephemeral history: kept
// in memory only, resent (capped) with each request, never persisted
// server-side. Cleared on a full page reload AND on logout (see
// resetAssistant) — the in-memory array/DOM otherwise survive a same-tab
// logout -> login as a different employee, leaking one employee's chat
// content (which can include their own leave/payslip/benefits data) into
// the next employee's view of the same browser tab.
// ---------------------------------------------------------------------------
const ASSISTANT_MAX_HISTORY_TURNS = 8;
let assistantHistory = [];
let assistantBusy = false;

function resetAssistant() {
  assistantHistory = [];
  assistantBusy = false;
  const list = document.getElementById('assistantMessages');
  if (list) list.innerHTML = '';
  document.getElementById('assistantPanel')?.classList.add('hidden');
  document.getElementById('assistantFab')?.classList.add('hidden');
}

async function initAssistant() {
  // Always start from a clean slate before deciding whether to show the FAB
  // for whoever is logged in now — see resetAssistant's docstring above.
  // Also called directly from doLogout() (core.js) so the previous user's
  // chat vanishes immediately at logout, not just at the next login.
  resetAssistant();
  // Hidden entirely (not just left to fail gracefully in chat) when the
  // institution has neither its own BYOK key nor a platform default — see
  // GET /api/assistant/availability, open to any authenticated user.
  const res = await api('/api/assistant/availability');
  const data = res?.ok ? await res.json() : null;
  if (data?.available) document.getElementById('assistantFab')?.classList.remove('hidden');
}

function toggleAssistantPanel() {
  document.getElementById('assistantPanel')?.classList.toggle('hidden');
}

function assistantAppendBubble(role, text) {
  const list = document.getElementById('assistantMessages');
  if (!list) return;
  const bubble = document.createElement('div');
  bubble.className = role === 'user'
    ? 'ml-8 bg-indigo-50 text-slate-800 rounded-lg px-3 py-2'
    : 'mr-8 bg-slate-100 text-slate-800 rounded-lg px-3 py-2';
  bubble.textContent = text; // never innerHTML — untrusted user/model text
  list.appendChild(bubble);
  list.scrollTop = list.scrollHeight;
}

async function submitAssistantMessage(e) {
  e.preventDefault();
  if (assistantBusy) return;
  const input = document.getElementById('assistantInput');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  assistantAppendBubble('user', message);
  assistantBusy = true;
  try {
    const res = await api('/api/assistant/chat', {
      method: 'POST',
      body: JSON.stringify({ message, history: assistantHistory.slice(-ASSISTANT_MAX_HISTORY_TURNS * 2) }),
    });
    if (!res) return; // api() already handled 401 (logout)
    const data = await res.json();
    if (!res.ok) {
      assistantAppendBubble('assistant', data.detail || 'Something went wrong — please try again.');
      return;
    }
    assistantAppendBubble('assistant', data.reply);
    assistantHistory.push({ role: 'user', content: message });
    assistantHistory.push({ role: 'assistant', content: data.reply });
  } catch (err) {
    assistantAppendBubble('assistant', 'Something went wrong — please try again.');
  } finally {
    assistantBusy = false;
  }
}

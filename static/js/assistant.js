// ---------------------------------------------------------------------------
// AI Assistant chatbot — floating widget, all pages. Ephemeral history: kept
// in memory only, resent (capped) with each request, cleared on reload.
// ---------------------------------------------------------------------------
const ASSISTANT_MAX_HISTORY_TURNS = 8;
let assistantHistory = [];
let assistantBusy = false;

function initAssistant() {
  document.getElementById('assistantFab')?.classList.remove('hidden');
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

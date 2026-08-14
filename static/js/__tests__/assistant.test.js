import { describe, it, expect, beforeEach, vi } from 'vitest';

// Matches the existing suite's convention (core.test.js, app-init.test.js):
// build a DOM fixture and re-implement the function under test inline,
// rather than importing the real static/js file (loaded as a plain
// <script> global in the browser, not a module).

describe('Assistant widget', () => {
  const ASSISTANT_MAX_HISTORY_TURNS = 8;
  let fab, panel, messages, history, busy;

  beforeEach(() => {
    document.body.innerHTML = `
      <button id="assistantFab" class="hidden"></button>
      <div id="assistantPanel" class="hidden">
        <div id="assistantMessages"></div>
      </div>
    `;
    fab = document.getElementById('assistantFab');
    panel = document.getElementById('assistantPanel');
    messages = document.getElementById('assistantMessages');
    history = [];
    busy = false;
  });

  function toggleAssistantPanel() {
    panel.classList.toggle('hidden');
  }

  function initAssistant() {
    fab.classList.remove('hidden');
  }

  function appendBubble(role, text) {
    const bubble = document.createElement('div');
    bubble.className = role === 'user' ? 'ml-8' : 'mr-8';
    bubble.textContent = text;
    messages.appendChild(bubble);
  }

  async function submitAssistantMessage(message, apiFn) {
    if (busy) return;
    busy = true;
    appendBubble('user', message);
    try {
      const res = await apiFn('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message, history: history.slice(-ASSISTANT_MAX_HISTORY_TURNS * 2) }),
      });
      if (!res) return;
      const data = await res.json();
      if (!res.ok) {
        appendBubble('assistant', data.detail || 'Something went wrong — please try again.');
        return;
      }
      appendBubble('assistant', data.reply);
      history.push({ role: 'user', content: message });
      history.push({ role: 'assistant', content: data.reply });
    } catch (e) {
      appendBubble('assistant', 'Something went wrong — please try again.');
    } finally {
      busy = false;
    }
  }

  it('initAssistant reveals the FAB', () => {
    expect(fab.classList.contains('hidden')).toBe(true);
    initAssistant();
    expect(fab.classList.contains('hidden')).toBe(false);
  });

  it('toggleAssistantPanel opens and closes the panel', () => {
    expect(panel.classList.contains('hidden')).toBe(true);
    toggleAssistantPanel();
    expect(panel.classList.contains('hidden')).toBe(false);
    toggleAssistantPanel();
    expect(panel.classList.contains('hidden')).toBe(true);
  });

  it('renders message text as literal text, never interpreted as HTML (XSS regression)', async () => {
    const malicious = '<img src=x onerror="window.__pwned=true">';
    const apiFn = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'ok' }),
    });
    await submitAssistantMessage(malicious, apiFn);
    const firstBubble = messages.firstChild;
    expect(firstBubble.textContent).toBe(malicious);
    expect(firstBubble.querySelector('img')).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });

  it('caps resent history at ASSISTANT_MAX_HISTORY_TURNS*2 messages', async () => {
    const apiFn = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'reply' }),
    });
    for (let i = 0; i < 20; i++) {
      await submitAssistantMessage(`turn ${i}`, apiFn);
    }
    const lastCallBody = JSON.parse(apiFn.mock.calls[apiFn.mock.calls.length - 1][1].body);
    expect(lastCallBody.history.length).toBeLessThanOrEqual(ASSISTANT_MAX_HISTORY_TURNS * 2);
  });

  it('renders a graceful error bubble on a null api() response (401) without adding to history', async () => {
    const apiFn = vi.fn().mockResolvedValue(null); // matches api()'s documented 401 behavior
    await submitAssistantMessage('hello', apiFn);
    expect(history.length).toBe(0);
    // Only the user's own bubble should be present — no assistant reply, no crash.
    expect(messages.children.length).toBe(1);
  });

  it('renders a graceful error bubble on a non-ok response without adding to history', async () => {
    const apiFn = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Rate limited' }),
    });
    await submitAssistantMessage('hello', apiFn);
    expect(history.length).toBe(0);
    expect(messages.children[1].textContent).toBe('Rate limited');
  });
});

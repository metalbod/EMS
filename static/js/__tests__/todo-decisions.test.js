import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL dashboard.js + todo-decisions.js together, with only the
// globals they read stubbed (api, esc, fmtDate, ...), so the inline Approve /
// Reject flow is tested as shipped. Inline onclick handlers resolve against
// jsdom's own window, so the handlers are attached there and buttons are
// clicked for real.
const SRC = ['../dashboard.js', '../todo-decisions.js'].map(f => readFileSync(resolve(__dirname, f), 'utf8')).join('\n');
const escStub = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const fmtDateStub = v => (v ? String(v).slice(0, 10) : '—');
const HANDLERS = ['todoApprove', 'todoRejectOpen', 'todoRejectInput', 'todoRejectCancel', 'todoRejectConfirm', 'toggleTodoGroup'];

function load(apiImpl) {
  const factory = new Function('api', 'esc', 'fmtDate', 'currentUser', 'guardAsync', 'showPage', 'apiErrorText',
    `${SRC}\nreturn { loadDashboardTodos, ${HANDLERS.join(', ')} };`);
  const shown = [];
  const mod = factory(apiImpl, escStub, fmtDateStub, { role: 'hr_manager', employee_id: 'E-ME' }, fn => fn,
    (p, o) => shown.push([p, o]), d => (typeof d === 'string' ? d : ''));
  const win = globalThis.jsdom?.window || document.defaultView;
  for (const h of HANDLERS) win[h] = mod[h];
  return { ...mod, shown };
}

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const leaveItem = (over = {}) => ({
  key: 'leave-approval-5', kind: 'approval', module: 'leave', ref_id: 5, focus_id: 5, page: 'leave-approvals', count: 1,
  label: 'Annual Leave — Aiman (leave, awaiting your approval)', stage: 'Annual Leave: 2026-10-05 to 2026-10-09',
  stage_type: 'Leave', employee_name: 'Aiman', employee_id: 'E9', due_date: null, waiting_since: '2026-09-20', days_waiting: 8, days_overdue: null, ...over,
});
const ldItem = (over = {}) => leaveItem({ key: 'ld_enrollment-approval-9', module: 'ld_enrollment', ref_id: 9, focus_id: 9, page: 'ld-trainings', stage_type: 'Training Enrollment', stage: 'First Aid', ...over });
const claimItem = (over = {}) => leaveItem({ key: 'claims-approval-3', module: 'claims', ref_id: 3, focus_id: 3, page: 'ben-claims', stage_type: 'Benefit Claim', stage: 'Dental claim — RM 120.00', ...over });

/** An api() stub driven by a queue of responders, recording every call. */
function makeApi({ todos = [], patch = () => json(200, { status: 'Approved' }) } = {}) {
  const calls = [];
  let list = todos;
  const impl = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null });
    if (url === '/api/todos') return json(200, typeof list === 'function' ? list() : list);
    return patch(url, opts, calls);
  };
  impl.calls = calls;
  impl.setList = l => { list = l; };
  return impl;
}

const $ = id => document.getElementById(id);
const body = () => $('dashboardTodoBody');
const row = key => [...body().querySelectorAll('tbody tr')].find(r => r.querySelector(`[onclick*="'${key}'"]`));
const btn = (label, scope = body()) => [...scope.querySelectorAll('button')].find(b => b.textContent.trim() === label);
const flush = () => new Promise(r => setTimeout(r, 0));

beforeEach(() => {
  document.body.innerHTML = `
    <p id="kpiApprovals">—</p>
    <div id="dashboardTodoCard"><h2 tabindex="-1">Your to-do<span id="dashboardTodoCount"></span></h2>
      <p id="dashboardTodoResult" class="hidden"></p>
      <div id="dashboardTodoError" class="hidden"><p id="dashboardTodoErrorMsg"></p><button id="dashboardTodoRetry"></button></div>
      <div id="dashboardTodoBody" class="hidden"></div>
      <p id="dashboardTodoEmpty" class="hidden"></p><p id="dashboardTodoLive" role="status"></p></div>`;
});
afterEach(() => { vi.useRealTimers(); });

describe('which requests get inline decisions', () => {
  it('leave and L&D get Approve / Reject / Details; every other kind keeps a click-through Review', async () => {
    const api = makeApi({ todos: [leaveItem(), ldItem(), claimItem(), leaveItem({ key: 'resignation-approval-2', module: 'resignation', ref_id: 2 })] });
    await load(api).loadDashboardTodos();
    const rows = [...body().querySelectorAll('tbody tr')];
    expect(rows).toHaveLength(4);
    for (const [i, expected] of [[0, true], [1, true], [2, false], [3, false]]) {
      expect(!!btn('Approve', rows[i]), `row ${i} approve`).toBe(expected);
      expect(!!btn('Reject', rows[i]), `row ${i} reject`).toBe(expected);
      expect(!!btn('Review', rows[i]), `row ${i} review`).toBe(!expected);
      expect(rows[i].hasAttribute('onclick'), `row ${i} click-through`).toBe(!expected);
    }
  });

  it('refuses a request without a usable id or key (no inline buttons, plain Review)', async () => {
    const api = makeApi({ todos: [leaveItem({ ref_id: null }), leaveItem({ key: 'x"y', ref_id: 5 })] });
    await load(api).loadDashboardTodos();
    expect(body().querySelectorAll('.todo-decision-actions')).toHaveLength(0);
    expect(body().querySelectorAll('tbody tr button.todo-action')).toHaveLength(2);
  });

  it('names what each button acts on, and Details deep-links to the record', async () => {
    await load(makeApi({ todos: [leaveItem()] })).loadDashboardTodos();
    const r = body().querySelector('tbody tr');
    expect(btn('Approve', r).getAttribute('aria-label')).toBe("Approve Aiman's leave request");
    expect(btn('Reject', r).getAttribute('aria-label')).toBe("Reject Aiman's leave request");
    expect(btn('Details', r).getAttribute('onclick')).toContain("showPage('leave-approvals',{focus:5})");
  });
});

describe('approve', () => {
  it('sends the same PATCH the Leave page sends, then re-fetches the list, announces and refocuses', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => json(200, { status: 'Approved' }) });
    const mod = load(api);
    await mod.loadDashboardTodos();
    api.setList([]); // the server no longer lists it
    btn('Approve').click();
    await flush(); await flush();
    const patch = api.calls.find(c => c.method === 'PATCH');
    expect(patch).toMatchObject({ url: '/api/leave/applications/5/status', body: { status: 'Approved' } });
    expect(api.calls.filter(c => c.url === '/api/todos')).toHaveLength(2); // initial + refresh, no optimistic removal
    // the outcome is spoken first, then the refreshed list's own summary — never overwritten by it
    expect($('dashboardTodoLive').textContent).toBe("Approved Aiman's leave request. You're all caught up — nothing pending right now.");
    expect($('dashboardTodoResult').textContent).toBe("Approved Aiman's leave request.");
    expect($('dashboardTodoResult').classList.contains('hidden')).toBe(false);
    expect($('dashboardTodoEmpty').classList.contains('hidden')).toBe(false); // list is now empty
  });

  it('L&D uses its own endpoint and treats "In Progress" as approved', async () => {
    const api = makeApi({ todos: [ldItem()], patch: () => json(200, { status: 'In Progress' }) });
    await load(api).loadDashboardTodos();
    api.setList([]);
    btn('Approve').click();
    await flush(); await flush();
    expect(api.calls.find(c => c.method === 'PATCH').url).toBe('/api/ld/enrollments/9/status');
    expect($('dashboardTodoLive').textContent).toMatch(/^Approved Aiman's training enrollment\. /);
  });

  it('says so when the approval only advanced a multi-step workflow (still pending)', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => json(200, { status: 'Pending Approval' }) });
    await load(api).loadDashboardTodos();
    btn('Approve').click();
    await flush(); await flush();
    expect($('dashboardTodoLive').textContent).toMatch(/^Approved at your step .* is now with the next approver\. 1 item on your to-do list/);
  });

  it('disables both buttons while the request is in flight, so it cannot be double-submitted', async () => {
    let release;
    const gate = new Promise(r => { release = r; });
    const api = makeApi({ todos: [leaveItem()], patch: () => gate });
    await load(api).loadDashboardTodos();
    btn('Approve').click();
    await flush();
    expect(btn('Approving…').disabled).toBe(true);
    expect(btn('Reject').disabled).toBe(true);
    btn('Approving…').click(); // a second click while busy does nothing
    release(json(200, { status: 'Approved' }));
    await flush(); await flush();
    expect(api.calls.filter(c => c.method === 'PATCH')).toHaveLength(1);
  });
});

describe('reject', () => {
  it('opens a labelled, required reason field and moves focus into it', async () => {
    await load(makeApi({ todos: [leaveItem()] })).loadDashboardTodos();
    btn('Reject').click();
    const ta = document.getElementById('todo-reason-leave-approval-5');
    expect(ta).toBeTruthy();
    expect(document.activeElement).toBe(ta);
    expect(body().querySelector('label[for="todo-reason-leave-approval-5"]').textContent).toContain("Reason for rejecting Aiman's leave request");
    expect(btn('Reject').getAttribute('aria-expanded')).toBe('true');
    expect(btn('Confirm reject')).toBeTruthy();
  });

  it('will not send without a reason (whitespace does not count), and says why', async () => {
    const api = makeApi({ todos: [leaveItem()] });
    await load(api).loadDashboardTodos();
    btn('Reject').click();
    const ta = document.getElementById('todo-reason-leave-approval-5');
    ta.value = '   '; ta.dispatchEvent(new Event('input'));
    btn('Confirm reject').click();
    expect(api.calls.some(c => c.method === 'PATCH')).toBe(false);
    expect(body().querySelector('[role="alert"]').textContent).toMatch(/Add a reason/);
    expect(document.activeElement.id).toBe('todo-reason-leave-approval-5');
  });

  it('sends the trimmed reason as notes, then refreshes and announces', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => json(200, { status: 'Rejected' }) });
    await load(api).loadDashboardTodos();
    api.setList([]);
    btn('Reject').click();
    const ta = document.getElementById('todo-reason-leave-approval-5');
    ta.value = '  Clashes with the audit week  '; ta.dispatchEvent(new Event('input'));
    btn('Confirm reject').click();
    await flush(); await flush();
    expect(api.calls.find(c => c.method === 'PATCH')).toMatchObject({
      url: '/api/leave/applications/5/status', body: { status: 'Rejected', notes: 'Clashes with the audit week' },
    });
    expect($('dashboardTodoLive').textContent).toMatch(/^Rejected Aiman's leave request\. /);
  });

  it('keeps what was typed across a re-render, and Cancel closes it and returns focus to Reject', async () => {
    await load(makeApi({ todos: [leaveItem(), ldItem()] })).loadDashboardTodos();
    btn('Reject', row('todoRejectOpen')).click();
    const ta = document.getElementById('todo-reason-leave-approval-5');
    ta.value = 'half typed'; ta.dispatchEvent(new Event('input'));
    btn('Reject', [...body().querySelectorAll('tbody tr')].find(r => r.textContent.includes('First Aid'))).click(); // opening another row re-renders
    expect(document.getElementById('todo-reason-leave-approval-5').value).toBe('half typed');
    btn('Cancel', document.getElementById('todo-decision-leave-approval-5')).click();
    expect(document.getElementById('todo-reason-leave-approval-5')).toBeNull();
    expect(document.activeElement.getAttribute('data-todo-reject')).toBe('leave-approval-5');
  });

  it('escapes hostile text in the reason field and labels, even after a re-render restores it', async () => {
    await load(makeApi({ todos: [leaveItem({ employee_name: '<img src=x onerror=alert(1)>' }), ldItem()] })).loadDashboardTodos();
    btn('Reject', body().querySelector('tbody tr')).click();
    const ta = document.getElementById('todo-reason-leave-approval-5');
    ta.value = '</textarea><img src=x onerror=alert(2)>'; ta.dispatchEvent(new Event('input'));
    btn('Reject', [...body().querySelectorAll('tbody tr')].find(r => r.textContent.includes('First Aid'))).click(); // re-render
    expect(body().querySelector('img')).toBeNull();
    expect(document.getElementById('todo-reason-leave-approval-5').value).toBe('</textarea><img src=x onerror=alert(2)>');
    expect(body().querySelector('label[for="todo-reason-leave-approval-5"]').textContent).toContain('<img src=x onerror=alert(1)>');
  });
});

describe('failures never lose the user\'s place', () => {
  it('"already decided" by someone else refreshes the list instead of showing a retry', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => json(400, { detail: 'Application is already Approved' }) });
    await load(api).loadDashboardTodos();
    api.setList([]);
    btn('Approve').click();
    await flush(); await flush();
    expect($('dashboardTodoLive').textContent).toMatch(/^Aiman's leave request was already decided by someone else — your list has been refreshed\./);
    expect(api.calls.filter(c => c.url === '/api/todos')).toHaveLength(2);
    expect(body().querySelector('[role="alert"]')).toBeNull();
  });

  it('404 (request removed) is treated the same way', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => json(404, { detail: 'Application not found' }) });
    await load(api).loadDashboardTodos();
    api.setList([]);
    btn('Approve').click();
    await flush(); await flush();
    expect($('dashboardTodoLive').textContent).toMatch(/already decided by someone else/);
  });

  it('a decision message is spoken exactly once — the next ordinary refresh does not repeat it', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => json(200, { status: 'Approved' }) });
    const mod = load(api);
    await mod.loadDashboardTodos();
    api.setList([leaveItem({ key: 'leave-approval-6', ref_id: 6, focus_id: 6 })]);
    btn('Approve').click();
    await flush(); await flush();
    expect($('dashboardTodoLive').textContent).toMatch(/^Approved Aiman's leave request\. /);
    await mod.loadDashboardTodos(); // e.g. a role switch re-runs the loader
    expect($('dashboardTodoLive').textContent).toBe('1 item on your to-do list, 1 waiting for your decision.');
  });

  it('a 403 or other error shows on the row, re-enables the buttons and keeps the request', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => json(403, { detail: 'Only the next approver can act' }) });
    await load(api).loadDashboardTodos();
    btn('Approve').click();
    await flush(); await flush();
    const alertEl = body().querySelector('[role="alert"]');
    expect(alertEl.textContent).toBe("You're not able to approve Aiman's leave request: Only the next approver can act");
    expect(btn('Approve').disabled).toBe(false);
    expect(body().querySelectorAll('tbody tr')[0].textContent).toContain('Annual Leave'); // still listed
    expect(api.calls.filter(c => c.url === '/api/todos')).toHaveLength(1); // no refresh on a plain failure
  });

  it('a network failure says so; a failed reject keeps the reason typed', async () => {
    let n = 0;
    const api = makeApi({ todos: [leaveItem()], patch: () => { if (++n === 1) throw new TypeError('Failed to fetch'); return json(200, { status: 'Rejected' }); } });
    await load(api).loadDashboardTodos();
    btn('Reject').click();
    const ta = document.getElementById('todo-reason-leave-approval-5');
    ta.value = 'Not this week'; ta.dispatchEvent(new Event('input'));
    btn('Confirm reject').click();
    await flush(); await flush();
    expect(body().querySelector('[role="alert"]').textContent).toMatch(/Check your connection/);
    expect(document.getElementById('todo-reason-leave-approval-5').value).toBe('Not this week');
    expect(document.activeElement.id).toBe('todo-reason-leave-approval-5');
    api.setList([]);
    btn('Confirm reject').click(); // retry works and sends the same reason
    await flush(); await flush();
    expect(api.calls.filter(c => c.method === 'PATCH').at(-1).body).toEqual({ status: 'Rejected', notes: 'Not this week' });
  });

  it('a 401 (logout already started) leaves the UI alone rather than flashing an error', async () => {
    const api = makeApi({ todos: [leaveItem()], patch: () => null });
    await load(api).loadDashboardTodos();
    btn('Approve').click();
    await flush(); await flush();
    expect(body().querySelector('[role="alert"]')).toBeNull();
    expect(api.calls.filter(c => c.url === '/api/todos')).toHaveLength(1);
  });

  it('drops inline state for a request that has left the list', async () => {
    const api = makeApi({ todos: [leaveItem()] });
    const mod = load(api);
    await mod.loadDashboardTodos();
    btn('Reject').click();
    api.setList([]); // it was decided elsewhere while the reason was open
    await mod.loadDashboardTodos();
    api.setList([leaveItem()]); // ...and reappears (e.g. re-submitted): no ghost reject panel
    await mod.loadDashboardTodos();
    expect(document.getElementById('todo-reason-leave-approval-5')).toBeNull();
  });
});

describe('the result line', () => {
  it('shows the outcome and hides itself after a few seconds', async () => {
    vi.useFakeTimers();
    const api = makeApi({ todos: [leaveItem()], patch: () => json(200, { status: 'Approved' }) });
    const mod = load(api);
    await vi.runAllTimersAsync(); // let nothing pending interfere
    await mod.loadDashboardTodos();
    api.setList([]);
    btn('Approve').click();
    await vi.advanceTimersByTimeAsync(10);
    expect($('dashboardTodoResult').classList.contains('hidden')).toBe(false);
    await vi.advanceTimersByTimeAsync(8000);
    expect($('dashboardTodoResult').classList.contains('hidden')).toBe(true);
  });
});

import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL static/js/dashboard.js (not a copy of its logic) with the
// handful of globals it reads stubbed, so the Home to-do card is tested
// against the code that ships.
// dashboard.js calls into todo-decisions.js (inline Approve/Reject), so both are loaded together.
const SRC = ['../dashboard.js', '../todo-decisions.js'].map(f => readFileSync(resolve(__dirname, f), 'utf8')).join('\n');

const escStub = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
// Same dd-Mon-yy shape as core.js's fmtDate, so tests can tell a formatted date from a raw ISO one.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmtDateStub = v => {
  if (!v) return '—';
  const [y, m, d] = String(v).slice(0, 10).split('-');
  return `${d}-${MONTHS[+m - 1]}-${y.slice(2)}`;
};

const shown = []; // pages showPage() was asked to open
function load(apiImpl, user = { role: 'hr_manager', employee_id: 'E-ME' }) {
  // guardAsync (core.js) only adds a busy-button wrapper — pass-through here.
  const factory = new Function('api', 'esc', 'fmtDate', 'currentUser', 'guardAsync', 'showPage', 'apiErrorText',
    `${SRC}\nreturn { loadDashboardTodos, toggleTodoGroup, wireDashboardKpiTiles, dashTabKeydown, switchDashTab };`);
  const api = factory(apiImpl, escStub, fmtDateStub, user, fn => fn, p => shown.push(p), d => (typeof d === 'string' ? d : ''));
  // inline onclick="toggleTodoGroup(this)" resolves in jsdom's own window
  (globalThis.jsdom?.window || document.defaultView).toggleTodoGroup = api.toggleTodoGroup;
  return api;
}

const ok = body => async () => ({ ok: true, status: 200, json: async () => body });
const status = code => async () => ({ ok: false, status: code, json: async () => ({}) });

const approval = (over = {}) => ({
  key: 'resignation-approval-1', label: 'Resignation — last day 2026-12-10 — Ng Say Li (resignation, awaiting your approval)',
  stage: 'Resignation — last day 2026-12-10', page: 'resignation-approvals', count: 1, kind: 'approval', employee_name: 'Ng Say Li',
  employee_id: 'E1', focus_id: 11, stage_type: 'Resignation', due_date: null, waiting_since: '2026-09-11', days_waiting: 17, days_overdue: null, ...over,
});
const task = (over = {}) => ({
  key: 'ob-item-9', label: 'Exit Interview — Yahya (Offboarding)', stage: 'Exit Interview', page: 'offboarding', count: 1, kind: 'task',
  employee_name: 'Yahya', employee_id: 'E2', stage_type: 'Offboarding', checklist_id: 7, checklist_open: 3, checklist_total: 5,
  event_date: '2026-10-12', days_until_event: 14, due_date: null, waiting_since: null, days_waiting: null, days_overdue: null, ...over,
});
const reminder = (over = {}) => ({
  key: 'ld-trainings', label: '2 training courses in progress', page: 'ld-trainings', count: 2, kind: 'reminder',
  due_date: null, days_overdue: null, ...over,
});

const $ = id => document.getElementById(id);
const hidden = id => $(id).classList.contains('hidden');
const body = () => $('dashboardTodoBody');

beforeEach(() => {
  shown.length = 0;
  document.body.innerHTML = `
    <p id="kpiApprovals">—</p>
    <h2>Your to-do<span id="dashboardTodoCount"></span></h2>
    <div id="dashboardTodoCard" class="hidden">
      <div id="dashboardTodoError" class="hidden"><p id="dashboardTodoErrorMsg"></p><button id="dashboardTodoRetry"></button></div>
      <div id="dashboardTodoBody" class="hidden"></div>
      <p id="dashboardTodoEmpty" class="hidden"></p>
      <p id="dashboardTodoLive" role="status"></p>
    </div>`;
});

describe('Home to-do card — failure is never "all caught up"', () => {
  it('shows an error (not the empty state) on a 500 and leaves Pending approvals at —', async () => {
    const { loadDashboardTodos } = load(status(500));
    await loadDashboardTodos();
    expect(hidden('dashboardTodoError')).toBe(false);
    expect(hidden('dashboardTodoEmpty')).toBe(true);
    expect(hidden('dashboardTodoBody')).toBe(true);
    expect($('dashboardTodoErrorMsg').textContent).toMatch(/something went wrong/i);
    expect($('kpiApprovals').textContent).toBe('—');
    expect($('dashboardTodoCount').textContent).toBe('');
  });

  it('shows a connection-specific message when the request itself throws, and re-enables Retry', async () => {
    const { loadDashboardTodos } = load(async () => { throw new TypeError('Failed to fetch'); });
    await loadDashboardTodos();
    expect($('dashboardTodoErrorMsg').textContent).toMatch(/connection/i);
    expect($('dashboardTodoRetry').disabled).toBe(false);
    expect($('kpiApprovals').textContent).toBe('—');
  });

  it('treats a 403 as a permission message, and a non-array body as an error', async () => {
    let { loadDashboardTodos } = load(status(403));
    await loadDashboardTodos();
    expect($('dashboardTodoErrorMsg').textContent).toMatch(/access/i);
    ({ loadDashboardTodos } = load(ok({ detail: 'nope' })));
    await loadDashboardTodos();
    expect(hidden('dashboardTodoError')).toBe(false);
  });

  it('recovers: a successful retry clears the error', async () => {
    let calls = 0;
    const { loadDashboardTodos } = load(async () => (++calls === 1 ? { ok: false, status: 500 } : { ok: true, status: 200, json: async () => [approval()] }));
    await loadDashboardTodos();
    expect(hidden('dashboardTodoError')).toBe(false);
    await loadDashboardTodos();
    expect(hidden('dashboardTodoError')).toBe(true);
    expect(hidden('dashboardTodoBody')).toBe(false);
    expect($('kpiApprovals').textContent).toBe('1');
  });
});

describe('Home to-do card — empty state, count and KPI', () => {
  it('shows "all caught up" only for a genuinely empty, successful response', async () => {
    const { loadDashboardTodos } = load(ok([]));
    await loadDashboardTodos();
    expect(hidden('dashboardTodoEmpty')).toBe(false);
    expect(hidden('dashboardTodoError')).toBe(true);
    expect($('kpiApprovals').textContent).toBe('0');
    expect($('dashboardTodoCount').textContent).toBe('');
  });

  it('puts the item count in the heading and counts Pending approvals from kind, not label text', async () => {
    const items = [approval({ label: 'Reworded copy' }), approval({ key: 'x2' }), task(), task({ key: 'y' }), reminder()];
    const { loadDashboardTodos } = load(ok(items));
    await loadDashboardTodos();
    expect($('kpiApprovals').textContent).toBe('2');
    expect($('dashboardTodoCount').textContent).toBe('5 items');
  });

  it('hides the card entirely for a superadmin', async () => {
    const { loadDashboardTodos } = load(ok([approval()]), { role: 'superadmin' });
    await loadDashboardTodos();
    expect(hidden('dashboardTodoCard')).toBe(true);
  });
});

describe('Home to-do card — sections', () => {
  it('splits decisions, checklist tasks and reminders into their own labelled sections', async () => {
    const { loadDashboardTodos } = load(ok([reminder(), task(), approval()]));
    await loadDashboardTodos();
    const heads = [...body().querySelectorAll('h3.todo-subheading')].map(h => h.textContent);
    expect(heads).toEqual(['Needs your decision', 'Checklist tasks', 'Reminders']);
  });

  it('renders only the sections that have items', async () => {
    const { loadDashboardTodos } = load(ok([task()]));
    await loadDashboardTodos();
    expect([...body().querySelectorAll('h3.todo-subheading')].map(h => h.textContent)).toEqual(['Checklist tasks']);
  });

  it('shows only the stage in the Request column — no repeated employee or type', async () => {
    const { loadDashboardTodos } = load(ok([approval()]));
    await loadDashboardTodos();
    const cells = [...body().querySelectorAll('tbody tr td')];
    // the leading "Resignation — " is the Type column's job, and the ISO date is formatted like every other date
    expect(cells[0].textContent).toBe('Last day 10-Dec-26');
    expect(cells[0].textContent).not.toContain('Ng Say Li');
    expect(cells[0].textContent).not.toContain('awaiting your approval');
    expect(cells[1].textContent).toBe('Ng Say Li');
  });
});

describe('Home to-do card — approvals', () => {
  it('gives every approval a focusable button with a descriptive accessible name', async () => {
    const items = [approval(), approval({ key: 'a2', label: 'Leave — Raj', employee_name: 'Raj' })];
    const { loadDashboardTodos } = load(ok(items));
    await loadDashboardTodos();
    const rows = [...body().querySelectorAll('tbody tr')];
    expect(rows).toHaveLength(2);
    rows.forEach((row, i) => {
      const btn = row.querySelector('button[type="button"]');
      expect(btn.textContent).toBe('Review');
      expect(btn.getAttribute('aria-label')).not.toContain('awaiting your approval'); // not the long server label
      expect(btn.getAttribute('aria-label')).not.toMatch(/\d{4}-\d{2}-\d{2}/); // no ISO date read out digit by digit
    });
  });

  it('says "Waiting 17 days" for a deadline-less approval, never a red overdue', async () => {
    const { loadDashboardTodos } = load(ok([approval()]));
    await loadDashboardTodos();
    const row = body().querySelector('tbody tr');
    expect(row.textContent).toContain('Waiting 17 days');
    expect(row.querySelector('.todo-overdue')).toBeNull();
  });

  it('spells overdue out in words (with a hidden icon) so colour is never the only signal', async () => {
    const { loadDashboardTodos } = load(ok([approval({ due_date: '2026-09-25', days_overdue: 3 }), approval({ key: 'k', due_date: '2026-09-26', days_overdue: 1 })]));
    await loadDashboardTodos();
    const cells = [...body().querySelectorAll('.todo-overdue')];
    expect(cells[0].firstChild.nextSibling.textContent).toBe('Overdue 3 days');
    expect(cells[1].firstChild.nextSibling.textContent).toBe('Overdue 1 day');
    // the exact date is in text a screen reader gets, not only in a hover title
    expect(cells[0].querySelector('.sr-only-text').textContent).toBe(', due 25-Sep-26');
    expect(cells[0].querySelector('svg').getAttribute('aria-hidden')).toBe('true');
  });

  it('shows "Submitted today" for a same-day approval', async () => {
    const { loadDashboardTodos } = load(ok([approval({ days_waiting: 0 })]));
    await loadDashboardTodos();
    expect(body().textContent).toContain('Submitted today');
  });

  it('escapes hostile text and titles a long employee name for the clipped cell', async () => {
    const evil = '<img src=x onerror=alert(1)>';
    const long = 'Muhammad Aiman bin Abdul Rahman '.repeat(6).trim();
    const { loadDashboardTodos } = load(ok([approval({ stage: evil, label: evil, employee_name: long })]));
    await loadDashboardTodos();
    expect(body().querySelector('img')).toBeNull();
    expect(body().querySelector('.todo-cell-clip').getAttribute('title')).toBe(long);
  });

  it('keeps the row clickable for mouse users without the button double-firing', async () => {
    const { loadDashboardTodos } = load(ok([approval({ page: 'dash-leave' })]));
    await loadDashboardTodos();
    const row = body().querySelector('tbody tr');
    expect(row.getAttribute('onclick')).toBe("showPage('dashboard');switchDashTab('dash-leave')");
    expect(row.querySelector('button').getAttribute('onclick')).toMatch(/^event\.stopPropagation\(\);/);
  });
});

describe('Home to-do card — checklist groups', () => {
  const yahya = (o = {}) => task({ checklist_id: 7, employee_name: 'Yahya', ...o });
  const cheng = (o = {}) => task({ checklist_id: 8, employee_name: 'Cheng Kar Yan', employee_id: 'E3', event_date: '2026-11-30', days_until_event: 63, checklist_open: 2, checklist_total: 5, ...o });

  it('collapses six items across three people into three collapsed groups', async () => {
    const items = [yahya({ key: 'a' }), yahya({ key: 'b' }), cheng({ key: 'c' }), cheng({ key: 'd' }),
                   task({ key: 'e', checklist_id: 9, employee_name: 'Nasrollah', event_date: null, days_until_event: null }),
                   task({ key: 'f', checklist_id: 9, employee_name: 'Nasrollah', event_date: null, days_until_event: null })];
    const { loadDashboardTodos } = load(ok(items));
    await loadDashboardTodos();
    const groups = body().querySelectorAll('.todo-group');
    expect(groups).toHaveLength(3);
    groups.forEach(g => {
      expect(g.querySelector('.todo-group-toggle').getAttribute('aria-expanded')).toBe('false');
      expect(g.querySelector('.todo-group-items').hidden).toBe(true);
    });
  });

  it('names both scopes: "2 assigned to you · 3 of 5 open", and "Leaves … · in 14 days"', async () => {
    const { loadDashboardTodos } = load(ok([yahya({ key: 'a', checklist_open: 3 }), yahya({ key: 'b', checklist_open: 3 })]));
    await loadDashboardTodos();
    const text = body().querySelector('.todo-group-toggle').textContent.replace(/\s+/g, ' ');
    expect(text).toContain('Yahya');
    expect(text).toContain('Offboarding · 2 assigned to you · 3 of 5 open');
    expect(text).toContain('Leaves 12-Oct-26 · in 14 days');
  });

  it('says "Left" once the last working day has passed, and "today" on the day', async () => {
    let { loadDashboardTodos } = load(ok([yahya({ event_date: '2026-09-20', days_until_event: -8 })]));
    await loadDashboardTodos();
    expect(body().textContent).toContain('Left 20-Sep-26');
    ({ loadDashboardTodos } = load(ok([yahya({ event_date: '2026-09-28', days_until_event: 0 })])));
    body().innerHTML = '';
    await loadDashboardTodos();
    expect(body().textContent).toContain('Leaves 28-Sep-26 · today');
  });

  it('titles a person\'s own checklist "Your onboarding" instead of naming them', async () => {
    const mine = task({ employee_id: 'E-ME', employee_name: 'Kenneth', stage_type: 'Onboarding', event_date: null, days_until_event: null });
    const { loadDashboardTodos } = load(ok([mine]));
    await loadDashboardTodos();
    expect(body().querySelector('.todo-group-name').textContent).toBe('Your onboarding');
  });

  it('orders groups: overdue first, then the person leaving soonest', async () => {
    const items = [cheng({ key: 'c' }), yahya({ key: 'a' }),
                   task({ key: 'z', checklist_id: 11, employee_name: 'Zed', event_date: '2026-12-31', days_until_event: 94, due_date: '2026-09-20', days_overdue: 8 })];
    const { loadDashboardTodos } = load(ok(items));
    await loadDashboardTodos();
    const names = [...body().querySelectorAll('.todo-group-name')].map(n => n.textContent);
    expect(names).toEqual(['Zed', 'Yahya', 'Cheng Kar Yan']);
    expect(body().querySelector('.todo-group .todo-overdue').textContent).toBe('1 overdue');
  });

  it('expands with the toggle (aria-expanded + hidden in sync) and stays open across a refresh', async () => {
    const { loadDashboardTodos } = load(ok([yahya({ key: 'a', stage: 'Exit Interview' }), yahya({ key: 'b', stage: 'Return laptop', due_date: '2026-10-05' })]));
    await loadDashboardTodos();
    const btn = () => body().querySelector('.todo-group-toggle');
    btn().click();
    // a checklist item without a due date shows no "—" placeholder
    expect(body().querySelector('.todo-group-items li:first-child').textContent).toBe('Exit Interview');
    expect(btn().getAttribute('aria-expanded')).toBe('true');
    expect(body().querySelector('.todo-group-items').hidden).toBe(false);
    expect(body().querySelector('.todo-group-items').textContent).toContain('Return laptop');
    expect(body().querySelector('.todo-group-items').textContent).toContain('Due 05-Oct-26');
    await loadDashboardTodos(); // re-render
    expect(btn().getAttribute('aria-expanded')).toBe('true');
    expect(body().querySelector('.todo-group-items').hidden).toBe(false);
    btn().click();
    expect(body().querySelector('.todo-group-items').hidden).toBe(true);
  });

  it('gives each group one real Open button (the items inside have none) that names the person', async () => {
    const { loadDashboardTodos } = load(ok([yahya({ key: 'a' }), yahya({ key: 'b' })]));
    await loadDashboardTodos();
    const g = body().querySelector('.todo-group');
    expect(g.querySelectorAll('.todo-group-items button')).toHaveLength(0);
    const open = g.querySelector('.todo-group-head > button.todo-action');
    expect(open.textContent).toBe('Open');
    expect(open.getAttribute('aria-label')).toBe("Open Yahya's offboarding checklist");
  });

  it('escapes a hostile employee name in the group header and its aria-label', async () => {
    const { loadDashboardTodos } = load(ok([yahya({ employee_name: '<img src=x onerror=alert(1)>' })]));
    await loadDashboardTodos();
    expect(body().querySelector('img')).toBeNull();
  });
});

describe('Home to-do card — reminders and the single highlight', () => {
  it('renders reminders as a sentence plus an Open button', async () => {
    const { loadDashboardTodos } = load(ok([reminder()]));
    await loadDashboardTodos();
    const li = body().querySelector('.todo-reminders li');
    expect(li.textContent).toContain('2 training courses in progress');
    expect(li.querySelector('button').getAttribute('onclick')).toContain("showPage('ld-trainings')");
  });

  it('highlights exactly one thing: the first approval when there is one', async () => {
    const { loadDashboardTodos } = load(ok([approval({ key: 'a1' }), approval({ key: 'a2' }), task(), reminder()]));
    await loadDashboardTodos();
    expect(body().querySelectorAll('.todo-row-urgent')).toHaveLength(1);
    expect(body().querySelector('.todo-row-urgent').textContent).toContain('Ng Say Li');
    expect(body().querySelectorAll('.todo-action-primary')).toHaveLength(1);
  });

  it('with no approvals, the top checklist group is the highlight; with only reminders, the first reminder', async () => {
    let { loadDashboardTodos } = load(ok([task(), reminder()]));
    await loadDashboardTodos();
    expect(body().querySelector('.todo-row-urgent').classList.contains('todo-group')).toBe(true);
    expect(body().querySelectorAll('.todo-row-urgent')).toHaveLength(1);

    ({ loadDashboardTodos } = load(ok([reminder(), reminder({ key: 'r2' })])));
    body().innerHTML = '';
    await loadDashboardTodos();
    expect(body().querySelectorAll('.todo-action-primary')).toHaveLength(1);
  });
});

describe('Home to-do card — concurrency', () => {
  it('drops a slow, stale response instead of overwriting the newer one', async () => {
    let releaseFirst;
    const first = new Promise(r => { releaseFirst = r; });
    let n = 0;
    const api = () => (++n === 1 ? first : Promise.resolve({ ok: true, status: 200, json: async () => [reminder({ label: 'NEW' })] }));
    const { loadDashboardTodos } = load(api);
    const p1 = loadDashboardTodos();
    await loadDashboardTodos(); // second call resolves first and renders NEW
    releaseFirst({ ok: true, status: 200, json: async () => [reminder({ label: 'STALE' })] });
    await p1;
    expect(body().textContent).toContain('NEW');
    expect(body().textContent).not.toContain('STALE');
  });

  it('shows a skeleton while the first load is in flight and disables Retry until it settles', async () => {
    let release;
    const gate = new Promise(r => { release = r; });
    const { loadDashboardTodos } = load(() => gate);
    const p = loadDashboardTodos();
    expect(body().querySelectorAll('.todo-skeleton').length).toBeGreaterThan(0);
    expect(body().getAttribute('aria-busy')).toBe('true');
    expect($('dashboardTodoRetry').disabled).toBe(true);
    release({ ok: true, status: 200, json: async () => [] });
    await p;
    expect($('dashboardTodoRetry').disabled).toBe(false);
    expect(body().querySelectorAll('.todo-skeleton')).toHaveLength(0);
  });
});


describe('Home KPI tiles as shortcuts', () => {
  function tilesDom({ visible = ['employees', 'payroll-runs', 'requisitions'], hiddenGroup = false } = {}) {
    const navItems = visible.map(p => `<div data-page="${p}"></div>`).join('');
    document.body.insertAdjacentHTML('beforeend', `
      <div id="submenu-x" class="hidden">${navItems}</div>
      <div id="dashKpiRow">
        <div class="kpi-tile" data-kpi-target="employees" data-kpi-title="View the employee list"><p>Headcount</p></div>
        <div class="kpi-tile kpi-tile-accent" data-kpi-target="decisions" data-kpi-title="Jump to what needs your decision"><p>Pending approvals</p></div>
        <div class="kpi-tile" data-kpi-target="payroll-runs" data-kpi-title="Open payroll runs"><p>Pay day</p></div>
        <div class="kpi-tile" data-kpi-target="requisitions" data-kpi-title="Open job requisitions"><p>Open roles</p></div>
      </div>
      <button data-dashtab="dash-general" class="pill-tab"></button>
      <div id="dash-general" class="dash-tab-panel"></div>`);
    if (hiddenGroup) document.querySelector('[data-page="payroll-runs"]').classList.add('hidden');
    return [...document.querySelectorAll('#dashKpiRow .kpi-tile')];
  }

  it('links every tile whose page is in the sidebar (a collapsed sidebar group does not count as hidden)', () => {
    const tiles = tilesDom();
    load(ok([])).wireDashboardKpiTiles();
    tiles.forEach(t => {
      expect(t.classList.contains('kpi-tile-link')).toBe(true);
      expect(t.getAttribute('role')).toBe('link');
      expect(t.getAttribute('tabindex')).toBe('0');
      expect(t.querySelectorAll('.kpi-tile-arrow')).toHaveLength(1);
    });
    expect(tiles[0].getAttribute('title')).toBe('View the employee list');
  });

  it('leaves a tile plain when this role cannot see its page (role-hidden item, or item missing)', () => {
    const tiles = tilesDom({ visible: ['employees', 'payroll-runs'], hiddenGroup: true }); // no requisitions, payroll hidden
    load(ok([])).wireDashboardKpiTiles();
    const [headcount, approvals, payday, roles] = tiles;
    expect(headcount.classList.contains('kpi-tile-link')).toBe(true);
    expect(approvals.classList.contains('kpi-tile-link')).toBe(true); // always: same page
    for (const t of [payday, roles]) {
      expect(t.classList.contains('kpi-tile-link')).toBe(false);
      expect(t.hasAttribute('role')).toBe(false);
      expect(t.hasAttribute('tabindex')).toBe(false);
      expect(t.querySelector('.kpi-tile-arrow')).toBeNull();
    }
  });

  it('opens the tile\'s page on click and on Enter, but not on other keys or an unlinked tile', () => {
    const tiles = tilesDom({ visible: ['employees'] });
    load(ok([])).wireDashboardKpiTiles();
    tiles[0].click();
    tiles[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    tiles[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    tiles[2].click(); // payroll-runs: not visible to this role
    expect(shown).toEqual(['employees', 'employees']);
  });

  it('is safe to re-run on a role switch: handlers bind once and the arrow is not duplicated', () => {
    const tiles = tilesDom();
    const { wireDashboardKpiTiles } = load(ok([]));
    wireDashboardKpiTiles(); wireDashboardKpiTiles();
    tiles[0].click();
    expect(shown).toEqual(['employees']);
    expect(tiles[0].querySelectorAll('.kpi-tile-arrow')).toHaveLength(1);
  });

  it('Pending approvals switches to the General tab and moves focus to the decisions section', async () => {
    Element.prototype.scrollIntoView = () => {};
    const { loadDashboardTodos, wireDashboardKpiTiles } = load(ok([approval()]));
    await loadDashboardTodos();
    const tiles = tilesDom();
    wireDashboardKpiTiles();
    tiles[1].click();
    const target = document.getElementById('todo-decisions');
    expect(target.getAttribute('tabindex')).toBe('-1');
    expect(document.activeElement).toBe(target);
    expect(document.querySelector('[data-dashtab="dash-general"]').classList.contains('pill-tab-active')).toBe(true);
  });

  it('with nothing to decide, Pending approvals lands on the to-do heading instead', () => {
    Element.prototype.scrollIntoView = () => {};
    document.body.insertAdjacentHTML('beforeend', '<div id="dashboardTodoCard"><h2 tabindex="-1">Your to-do</h2></div>');
    const tiles = tilesDom();
    load(ok([])).wireDashboardKpiTiles();
    tiles[1].click();
    expect(document.activeElement.textContent).toBe('Your to-do');
  });
});


describe('Home to-do card — screen-reader announcements', () => {
  const live = () => $('dashboardTodoLive').textContent;

  it('announces the count and how many need a decision', async () => {
    const { loadDashboardTodos } = load(ok([approval(), approval({ key: 'a2' }), task()]));
    await loadDashboardTodos();
    expect(live()).toBe('3 items on your to-do list, 2 waiting for your decision.');
  });

  it('announces a singular count without a decision clause when nothing needs deciding', async () => {
    const { loadDashboardTodos } = load(ok([reminder()]));
    await loadDashboardTodos();
    expect(live()).toBe('1 item on your to-do list.');
  });

  it('announces "all caught up" for an empty list, and clears the announcement on error', async () => {
    let { loadDashboardTodos } = load(ok([]));
    await loadDashboardTodos();
    expect(live()).toMatch(/all caught up/i);
    ({ loadDashboardTodos } = load(status(500)));
    await loadDashboardTodos();
    expect(live()).toBe(''); // the error block is role="alert" and speaks for itself
  });
});


describe('Home to-do card — the single highlight follows what is actually late', () => {
  const leaveOverdue = (o = {}) => approval({ key: 'leave-1', stage: 'Annual Leave: 2026-09-25 to 2026-09-29', stage_type: 'Leave',
    employee_name: 'Aiman', due_date: '2026-09-25', days_overdue: 3, waiting_since: '2026-09-20', days_waiting: 8, ...o });
  const urgentText = () => body().querySelector('.todo-row-urgent')?.textContent || '';

  it('an overdue leave request beats an older approval that has no deadline', async () => {
    // server order puts the 17-day resignation first; the highlight must still go to the late leave
    const { loadDashboardTodos } = load(ok([approval(), leaveOverdue()]));
    await loadDashboardTodos();
    expect(body().querySelectorAll('.todo-row-urgent')).toHaveLength(1);
    expect(urgentText()).toContain('Aiman');
    expect(urgentText()).not.toContain('Ng Say Li');
  });

  it('an overdue checklist item beats an approval that is merely waiting', async () => {
    const late = task({ key: 'late', due_date: '2026-09-26', days_overdue: 2 });
    const { loadDashboardTodos } = load(ok([approval(), late]));
    await loadDashboardTodos();
    const urgent = body().querySelector('.todo-row-urgent');
    expect(urgent.classList.contains('todo-group')).toBe(true);
    expect(body().querySelector('tbody tr').classList.contains('todo-row-urgent')).toBe(false);
    expect(body().querySelectorAll('.todo-action-primary')).toHaveLength(1);
  });

  it('the most overdue item wins across kinds, and an approval wins a tie', async () => {
    const { loadDashboardTodos } = load(ok([leaveOverdue({ days_overdue: 3 }), task({ key: 't9', due_date: '2026-09-19', days_overdue: 9 })]));
    await loadDashboardTodos();
    expect(body().querySelector('.todo-row-urgent').classList.contains('todo-group')).toBe(true);

    document.getElementById('dashboardTodoBody').innerHTML = '';
    const again = load(ok([task({ key: 't3', due_date: '2026-09-25', days_overdue: 3 }), leaveOverdue({ days_overdue: 3 })]));
    await again.loadDashboardTodos();
    expect(urgentText()).toContain('Aiman'); // tie -> the approval
  });

  it('orders checklist groups by how far past a deadline each is', async () => {
    const items = [
      task({ key: 'a', checklist_id: 1, employee_name: 'Yahya', due_date: '2026-09-26', days_overdue: 2 }),
      task({ key: 'b', checklist_id: 2, employee_name: 'Cheng Kar Yan', due_date: '2026-09-19', days_overdue: 9 }),
    ];
    const { loadDashboardTodos } = load(ok(items));
    await loadDashboardTodos();
    expect([...body().querySelectorAll('.todo-group-name')].map(n => n.textContent)).toEqual(['Cheng Kar Yan', 'Yahya']);
  });
});

describe('Home to-do card — plain, consistent copy', () => {
  it('formats every ISO date inside stage text like the rest of Home', async () => {
    const { loadDashboardTodos } = load(ok([approval({ stage: 'Annual Leave: 2026-10-05 to 2026-10-09', stage_type: 'Leave' })]));
    await loadDashboardTodos();
    const cell = body().querySelector('tbody tr td').textContent;
    expect(cell).toBe('Annual Leave: 05-Oct-26 to 09-Oct-26');
    expect(body().textContent).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });

  it('only strips a leading type that the Type column repeats — and leaves other stages intact', async () => {
    const items = [approval(), approval({ key: 'w', stage: 'Week of 2026-09-21', stage_type: 'Timesheet' }),
                   approval({ key: 'c', stage: 'Dental claim — RM 120.00', stage_type: 'Benefit Claim' })];
    const { loadDashboardTodos } = load(ok(items));
    await loadDashboardTodos();
    const stages = [...body().querySelectorAll('tbody tr')].map(r => r.querySelector('td').textContent);
    expect(stages).toEqual(['Last day 10-Dec-26', 'Week of 21-Sep-26', 'Dental claim — RM 120.00']);
  });

  it('a reminder button says where it goes when the server says so, and falls back to Open', async () => {
    const { loadDashboardTodos } = load(ok([reminder({ key: 'docs', label: '3 employee documents expiring soon', page: 'dash-leave', action_label: 'View calendar' }), reminder()]));
    await loadDashboardTodos();
    const btns = [...body().querySelectorAll('.todo-reminders button')];
    expect(btns.map(b => b.textContent)).toEqual(['View calendar', 'Open']);
    expect(btns[0].getAttribute('aria-label')).toBe('View calendar: 3 employee documents expiring soon');
  });

  it('keeps the exact waiting date reachable without a hover: screen-reader text plus the title', async () => {
    const { loadDashboardTodos } = load(ok([approval()]));
    await loadDashboardTodos();
    const t = body().querySelector('tbody .todo-timing');
    expect(t.getAttribute('title')).toBe('Submitted 11-Sep-26');
    expect(t.querySelector('.sr-only-text').textContent).toBe(', submitted 11-Sep-26');
  });
});


describe('Home tab bar — ARIA tabs keyboard support', () => {
  function tabsDom({ hiddenTabs = [] } = {}) {
    const ids = ['general', 'workforce', 'recruitment', 'timesheet'];
    document.body.insertAdjacentHTML('beforeend', `
      <div id="tablist" role="tablist">
        ${ids.map(t => `<button id="dash-tab-${t}-btn" role="tab" data-dashtab="dash-${t}" class="pill-tab ${hiddenTabs.includes(t) ? 'hidden' : ''}"></button>`).join('')}
      </div>
      ${ids.map(t => `<div id="dash-${t}" class="dash-tab-panel" role="tabpanel"></div>`).join('')}`);
    return Object.fromEntries(ids.map(t => [t, document.getElementById(`dash-tab-${t}-btn`)]));
  }
  const press = (api, key) => {
    const e = { key, currentTarget: document.getElementById('tablist'), prevented: false, preventDefault() { this.prevented = true; } };
    api.dashTabKeydown(e);
    return e;
  };

  it('leaves exactly one tab stop — the selected tab — via roving tabindex', () => {
    const tabs = tabsDom();
    const api = load(ok([]));
    api.switchDashTab('dash-workforce');
    expect(Object.values(tabs).map(t => t.getAttribute('tabindex'))).toEqual(['-1', '0', '-1', '-1']);
    expect(tabs.workforce.getAttribute('aria-selected')).toBe('true');
    expect(tabs.general.getAttribute('aria-selected')).toBe('false');
  });

  it('ArrowRight/ArrowLeft move focus (wrapping) without switching the panel; Home/End jump', () => {
    const tabs = tabsDom();
    const api = load(ok([]));
    api.switchDashTab('dash-general');
    tabs.general.focus();
    expect(press(api, 'ArrowRight').prevented).toBe(true);
    expect(document.activeElement).toBe(tabs.workforce);
    expect(tabs.general.getAttribute('aria-selected')).toBe('true'); // focus moved, nothing activated (tabs lazy-load)
    press(api, 'End');
    expect(document.activeElement).toBe(tabs.timesheet);
    press(api, 'ArrowRight'); // wraps to the first
    expect(document.activeElement).toBe(tabs.general);
    press(api, 'ArrowLeft'); // wraps to the last
    expect(document.activeElement).toBe(tabs.timesheet);
    press(api, 'Home');
    expect(document.activeElement).toBe(tabs.general);
  });

  it('skips tabs this role cannot see, and ignores other keys and other focus', () => {
    const tabs = tabsDom({ hiddenTabs: ['recruitment'] });
    const api = load(ok([]));
    tabs.workforce.focus();
    press(api, 'ArrowRight');
    expect(document.activeElement).toBe(tabs.timesheet); // recruitment is hidden
    expect(press(api, 'a').prevented).toBe(false);
    document.activeElement.blur();
    expect(press(api, 'ArrowRight').prevented).toBe(false); // focus isn't on a tab
  });
});

describe('Home markup — tab semantics', () => {
  const html = readFileSync(resolve(__dirname, '../../index.html'), 'utf8');

  it('every home tabpanel is labelled by an existing tab, and every tab controls an existing panel', () => {
    const panels = [...html.matchAll(/<div id="(dash-[a-z]+)" class="dash-tab-panel[^"]*" role="tabpanel" aria-labelledby="([^"]+)"/g)];
    expect(panels.length).toBe(6);
    for (const [, panelId, labelledby] of panels) {
      expect(html).toContain(`id="${labelledby}"`);
      expect(html).toContain(`aria-controls="${panelId}"`);
    }
  });

  it('labels the Home headcount tile for what it counts', () => {
    expect(html).toContain('<p class="kpi-tile-label">Active headcount</p>');
  });
});


describe('Home links deep-link to the exact record', () => {
  const rowNav = () => body().querySelector('tbody tr').getAttribute('onclick');

  it('an approval row and its button open that record (focus_id), not just the list', async () => {
    const { loadDashboardTodos } = load(ok([approval({ page: 'leave-approvals', focus_id: 4021 })]));
    await loadDashboardTodos();
    expect(rowNav()).toBe("showPage('leave-approvals',{focus:4021})");
    expect(body().querySelector('tbody .todo-action').getAttribute('onclick')).toContain("showPage('leave-approvals',{focus:4021})");
  });

  it('a split timesheet/overtime row links to the parent timesheet the server resolved', async () => {
    const { loadDashboardTodos } = load(ok([approval({ page: 'timesheet-approvals', ref_id: 901, focus_id: 40 })]));
    await loadDashboardTodos();
    expect(rowNav()).toBe("showPage('timesheet-approvals',{focus:40})"); // 40, not the child 901
  });

  it('a checklist group opens its checklist', async () => {
    const { loadDashboardTodos } = load(ok([task({ checklist_id: 77 })]));
    await loadDashboardTodos();
    expect(body().querySelector('.todo-group-head > button.todo-action').getAttribute('onclick')).toContain("showPage('offboarding',{focus:77})");
  });

  it('falls back to the plain page when there is no usable id, and never injects a non-numeric one', async () => {
    const items = [approval({ key: 'a', focus_id: null }), approval({ key: 'b', focus_id: undefined }),
                   approval({ key: 'c', focus_id: "1});alert(1);//" }), approval({ key: 'd', focus_id: 1.5 })];
    const { loadDashboardTodos } = load(ok(items));
    await loadDashboardTodos();
    for (const tr of body().querySelectorAll('tbody tr')) {
      expect(tr.getAttribute('onclick')).toBe("showPage('resignation-approvals')");
    }
  });

  it('a Dashboard sub-tab link and a reminder stay exactly as they were', async () => {
    const { loadDashboardTodos } = load(ok([reminder({ page: 'dash-leave', focus_id: 5 }), reminder({ key: 'r2', page: 'ld-trainings' })]));
    await loadDashboardTodos();
    const navs = [...body().querySelectorAll('.todo-reminders button')].map(b => b.getAttribute('onclick'));
    expect(navs[0]).toContain("showPage('dashboard');switchDashTab('dash-leave')");
    expect(navs[1]).toContain("showPage('ld-trainings')");
    expect(navs[1]).not.toContain('focus');
  });
});

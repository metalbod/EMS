import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL list-views.js with a stubbed signed-in user, esc and notify.
const src = readFileSync(resolve(__dirname, '..', 'list-views.js'), 'utf8');
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const notes = [];
const L = new Function('currentUser', 'esc', 'notify', `${src}\nreturn { listViewsLoad, listViewsStore, listViewsAdd, listViewsSameState, listViewsChipsHtml, csvCell, csvText, listViewsKey, listViewsRegister, lvSave, lvStartSave, listViewsRender, lvApply, lvDelete };`)({ id: 7 }, esc, m => notes.push(m));

beforeEach(() => { localStorage.clear(); document.body.innerHTML = ''; notes.length = 0; });

describe('saved views storage', () => {
  it('is keyed by user and list, and survives a round trip', () => {
    expect(L.listViewsKey('employees')).toBe('listViews:7:employees');
    expect(L.listViewsLoad('employees')).toEqual([]);
    L.listViewsStore('employees', [{ name: 'IT only', state: { department: 'IT' } }]);
    expect(L.listViewsLoad('employees')).toEqual([{ name: 'IT only', state: { department: 'IT' } }]);
    expect(L.listViewsLoad('candidates')).toEqual([]);
  });

  it('ignores corrupt or malformed stored data instead of throwing', () => {
    localStorage.setItem('listViews:7:employees', '{not json');
    expect(L.listViewsLoad('employees')).toEqual([]);
    localStorage.setItem('listViews:7:employees', JSON.stringify([{ name: 5 }, null, { name: 'ok', state: { a: 1 } }, { name: 'x' }]));
    expect(L.listViewsLoad('employees')).toEqual([{ name: 'ok', state: { a: 1 } }]);
  });

  it('adds a view, replaces one with the same name (any case), trims and caps names, keeps the newest 12', () => {
    let v = L.listViewsAdd([], '  Sales team  ', { department: 'Sales' });
    expect(v).toEqual([{ name: 'Sales team', state: { department: 'Sales' } }]);
    v = L.listViewsAdd(v, 'sales TEAM', { department: 'Sales', status: '' });
    expect(v).toHaveLength(1);
    expect(v[0].state.status).toBe('');
    expect(L.listViewsAdd(v, '   ', {})).toBe(v);
    expect(L.listViewsAdd([], 'x'.repeat(80), {})[0].name).toHaveLength(40);
    let many = []; for (let i = 0; i < 15; i++) many = L.listViewsAdd(many, `v${i}`, { i });
    expect(many).toHaveLength(12);
    expect(many[11].name).toBe('v14');
  });

  it('a blocked localStorage does not throw', () => {
    const real = Storage.prototype.setItem;
    Storage.prototype.setItem = () => { throw new Error('blocked'); };
    expect(L.listViewsStore('employees', [])).toBe(false);
    Storage.prototype.setItem = real;
  });
});

describe('comparing filter states', () => {
  it('treats arrays as sets and blank as missing', () => {
    expect(L.listViewsSameState({ stages: ['B', 'A'], search: '' }, { stages: ['A', 'B'] })).toBe(true);
    expect(L.listViewsSameState({ status: 'Active', ending: '' }, { status: 'Active' })).toBe(true);
    expect(L.listViewsSameState({ status: 'Active' }, { status: '' })).toBe(false);
    expect(L.listViewsSameState({ stages: ['A'] }, { stages: ['A', 'B'] })).toBe(false);
  });
});

describe('view chips', () => {
  const builtins = [{ label: 'Active', state: { status: 'Active' } }, { label: 'Everyone', state: { status: '' } }];

  it('lights the chip matching the current filters and offers saving only when none matches', () => {
    const html = L.listViewsChipsHtml('employees', builtins, [], { status: 'Active' });
    expect(html).toContain('lv-chip-active');
    expect(html).not.toContain('Save this view');
    const custom = L.listViewsChipsHtml('employees', builtins, [], { status: 'Inactive', department: 'IT' });
    expect(custom).not.toContain('lv-chip-active');
    expect(custom).toContain('+ Save this view');
  });

  it('escapes names, and saved views get a delete button', () => {
    const html = L.listViewsChipsHtml('employees', builtins, [{ name: '<img src=x onerror=alert(1)>', state: { department: 'IT' } }], { status: 'Active' });
    expect(html).not.toContain('<img');
    expect(html).toContain('lvDelete(');
  });
});

describe('applying, saving and deleting through the page', () => {
  it('saves the current filters under a name and re-applies them later', () => {
    document.body.innerHTML = '<div id="host"></div>';
    let state = { status: 'Inactive', department: 'IT' };
    const applied = [];
    L.listViewsRegister('employees', { hostId: 'host', builtins: [{ label: 'Active', state: { status: 'Active' } }], getState: () => state, applyState: s => { applied.push(s); state = s; } });
    L.lvStartSave('employees');
    document.getElementById('lvName-employees').value = 'Old IT';
    L.lvSave('employees');
    expect(L.listViewsLoad('employees')).toEqual([{ name: 'Old IT', state: { status: 'Inactive', department: 'IT' } }]);
    L.lvApply('employees', 'b', 0);
    expect(applied.at(-1)).toEqual({ status: 'Active' });
    L.lvApply('employees', 's', 0);
    expect(applied.at(-1)).toEqual({ status: 'Inactive', department: 'IT' });
    L.lvDelete('employees', 0);
    expect(L.listViewsLoad('employees')).toEqual([]);
  });

  it('refuses an empty name and says so when storage is blocked', () => {
    document.body.innerHTML = '<div id="host"></div>';
    L.listViewsRegister('employees', { hostId: 'host', builtins: [], getState: () => ({ a: 1 }), applyState: () => {} });
    L.lvStartSave('employees');
    L.lvSave('employees');
    expect(L.listViewsLoad('employees')).toEqual([]);
    document.getElementById('lvName-employees').value = 'X';
    const real = Storage.prototype.setItem;
    Storage.prototype.setItem = () => { throw new Error('blocked'); };
    L.lvSave('employees');
    Storage.prototype.setItem = real;
    expect(notes[0]).toContain("won't let EMS keep saved views");
  });
});

describe('CSV', () => {
  it('quotes commas, quotes and newlines, and defuses spreadsheet formulas', () => {
    expect(L.csvCell('a,b')).toBe('"a,b"');
    expect(L.csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(L.csvCell('=SUM(A1)')).toBe("'=SUM(A1)");
    expect(L.csvCell('+60123')).toBe("'+60123");
    expect(L.csvCell('@x')).toBe("'@x");
    expect(L.csvCell(null)).toBe('');
    expect(L.csvCell(0)).toBe('0');
  });

  it('builds CRLF-separated rows with a header', () => {
    expect(L.csvText(['Name', 'Dept'], [['Aisyah', 'IT'], ['Lim, Wei', '']])).toBe('Name,Dept\r\nAisyah,IT\r\n"Lim, Wei",\r\n');
  });
});

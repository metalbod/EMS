// ---------------------------------------------------------------------------
// Saved views for long lists (Directory, Candidates) + CSV export
// ---------------------------------------------------------------------------
// A "view" is a name for a set of filters. Each list registers where its filters live
// (getState / applyState — one reads the page's own controls, the other writes them and
// reloads) and a few built-in views; people add their own with "Save this view". Saved
// views are a per-person, per-browser convenience (localStorage, keyed by user and list),
// not shared data — nothing leaves the browser and a cleared browser just starts with the
// built-ins again. Every read and write is wrapped: storage can be blocked or full.
//
// Depends on core.js (currentUser, esc). Plain global-scope script.

const LIST_VIEW_CFG = {};   // listId -> { hostId, builtins:[{key,label,state}], getState(), applyState(state) }
const _lvSaving = {};       // listId -> true while the inline "name this view" box is open

function listViewsKey(listId) {
  return `listViews:${currentUser?.id ?? currentUser?.username ?? 'anon'}:${listId}`;
}

function listViewsLoad(listId) {
  try {
    const v = JSON.parse(localStorage.getItem(listViewsKey(listId)) || '[]');
    return Array.isArray(v) ? v.filter(x => x && typeof x.name === 'string' && x.state && typeof x.state === 'object') : [];
  } catch (e) { return []; }
}

function listViewsStore(listId, views) {
  try { localStorage.setItem(listViewsKey(listId), JSON.stringify(views)); return true; } catch (e) { return false; }
}

// Saving a name that already exists replaces that view; names are trimmed and capped.
function listViewsAdd(views, name, state) {
  const clean = String(name || '').trim().slice(0, 40);
  if (!clean) return views;
  const rest = views.filter(v => v.name.toLowerCase() !== clean.toLowerCase());
  return [...rest, { name: clean, state }].slice(-12);
}

// Order-insensitive comparison of two filter states (arrays compare as sets; "" and missing are the same).
function listViewsSameState(a, b) {
  const norm = s => {
    const o = {};
    Object.keys(s || {}).sort().forEach(k => {
      const v = s[k];
      if (Array.isArray(v)) o[k] = [...v].map(String).sort();
      else if (v !== '' && v != null) o[k] = String(v);
    });
    return JSON.stringify(o);
  };
  return norm(a) === norm(b);
}

function listViewsChipsHtml(listId, builtins, saved, current) {
  const chip = (label, active, onclick, extra = '') =>
    `<span class="lv-chip${active ? ' lv-chip-active' : ''}"><button type="button" class="lv-chip-btn" aria-pressed="${active}" onclick="${onclick}">${esc(label)}</button>${extra}</span>`;
  const id = JSON.stringify(listId).replace(/"/g, '&quot;');
  const b = builtins.map((v, i) => chip(v.label, listViewsSameState(v.state, current), `lvApply(${id}, 'b', ${i})`)).join('');
  const s = saved.map((v, i) => chip(v.name, listViewsSameState(v.state, current), `lvApply(${id}, 's', ${i})`,
    `<button type="button" class="lv-chip-x" aria-label="Delete the view ${esc(v.name)}" title="Delete this view" onclick="lvDelete(${id}, ${i})">×</button>`)).join('');
  const matched = builtins.some(v => listViewsSameState(v.state, current)) || saved.some(v => listViewsSameState(v.state, current));
  const save = _lvSaving[listId]
    ? `<span class="lv-save"><input id="lvName-${esc(listId)}" class="inp lv-name" maxlength="40" placeholder="Name this view" aria-label="Name this view" onkeydown="if(event.key==='Enter'){event.preventDefault();lvSave(${id})}else if(event.key==='Escape'){lvCancelSave(${id})}"/>
        <button type="button" class="pill-btn pill-btn-primary" onclick="lvSave(${id})">Save</button><button type="button" class="pill-btn pill-btn-outline" onclick="lvCancelSave(${id})">Cancel</button></span>`
    : (matched ? '' : `<button type="button" class="lv-add" onclick="lvStartSave(${id})">+ Save this view</button>`);
  return `<div class="lv-row" role="group" aria-label="Views">${b}${s}${save}</div>`;
}

function listViewsRender(listId) {
  const cfg = LIST_VIEW_CFG[listId];
  const host = cfg && document.getElementById(cfg.hostId);
  if (!host) return;
  host.innerHTML = listViewsChipsHtml(listId, cfg.builtins, listViewsLoad(listId), cfg.getState());
  if (_lvSaving[listId]) document.getElementById(`lvName-${listId}`)?.focus();
}

function listViewsRegister(listId, cfg) {
  LIST_VIEW_CFG[listId] = cfg;
  listViewsRender(listId);
}

function lvApply(listId, kind, i) {
  const cfg = LIST_VIEW_CFG[listId];
  if (!cfg) return;
  const view = kind === 'b' ? cfg.builtins[i] : listViewsLoad(listId)[i];
  if (!view) return;
  _lvSaving[listId] = false;
  cfg.applyState(view.state);
  listViewsRender(listId);
}

function lvDelete(listId, i) {
  const views = listViewsLoad(listId);
  views.splice(i, 1);
  listViewsStore(listId, views);
  listViewsRender(listId);
}

function lvStartSave(listId) { _lvSaving[listId] = true; listViewsRender(listId); }
function lvCancelSave(listId) { _lvSaving[listId] = false; listViewsRender(listId); }
function lvSave(listId) {
  const cfg = LIST_VIEW_CFG[listId];
  const input = document.getElementById(`lvName-${listId}`);
  const name = (input?.value || '').trim();
  if (!cfg) return;
  if (!name) { input?.focus(); return; }
  if (!listViewsStore(listId, listViewsAdd(listViewsLoad(listId), name, cfg.getState()))) {
    notify("This browser won't let EMS keep saved views (storage is blocked or full).");
  }
  _lvSaving[listId] = false;
  listViewsRender(listId);
}

// ---- CSV export ---------------------------------------------------------------
// A cell starting with = + - or @ would be run as a formula by a spreadsheet; a leading apostrophe makes it text.
function csvCell(v) {
  let s = v == null ? '' : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function csvText(headers, rows) {
  return [headers, ...rows].map(r => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

function saveCsvFile(filename, text) {
  const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

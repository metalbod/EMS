// Searchable employee picker
// ---------------------------------------------------------------------------
// Turns a plain <select> full of employees into a searchable picker.
// Institutions can have 100+ employees, and every existing <select id="...">
// that lists them (Start Onboarding, Reports To, Approval Workflow's
// specific-employee step, L&D enrollment, Apply Leave on behalf of,
// Total Rewards, User Management's linked employee) forced scrolling
// through the whole roster to find one person.
//
// The <select> stays the real source of truth — same id, same .value, same
// onchange="..." attribute — this just hides it and layers a text input +
// filtered dropdown panel on top, reading directly from whatever <option>s
// are already sitting in the <select> at call time. That means:
//   - No changes needed to how any call site builds its options (some use
//     createElement/appendChild loops, some use innerHTML/map/join — both
//     keep working exactly as before).
//   - Pinned non-employee options (e.g. fReportsTo's "None (Top Level)" /
//     "⭐ Self (CEO / Top of Org)") just work — they're options too,
//     matched by their own label text like anyone else.
//   - Zero changes needed at any submit-time document.getElementById(id).value
//     read, anywhere — picking a result dispatches a real 'change' event on
//     the underlying <select>, so every existing onchange handler still fires.
//
// Call ONCE, right after a <select>'s options finish being (re)populated —
// idempotent, so it's safe to call unconditionally every time a modal opens
// or a page reloads its options, not just the first time.
// ---------------------------------------------------------------------------

function filterEmployeeOptions(options, query) {
  // options: array of {value, label}. Pure so it's unit-testable without a DOM.
  // Deliberately does NOT exclude blank-value options — some call sites
  // (e.g. fReportsTo) have a meaningful choice living at value="" (its
  // "None (Top Level)" option), indistinguishable from a plain "please
  // select…" placeholder by value alone. Showing every option (including
  // a placeholder row) when the query is empty is a minor, harmless
  // redundancy; correctly keeping "None (Top Level)" reachable by typing
  // "none" is worth that trade-off.
  const q = (query || '').trim().toLowerCase();
  return options.filter(o => o.label.toLowerCase().includes(q));
}

function initEmployeeSearchSelect(selectId, placeholder) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const inputClass = sel.className.split(/\s+/).filter(c => c && c !== 'hidden').join(' ');

  let wrap = document.getElementById(selectId + 'SearchWrap');
  if (!wrap) {
    // Visually hidden but NOT display:none — a couple of these <select>s
    // (e.g. approval-workflow.js's "specific employee" step picker) have
    // their own external code toggling the *select's own* 'hidden' class
    // to show/hide the whole field. Using inline styles here (instead of
    // also touching the 'hidden' class) leaves that class free for such
    // external toggling to keep working unmodified — a MutationObserver
    // below mirrors whatever it does onto the wrap.
    Object.assign(sel.style, { position: 'absolute', opacity: '0', width: '0', height: '0', overflow: 'hidden', pointerEvents: 'none' });
    wrap = document.createElement('div');
    wrap.id = selectId + 'SearchWrap';
    wrap.className = 'relative' + (sel.classList.contains('hidden') ? ' hidden' : '');
    sel.insertAdjacentElement('afterend', wrap);
    new MutationObserver(() => {
      wrap.classList.toggle('hidden', sel.classList.contains('hidden'));
    }).observe(sel, { attributes: true, attributeFilter: ['class'] });
    wrap.innerHTML = `
      <input type="text" id="${selectId}Search" class="${esc(inputClass)}" placeholder="${esc(placeholder || 'Search…')}" autocomplete="off"/>
      <div id="${selectId}Dropdown" class="hidden absolute z-20 mt-1 w-full max-h-60 overflow-y-auto bg-white border border-slate-200 rounded-lg shadow-lg"></div>
    `;
    const input = wrap.querySelector('input');
    const dropdown = wrap.querySelector('div');

    const render = (query) => {
      const options = [...sel.options].map(o => ({ value: o.value, label: o.textContent }));
      const rows = filterEmployeeOptions(options, query);
      dropdown.innerHTML = rows.length
        ? rows.map(o => `<div class="px-3 py-2 text-sm hover:bg-slate-50 cursor-pointer" data-v="${esc(o.value)}">${esc(o.label)}</div>`).join('')
        : `<div class="px-3 py-2 text-sm text-slate-400">No matches</div>`;
    };
    const pick = (value) => {
      const opt = [...sel.options].find(o => o.value === value);
      sel.value = value;
      input.value = opt ? opt.textContent : '';
      dropdown.classList.add('hidden');
      sel.dispatchEvent(new Event('change'));
    };

    input.addEventListener('input', () => { render(input.value); dropdown.classList.remove('hidden'); });
    // select() on focus: whatever's currently shown (a placeholder like
    // "Select employee…", or a previously-picked name) is fully selected,
    // so the user's first keystroke cleanly replaces it rather than
    // requiring a manual clear first — standard combobox behavior. Render
    // against an EMPTY query, not that pre-existing text — it's about to
    // be replaced, not a search the user actually typed, so filtering by
    // it (e.g. against the literal placeholder "Select employee…") would
    // wrongly show "No matches" the moment the field is focused.
    input.addEventListener('focus', () => { input.select(); render(''); dropdown.classList.remove('hidden'); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { dropdown.classList.add('hidden'); input.blur(); }
      if (e.key === 'Enter') {
        e.preventDefault();
        const first = dropdown.querySelector('[data-v]');
        if (first) pick(first.dataset.v);
      }
    });
    // mousedown (not click) fires before the input's blur event would
    // otherwise hide the dropdown first and swallow the click.
    dropdown.addEventListener('mousedown', (e) => {
      const row = e.target.closest('[data-v]');
      if (row) pick(row.dataset.v);
    });
    document.addEventListener('click', (e) => {
      if (!wrap.contains(e.target)) dropdown.classList.add('hidden');
    });
  }

  // Re-sync the visible text with whatever is actually selected — needed
  // both on first render and whenever a call site repopulates the
  // underlying <select>'s options (e.g. a modal reopened for a new record).
  // selectedIndex (not a value-truthiness check) so a legitimately
  // blank-valued option that's actually selected — e.g. fReportsTo's
  // "None (Top Level)", value="" — still displays its own label, distinct
  // from "nothing chosen yet" on a picker whose placeholder is also "".
  const input = wrap.querySelector('input');
  const current = sel.options[sel.selectedIndex];
  input.value = current ? current.textContent : '';
}

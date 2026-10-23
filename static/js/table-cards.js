// ---------------------------------------------------------------------------
// Tables that become cards on a phone
// ---------------------------------------------------------------------------
// A table with class "cards-on-phone" is laid out as one card per row below 640px
// (styles.css). Each cell then needs its column's name next to its value, which
// only the header row knows — so this copies each <th>'s text onto the cells of
// its column as data-label, and keeps doing so as the list re-renders (rows are
// rebuilt by many different render functions; none of them need to know). The
// first column is the card's title and an unlabelled (empty-header) column, like
// row actions, shows no label. Opt-in per table: wide, dense tables elsewhere keep
// scrolling sideways.
//
// Plain global-scope script; no dependencies.

function labelCardTable(table) {
  const heads = [...table.querySelectorAll('thead tr:last-child th')];
  if (!heads.length) return;
  const labels = heads.map(th => (th.textContent || '').replace(/[▲▼↑↓]/g, '').replace(/\s+/g, ' ').trim());
  table.querySelectorAll('tbody tr').forEach(tr => {
    const cells = [...tr.children].filter(c => c.tagName === 'TD');
    if (cells.length !== labels.length) return;               // a one-cell "Loading…" / "No results" row
    cells.forEach((td, i) => {
      const want = i === 0 ? '' : labels[i];
      if (want) { if (td.getAttribute('data-label') !== want) td.setAttribute('data-label', want); }
      else if (td.hasAttribute('data-label')) td.removeAttribute('data-label');
    });
  });
}

function labelAllCardTables(root = document) {
  root.querySelectorAll('table.cards-on-phone').forEach(labelCardTable);
}

(function watchCardTables() {
  if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return;
  let queued = false;
  const run = () => { queued = false; labelAllCardTables(); };
  new MutationObserver(muts => {
    // only row/cell rebuilds matter; our own attribute writes never re-trigger this (childList only)
    if (queued || !muts.some(m => m.target.closest && m.target.closest('table.cards-on-phone'))) return;
    queued = true;
    (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : setTimeout)(run);
  }).observe(document.body || document.documentElement, { childList: true, subtree: true });
  labelAllCardTables();
})();

// List State
// ---------------------------------------------------------------------------
// One deep module for "a sortable, paginated list" — the sort key/direction,
// page/pageSize, and the sort+paginate+render-bookkeeping logic used to live
// duplicated between employees.js (empSortKey/empSortDir/empPage/empPageSize)
// and institutions.js (instSortKey/...), with each file re-implementing its
// own setSort/setPageSize/pagePrev/pageNext/sortedX/updateXSortArrows.
//
// createListState() is the one implementation both files call through now.
// It owns sort/page state and the render-time work (sorting, clamping the
// page, updating sort arrows) but NOT the DOM row markup or data fetching —
// callers still own `renderEmpTable()`/`renderInstTable()` as the seam where
// their own row template lives; this module is what those functions delegate
// the bookkeeping to.
function createListState({ sortKey, sortDir = 'asc', pageSize = 10, sortValue }) {
  const state = { sortKey, sortDir, pageSize, page: 1 };
  const getValue = sortValue || ((item, key) => item[key]);

  function sorted(data) {
    const dir = state.sortDir === 'asc' ? 1 : -1;
    return [...data].sort((a, b) => {
      let av = getValue(a, state.sortKey);
      let bv = getValue(b, state.sortKey);
      if (typeof av === 'string') av = av.toLowerCase();
      if (typeof bv === 'string') bv = bv.toLowerCase();
      if (av == null) av = '';
      if (bv == null) bv = '';
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }

  return {
    get sortKey() { return state.sortKey; },
    get sortDir() { return state.sortDir; },
    get page() { return state.page; },
    get pageSize() { return state.pageSize; },

    setSort(key) {
      if (state.sortKey === key) state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      else { state.sortKey = key; state.sortDir = 'asc'; }
      state.page = 1;
    },
    setPageSize(size) {
      state.pageSize = parseInt(size) || 10;
      state.page = 1;
    },
    resetPage() { state.page = 1; },
    prevPage() { if (state.page > 1) state.page--; },
    nextPage(total) {
      const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
      if (state.page < totalPages) state.page++;
    },

    // Sorts `data`, clamps the current page if it fell off the end (e.g. a
    // filter shrank the data since the last render), and returns the current
    // page's slice plus the pagination metadata the caller's render function
    // needs to update its page-info text.
    view(data) {
      const sortedData = sorted(data);
      const totalPages = Math.max(1, Math.ceil(sortedData.length / state.pageSize));
      if (state.page > totalPages) state.page = totalPages;
      const start = (state.page - 1) * state.pageSize;
      return {
        pageItems: sortedData.slice(start, start + state.pageSize),
        start,
        total: sortedData.length,
        totalPages,
      };
    },

    updateSortArrows(selector) {
      document.querySelectorAll(selector).forEach(el => {
        const key = el.dataset.sortKey;
        el.textContent = key === state.sortKey ? (state.sortDir === 'asc' ? ' ▲' : ' ▼') : '';
      });
    },
  };
}

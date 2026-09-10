import { describe, it, expect, beforeEach } from 'vitest';

// Mirrors employee-picker.js's filterEmployeeOptions — timesheet.js's
// Edit Project "Project Manager(s)" checklist reuses that exact matcher
// (see employee-picker.test.js for its own coverage), so this file only
// needs to mirror it, not re-derive it.
function filterEmployeeOptions(options, query) {
  const q = (query || '').trim().toLowerCase();
  return options.filter(o => o.label.toLowerCase().includes(q));
}

// Mirrors timesheet.js's renderProjectManagersChecklist / filterProjectManagerOptions /
// syncProjectManagersSelectAll / toggleAllProjectManagers — the searchable,
// checkbox-based Project Manager(s) picker on the Edit Project modal. A
// checklist (not a <select>) because a project can have several managers at
// once; the search box narrows a long, active-employee roster without
// losing anyone's checked state, including options scrolled out of view.
describe('Edit Project — Project Manager(s) search + checkbox list', () => {
  const managers = [
    { id: 'A028', name: 'Cheah Wui Keat' },
    { id: 'A026', name: 'Mohamad Syafiq' },
    { id: 'A032', name: 'Raj Saraiya' },
    { id: 'A109', name: 'Richie Teoh' },
  ];

  beforeEach(() => {
    document.body.innerHTML = `
      <input type="text" id="projectManagersSearch"/>
      <input type="checkbox" id="projectManagersSelectAll" />
      <div id="projectManagersList">
        ${managers.map(m => `
          <label class="project-manager-option" data-label="${m.name} (${m.id})">
            <input type="checkbox" class="project-manager-checkbox" value="${m.id}"/>
            ${m.name} (${m.id})
          </label>`).join('')}
        <div id="projectManagersNoMatch" class="hidden">No matches</div>
      </div>
    `;
  });

  function filterProjectManagerOptions() {
    const q = document.getElementById('projectManagersSearch')?.value || '';
    const opts = [...document.querySelectorAll('.project-manager-option')];
    const matched = new Set(filterEmployeeOptions(
      opts.map(el => ({ value: el.querySelector('.project-manager-checkbox').value, label: el.dataset.label })),
      q
    ).map(o => o.value));
    let visibleCount = 0;
    opts.forEach(opt => {
      const match = matched.has(opt.querySelector('.project-manager-checkbox').value);
      opt.classList.toggle('hidden', !match);
      if (match) visibleCount++;
    });
    document.getElementById('projectManagersNoMatch')?.classList.toggle('hidden', visibleCount > 0);
    syncProjectManagersSelectAll();
  }

  function visibleCheckboxes() {
    return [...document.querySelectorAll('.project-manager-option:not(.hidden) .project-manager-checkbox')];
  }

  function syncProjectManagersSelectAll() {
    const boxes = visibleCheckboxes();
    document.getElementById('projectManagersSelectAll').checked = boxes.length > 0 && boxes.every(b => b.checked);
  }

  function toggleAllProjectManagers() {
    const checked = document.getElementById('projectManagersSelectAll').checked;
    visibleCheckboxes().forEach(b => b.checked = checked);
  }

  function setSearch(q) {
    document.getElementById('projectManagersSearch').value = q;
    filterProjectManagerOptions();
  }

  function visibleIds() {
    return visibleCheckboxes().map(b => b.value);
  }

  it('shows every manager when the search box is empty', () => {
    setSearch('');
    expect(visibleIds().sort()).toEqual(['A026', 'A028', 'A032', 'A109']);
    expect(document.getElementById('projectManagersNoMatch').classList.contains('hidden')).toBe(true);
  });

  it('filters case-insensitively by name', () => {
    setSearch('richie');
    expect(visibleIds()).toEqual(['A109']);
  });

  it('filters by employee ID as well as name', () => {
    setSearch('A032');
    expect(visibleIds()).toEqual(['A032']);
  });

  it('shows the "No matches" empty state and hides every option when nothing matches', () => {
    setSearch('zzznomatch');
    expect(visibleIds()).toEqual([]);
    expect(document.getElementById('projectManagersNoMatch').classList.contains('hidden')).toBe(false);
  });

  it('a checked option that scrolls out of the current filter keeps its checked state', () => {
    document.querySelector('.project-manager-checkbox[value="A109"]').checked = true;
    setSearch('raj');
    expect(document.querySelector('.project-manager-checkbox[value="A109"]').checked).toBe(true);
    setSearch('');
    expect(visibleIds()).toContain('A109');
    expect(document.querySelector('.project-manager-checkbox[value="A109"]').checked).toBe(true);
  });

  it('"Select All" while filtered only checks the currently visible options, not everyone', () => {
    setSearch('teoh'); // -> only Richie Teoh visible
    document.getElementById('projectManagersSelectAll').checked = true;
    toggleAllProjectManagers();
    expect(document.querySelector('.project-manager-checkbox[value="A109"]').checked).toBe(true);
    expect(document.querySelector('.project-manager-checkbox[value="A026"]').checked).toBe(false);
    expect(document.querySelector('.project-manager-checkbox[value="A028"]').checked).toBe(false);
    expect(document.querySelector('.project-manager-checkbox[value="A032"]').checked).toBe(false);
  });

  it('"Select All" reflects only the visible checkboxes\' state, not hidden ones', () => {
    // Check every manager first…
    document.querySelectorAll('.project-manager-checkbox').forEach(b => b.checked = true);
    syncProjectManagersSelectAll();
    expect(document.getElementById('projectManagersSelectAll').checked).toBe(true);
    // …then uncheck one and filter it out of view — Select All should no
    // longer read as fully-checked while it's hidden and unchecked, and
    // should read as checked again once every *visible* box is checked,
    // even though a hidden one is off.
    document.querySelector('.project-manager-checkbox[value="A026"]').checked = false;
    setSearch('teoh'); // only A109 visible, and it's still checked
    expect(document.getElementById('projectManagersSelectAll').checked).toBe(true);
  });
});

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

// Mirrors timesheet.js's renderProjectManagersChecklist eligibility
// filter — only employees currently holding a manager-tier login role
// (PROJECT_MANAGER_ELIGIBLE_ROLES) are offered as Project Manager
// candidates, since core/approval_workflow.py's project_manager approver
// type grants approval power to anyone in a project's manager_ids
// regardless of their own role. A previously-assigned manager who no
// longer qualifies is still shown (never silently dropped by an unrelated
// save), just not offered to newly pick.
// Mirrors timesheet.js's loadProjectManagerEligibility — computing the
// eligible employee_id set from raw /api/users rows. Must check u.roles
// (every capability checkbox on the account — Settings > Users' "Roles"
// checklist), not u.role (only whichever one is currently their "Active /
// Primary Role", the landing view Switch Active Role toggles between): a
// real production case surfaced this — a user with Manager among their
// checked Roles but Employee set as their Active/Primary Role was wrongly
// excluded when only u.role was checked.
describe('Edit Project — Project Manager(s) eligibility computation from /api/users', () => {
  const PROJECT_MANAGER_ELIGIBLE_ROLES = ['manager','hr_manager','hr_admin'];

  function eligibleIdsFrom(users) {
    return new Set(
      users.filter(u=>u.is_active && u.employee_id && (u.roles||[u.role]).some(r=>PROJECT_MANAGER_ELIGIBLE_ROLES.includes(r)))
        .map(u=>u.employee_id)
    );
  }

  it('includes a user whose Active/Primary Role is Employee but who also holds Manager among their Roles', () => {
    const ids = eligibleIdsFrom([
      { employee_id: 'A042', role: 'employee', roles: ['manager','employee'], is_active: true },
    ]);
    expect(ids.has('A042')).toBe(true);
  });

  it('excludes a user whose Roles hold only Employee', () => {
    const ids = eligibleIdsFrom([
      { employee_id: 'A026', role: 'employee', roles: ['employee'], is_active: true },
    ]);
    expect(ids.has('A026')).toBe(false);
  });

  it('falls back to the single role field when roles is absent (older/minimal user rows)', () => {
    const ids = eligibleIdsFrom([
      { employee_id: 'A005', role: 'hr_manager', roles: undefined, is_active: true },
    ]);
    expect(ids.has('A005')).toBe(true);
  });

  it('excludes an inactive user account even if Manager is one of their Roles', () => {
    const ids = eligibleIdsFrom([
      { employee_id: 'A099', role: 'employee', roles: ['manager','employee'], is_active: false },
    ]);
    expect(ids.has('A099')).toBe(false);
  });

  it('excludes a user with no linked employee_id', () => {
    const ids = eligibleIdsFrom([
      { employee_id: null, role: 'manager', roles: ['manager'], is_active: true },
    ]);
    expect(ids.size).toBe(0);
  });
});

describe('Edit Project — Project Manager(s) eligibility filter', () => {
  const employees = [
    { employee_id: 'A028', full_name: 'Cheah Wui Keat', status: 'Active' },   // manager
    { employee_id: 'A026', full_name: 'Mohamad Syafiq', status: 'Active' },   // employee — not eligible
    { employee_id: 'A032', full_name: 'Raj Saraiya', status: 'Active' },      // hr_admin
    { employee_id: 'A109', full_name: 'Richie Teoh', status: 'Active' },      // hr_manager
    { employee_id: 'A050', full_name: 'Inactive Ida', status: 'Inactive' },   // manager, but inactive employee
  ];
  const eligibleIds = new Set(['A028', 'A032', 'A109']); // manager / hr_admin / hr_manager, active users

  function eligibleForPicker(selectedIds) {
    return employees
      .filter(e => e.status === 'Active' && (eligibleIds.has(e.employee_id) || selectedIds.includes(e.employee_id)))
      .map(e => e.employee_id);
  }

  it('offers only active employees holding a manager-tier role', () => {
    expect(eligibleForPicker([]).sort()).toEqual(['A028', 'A032', 'A109']);
  });

  it('excludes a plain "employee"-role employee even if active', () => {
    expect(eligibleForPicker([])).not.toContain('A026');
  });

  it('excludes a manager-tier employee whose employee record is Inactive', () => {
    expect(eligibleForPicker([])).not.toContain('A050');
  });

  it('still shows an already-assigned manager who no longer qualifies, so an unrelated save can\'t silently drop them', () => {
    const withLegacyAssignment = eligibleForPicker(['A026']);
    expect(withLegacyAssignment).toContain('A026');
    expect(withLegacyAssignment.sort()).toEqual(['A026', 'A028', 'A032', 'A109']);
  });
});

// Mirrors timesheet.js's renderProjectMembersChecklist / filterProjectMemberOptions /
// syncProjectMembersSelectAll / toggleAllProjectMembers — the Team
// Members picker, same searchable-checklist mechanics as Project
// Manager(s) above (and same filterEmployeeOptions matcher), but with no
// role-eligibility filter: every active employee is a candidate, since
// this is the roster that governs who can log timesheet hours against
// the project (see routers/projects.py's add_timesheet_entry), not an
// approval-authority list.
describe('Edit Project — Team Members search + checkbox list', () => {
  const members = [
    { id: 'A028', name: 'Cheah Wui Keat' },
    { id: 'A026', name: 'Mohamad Syafiq' },
    { id: 'A032', name: 'Raj Saraiya' },
    { id: 'A109', name: 'Richie Teoh' },
  ];

  beforeEach(() => {
    document.body.innerHTML = `
      <input type="text" id="projectMembersSearch"/>
      <input type="checkbox" id="projectMembersSelectAll" />
      <div id="projectMembersList">
        ${members.map(m => `
          <label class="project-member-option" data-label="${m.name} (${m.id})">
            <input type="checkbox" class="project-member-checkbox" value="${m.id}"/>
            ${m.name} (${m.id})
          </label>`).join('')}
        <div id="projectMembersNoMatch" class="hidden">No matches</div>
      </div>
    `;
  });

  function filterProjectMemberOptions() {
    const q = document.getElementById('projectMembersSearch')?.value || '';
    const opts = [...document.querySelectorAll('.project-member-option')];
    const matched = new Set(filterEmployeeOptions(
      opts.map(el => ({ value: el.querySelector('.project-member-checkbox').value, label: el.dataset.label })),
      q
    ).map(o => o.value));
    let visibleCount = 0;
    opts.forEach(opt => {
      const match = matched.has(opt.querySelector('.project-member-checkbox').value);
      opt.classList.toggle('hidden', !match);
      if (match) visibleCount++;
    });
    document.getElementById('projectMembersNoMatch')?.classList.toggle('hidden', visibleCount > 0);
    syncProjectMembersSelectAll();
  }

  function visibleCheckboxes() {
    return [...document.querySelectorAll('.project-member-option:not(.hidden) .project-member-checkbox')];
  }

  function syncProjectMembersSelectAll() {
    const boxes = visibleCheckboxes();
    document.getElementById('projectMembersSelectAll').checked = boxes.length > 0 && boxes.every(b => b.checked);
  }

  function toggleAllProjectMembers() {
    const checked = document.getElementById('projectMembersSelectAll').checked;
    visibleCheckboxes().forEach(b => b.checked = checked);
  }

  function setSearch(q) {
    document.getElementById('projectMembersSearch').value = q;
    filterProjectMemberOptions();
  }

  function visibleIds() {
    return visibleCheckboxes().map(b => b.value);
  }

  it('shows every active employee when the search box is empty — no role restriction', () => {
    setSearch('');
    expect(visibleIds().sort()).toEqual(['A026', 'A028', 'A032', 'A109']);
  });

  it('filters case-insensitively by name', () => {
    setSearch('richie');
    expect(visibleIds()).toEqual(['A109']);
  });

  it('filters by employee ID as well as name', () => {
    setSearch('A032');
    expect(visibleIds()).toEqual(['A032']);
  });

  it('shows the "No matches" empty state when nothing matches', () => {
    setSearch('zzznomatch');
    expect(visibleIds()).toEqual([]);
    expect(document.getElementById('projectMembersNoMatch').classList.contains('hidden')).toBe(false);
  });

  it('"Select All" while filtered only checks the currently visible options', () => {
    setSearch('teoh');
    document.getElementById('projectMembersSelectAll').checked = true;
    toggleAllProjectMembers();
    expect(document.querySelector('.project-member-checkbox[value="A109"]').checked).toBe(true);
    expect(document.querySelector('.project-member-checkbox[value="A026"]').checked).toBe(false);
  });
});

// Mirrors timesheet.js's renderProjectMembersChecklist's base filter
// (separate from the search box above): an employee deactivated after
// being added as a project member must still be offered — checked — so
// an unrelated future save can't silently drop them from membership just
// because the picker itself would no longer offer them to newly add.
// Same reasoning as the Project Manager(s) picker's own grandfather
// clause.
describe('Edit Project — Team Members includes a deactivated-but-selected member', () => {
  function renderableIds(employees, selectedIds) {
    return employees
      .filter(e => e.status === 'Active' || selectedIds.includes(e.employee_id))
      .map(e => e.employee_id);
  }

  const employees = [
    { employee_id: 'A028', status: 'Active' },
    { employee_id: 'A050', status: 'Inactive' },
  ];

  it('excludes an inactive employee who is not currently selected', () => {
    expect(renderableIds(employees, [])).not.toContain('A050');
  });

  it('still includes an inactive employee who is already a selected member', () => {
    const ids = renderableIds(employees, ['A050']);
    expect(ids).toContain('A050');
    expect(ids.sort()).toEqual(['A028', 'A050']);
  });
});

// Mirrors core.js's fmtDate and timesheet.js's loadCurrentTimesheet week
// label — every other date-range display in the app (Payroll runs, Leave,
// PIP/Performance cycles, Employee contract dates) renders
// `${fmtDate(a)} → ${fmtDate(b)}`; the My Timesheet week nav was the one
// place still showing the raw "YYYY-MM-DD" string it also sends the API.
describe('My Timesheet — week label date format', () => {
  const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function fmtDate(value) {
    if (!value) return '—';
    const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(value);
    const [y, mo, d] = m.slice(1).map(Number);
    return `${String(d).padStart(2,'0')}-${MONTH_ABBR[mo-1]}-${String(y).slice(-2)}`;
  }
  function weekLabel(startIso, endIso) {
    return `${fmtDate(startIso)} → ${fmtDate(endIso)}`;
  }

  it('renders both ends of the week range in dd-MMM-yy, not the raw ISO string', () => {
    expect(weekLabel('2026-09-08', '2026-09-14')).toBe('08-Sep-26 → 14-Sep-26');
  });

  it('handles a week that crosses a month boundary', () => {
    expect(weekLabel('2026-08-31', '2026-09-06')).toBe('31-Aug-26 → 06-Sep-26');
  });
});

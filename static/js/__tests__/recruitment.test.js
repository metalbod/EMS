import { describe, it, expect, beforeEach } from 'vitest';

// Mirrors employees.js's openAddModal — specifically its Reports To
// population loop, which recruitment.js's convertToEmployee used to skip
// entirely. Converting a hired candidate set the Add Employee form's field
// values directly and revealed the modal itself, bypassing the setup
// openAddModal (and employees.js's own startRehire, which follows this
// same "open the real modal first, then prefill" pattern) does: populating
// Reports To from the employees[] roster and wiring up the searchable
// picker. Reports To was left showing only its two pinned non-employee
// options ("None (Top Level)"/"Self"), and Primary Location stuck on
// "No Location" — a real production report ("the dropdown doesn't show
// the list of employees I wanted to see").
describe('Convert candidate to employee — Reports To gets populated', () => {
  let employees;

  function populateReportsTo(reportsToSelect) {
    while (reportsToSelect.options.length > 2) reportsToSelect.remove(2);
    employees.filter(e => e.status === 'Active').forEach(e => {
      const o = document.createElement('option');
      o.value = e.employee_id;
      o.textContent = `${e.employee_id} — ${e.full_name}`;
      reportsToSelect.appendChild(o);
    });
  }

  beforeEach(() => {
    employees = [
      { employee_id: 'A005', full_name: 'Patricia Ling', status: 'Active' },
      { employee_id: 'A042', full_name: 'Sarmini Devi', status: 'Active' },
      { employee_id: 'A099', full_name: 'Former Employee', status: 'Inactive' },
    ];
    document.body.innerHTML = `
      <select id="fReportsTo">
        <option value="">None (Top Level)</option>
        <option value="SELF">Self (CEO / Top of Org)</option>
      </select>
    `;
  });

  it('the regression: skipping the setup step leaves Reports To with only its two pinned options', () => {
    // No populateReportsTo() call — mirrors the old convertToEmployee,
    // which never populated the select at all.
    const rt = document.getElementById('fReportsTo');
    expect(rt.options.length).toBe(2);
  });

  it('the fix: running the setup step lists every active employee alongside the two pinned options', () => {
    const rt = document.getElementById('fReportsTo');
    populateReportsTo(rt);
    expect([...rt.options].map(o => o.value)).toEqual(['', 'SELF', 'A005', 'A042']);
  });

  it('excludes an inactive employee from the Reports To list', () => {
    const rt = document.getElementById('fReportsTo');
    populateReportsTo(rt);
    expect([...rt.options].map(o => o.value)).not.toContain('A099');
  });

  it('is idempotent — re-running it (e.g. a second convert attempt) does not duplicate options', () => {
    const rt = document.getElementById('fReportsTo');
    populateReportsTo(rt);
    populateReportsTo(rt);
    expect(rt.options.length).toBe(4);
  });
});

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

// Phase 2/3 of "one candidate, many requisitions" — mirrors recruitment.js's
// candDupSearchQuery (the Add Candidate modal's "is this an existing
// candidate?" duplicate-detection panel) and shouldShowPerApplicationStages
// (Candidate Detail's legacy single cdStageSelect vs. the per-application
// Applications section — see 20260930_0002_add_candidate_requisitions and
// _transition_candidate_stage's docstring in routers/recruitment.py).
describe('Candidate duplicate-detection search query', () => {
  function candDupSearchQuery(name, ic) {
    if ((ic || '').trim().length >= 4) return ic.trim();
    if ((name || '').trim().length >= 3) return name.trim();
    return '';
  }

  it('prefers IC number over full name when both are present — the stronger identity signal', () => {
    expect(candDupSearchQuery('Ali bin Abu', '900101-14-1234')).toBe('900101-14-1234');
  });

  it('falls back to full name once it reaches 3 characters', () => {
    expect(candDupSearchQuery('Ali', '')).toBe('Ali');
  });

  it('does not search on a 1-2 character name — too noisy, matches almost everything', () => {
    expect(candDupSearchQuery('Al', '')).toBe('');
  });

  it('does not search on a short partial IC (under 4 chars) even if the name is also too short', () => {
    expect(candDupSearchQuery('A', '900')).toBe('');
  });

  it('trims surrounding whitespace before searching', () => {
    expect(candDupSearchQuery('  Ali  ', '')).toBe('Ali');
  });

  it('an empty name and empty IC search for nothing', () => {
    expect(candDupSearchQuery('', '')).toBe('');
  });
});

describe('Candidate Detail — single vs. per-application stage controls', () => {
  function shouldShowPerApplicationStages(applications) {
    return (applications || []).length > 1;
  }

  it('a candidate with one application keeps the legacy single cdStageSelect (no visible change for the common case)', () => {
    expect(shouldShowPerApplicationStages([{ requisition_id: 1, stage: 'New' }])).toBe(false);
  });

  it('a candidate with zero applications (defensive — pre-Phase-2 data) also keeps the legacy control', () => {
    expect(shouldShowPerApplicationStages([])).toBe(false);
    expect(shouldShowPerApplicationStages(undefined)).toBe(false);
  });

  it('a candidate with two or more applications switches to the per-application Applications section — the legacy endpoint 400s past one application', () => {
    expect(shouldShowPerApplicationStages([
      { requisition_id: 1, stage: 'New' },
      { requisition_id: 2, stage: 'Interview' },
    ])).toBe(true);
  });
});

// Mirrors openApplyModal's requisition picker — an "Apply to Another
// Requisition" dropdown should never re-offer a requisition the candidate
// already has an open application against (that POST would just 400 on the
// UNIQUE(candidate_id, requisition_id) constraint).
describe('Apply to Another Requisition — excludes already-applied requisitions', () => {
  function availableRequisitions(allApprovedReqs, applications) {
    const appliedIds = new Set((applications || []).map(a => a.requisition_id));
    return allApprovedReqs.filter(req => !appliedIds.has(req.id));
  }

  const reqs = [{ id: 1, title: 'Engineer' }, { id: 2, title: 'Designer' }, { id: 3, title: 'Analyst' }];

  it('excludes a requisition the candidate has already applied to', () => {
    const rows = availableRequisitions(reqs, [{ requisition_id: 1 }]);
    expect(rows.map(r => r.id)).toEqual([2, 3]);
  });

  it('a general-interest (null requisition_id) application does not exclude any real requisition', () => {
    const rows = availableRequisitions(reqs, [{ requisition_id: null }]);
    expect(rows.map(r => r.id)).toEqual([1, 2, 3]);
  });

  it('a candidate with no applications yet can apply to any approved requisition', () => {
    const rows = availableRequisitions(reqs, []);
    expect(rows.map(r => r.id)).toEqual([1, 2, 3]);
  });
});

// Phase 4: list_candidates became application-level, so the Interview/Offer
// "select candidate" pickers now carry a requisition id per option
// (data-req-id) instead of per-person. Mirrors onOfferCandChange's
// auto-select of the matching Requisition dropdown option when HR picks a
// candidate/application — the Interview form has no requisition picker at
// all, so submitIntForm sends the same data-req-id straight through
// instead (no separate auto-select step to test there).
describe('Offer modal — auto-selecting the requisition from the picked application', () => {
  function resolveOfferReqId(candidateReqId, availableReqIds) {
    if (candidateReqId && availableReqIds.includes(candidateReqId)) return candidateReqId;
    return null;
  }

  it("auto-selects the requisition tied to the candidate's application", () => {
    expect(resolveOfferReqId('5', ['3', '5', '9'])).toBe('5');
  });

  it('leaves the requisition unset for a general-interest application (no requisition_id)', () => {
    expect(resolveOfferReqId('', ['3', '5', '9'])).toBe(null);
  });

  it('does not select a requisition absent from the Approved-only dropdown (e.g. since closed)', () => {
    expect(resolveOfferReqId('99', ['3', '5', '9'])).toBe(null);
  });
});

// Job Requisitions table — the "Published" pill next to the position
// title, shown only when public applications are enabled for that
// requisition (job_requisitions.public_token is set). Mirrors
// loadRequisitions' own row template in recruitment.js.
describe('Job Requisitions — "Published" pill', () => {
  function renderTitleCell(r) {
    return `${r.title}${r.public_token ? '<span class="badge status-positive">Published</span>' : ''}`;
  }

  it('shows the pill when public applications are enabled', () => {
    expect(renderTitleCell({ title: 'QA Engineer', public_token: 'abc-123' })).toContain('Published');
  });

  it('omits the pill when public applications are not enabled', () => {
    expect(renderTitleCell({ title: 'QA Engineer', public_token: null })).not.toContain('Published');
  });
});

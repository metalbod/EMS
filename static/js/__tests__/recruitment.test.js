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
  function candDupSearchQuery(name, ic, email) {
    if ((ic || '').trim().length >= 4) return ic.trim();
    if ((email || '').trim().length >= 5 && email.includes('@')) return email.trim();
    if ((name || '').trim().length >= 3) return name.trim();
    return '';
  }

  it('prefers IC number over full name when both are present — the stronger identity signal', () => {
    expect(candDupSearchQuery('Ali bin Abu', '900101-14-1234')).toBe('900101-14-1234');
  });

  it('prefers IC number over email when both are present', () => {
    expect(candDupSearchQuery('', '900101-14-1234', 'ali@example.com')).toBe('900101-14-1234');
  });

  it('falls back to email when no IC is present', () => {
    expect(candDupSearchQuery('Ali bin Abu', '', 'ali@example.com')).toBe('ali@example.com');
  });

  it('does not search on an email with no "@" or under 5 characters', () => {
    expect(candDupSearchQuery('', '', 'a@b')).toBe('');
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

  it('an empty name, IC, and email search for nothing', () => {
    expect(candDupSearchQuery('', '', '')).toBe('');
  });
});

// Mirrors recruitment.js's fillBlankCandidateFields — Add Candidate's
// "Extract with AI" button only fills fields still blank, never overwrites
// something HR already typed (before or after attaching the resume).
describe('AI resume extraction — fill-blank-fields-only', () => {
  const FIELD_TO_INPUT = {
    full_name: 'candFullName', email: 'candEmail', phone: 'candPhone',
    nationality: 'candNationality', experience_years: 'candExp', skills: 'candSkills',
  };
  // candExp and candNationality start pre-filled with a default in the
  // real markup (value="0" / value="Malaysian") — a plain "is it non-empty"
  // check would treat the untouched default as "HR already set this" and
  // never let extraction fill in a real value, so a value still exactly
  // matching the default counts as blank too (regression test below).
  const BLANK_SENTINELS = { candExp: '0', candNationality: 'Malaysian' };

  function fillBlankCandidateFields(fields, inputs) {
    let filled = 0;
    for (const [field, inputId] of Object.entries(FIELD_TO_INPUT)) {
      const value = fields[field];
      if (value === null || value === undefined || value === '') continue;
      const isBlank = inputId in inputs && (inputs[inputId] === '' || inputs[inputId] === BLANK_SENTINELS[inputId]);
      if (!isBlank) continue;
      inputs[inputId] = value;
      filled++;
    }
    return filled;
  }

  it('fills every blank field the extraction returned', () => {
    const inputs = { candFullName: '', candEmail: '', candPhone: '', candNationality: 'Malaysian', candExp: '0', candSkills: '' };
    const filled = fillBlankCandidateFields(
      { full_name: 'Ali bin Abu', email: 'ali@example.com', skills: 'Python, SQL' },
      inputs
    );
    expect(filled).toBe(3);
    expect(inputs.candFullName).toBe('Ali bin Abu');
    expect(inputs.candEmail).toBe('ali@example.com');
    expect(inputs.candSkills).toBe('Python, SQL');
  });

  it('never overwrites a field HR already typed', () => {
    const inputs = { candFullName: 'Already Typed Name', candEmail: '', candPhone: '', candNationality: 'Malaysian', candExp: '0', candSkills: '' };
    const filled = fillBlankCandidateFields(
      { full_name: 'Extracted Name From Resume', email: 'extracted@example.com' },
      inputs
    );
    expect(filled).toBe(1); // only email, full_name was already set
    expect(inputs.candFullName).toBe('Already Typed Name');
    expect(inputs.candEmail).toBe('extracted@example.com');
  });

  it('skips a field the AI omitted (null/undefined), leaving it blank', () => {
    const inputs = { candFullName: '', candEmail: '', candPhone: '', candNationality: 'Malaysian', candExp: '0', candSkills: '' };
    const filled = fillBlankCandidateFields({ full_name: 'Ali', phone: null, skills: undefined }, inputs);
    expect(filled).toBe(1);
    expect(inputs.candPhone).toBe('');
    expect(inputs.candSkills).toBe('');
  });

  it('fills experience_years even though candExp defaults to "0" (regression)', () => {
    const inputs = { candFullName: '', candEmail: '', candPhone: '', candNationality: 'Malaysian', candExp: '0', candSkills: '' };
    fillBlankCandidateFields({ experience_years: 5 }, inputs);
    expect(inputs.candExp).toBe(5);
  });

  it('fills nationality even though candNationality defaults to "Malaysian" (regression)', () => {
    const inputs = { candFullName: '', candEmail: '', candPhone: '', candNationality: 'Malaysian', candExp: '0', candSkills: '' };
    fillBlankCandidateFields({ nationality: 'Indonesian' }, inputs);
    expect(inputs.candNationality).toBe('Indonesian');
  });

  it('does not touch candExp/candNationality once HR has changed them from the default', () => {
    const inputs = { candFullName: '', candEmail: '', candPhone: '', candNationality: 'Singaporean', candExp: '3', candSkills: '' };
    const filled = fillBlankCandidateFields({ nationality: 'Indonesian', experience_years: 7 }, inputs);
    expect(filled).toBe(0);
    expect(inputs.candNationality).toBe('Singaporean');
    expect(inputs.candExp).toBe('3');
  });

  it('returns 0 when every field is either blank-extraction or already filled', () => {
    const inputs = { candFullName: 'Set', candEmail: 'set@example.com', candPhone: 'set', candNationality: 'Set', candExp: '1', candSkills: 'set' };
    const filled = fillBlankCandidateFields({ full_name: 'New Name' }, inputs);
    expect(filled).toBe(0);
  });
});

// Mirrors recruitment.js's CAND_AI_EXTRACTABLE_MIMES gate on the "Extract
// with AI" button — only a brand-new candidate (no candId yet) with at
// least one PDF/image pending file shows it; Word/text files and editing
// an existing candidate never do.
describe('AI resume extraction — Extract button visibility', () => {
  const CAND_AI_EXTRACTABLE_MIMES = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp'];

  function shouldShowExtractButton(isNewCandidate, pendingFiles) {
    const hasExtractableFile = pendingFiles.some(f => CAND_AI_EXTRACTABLE_MIMES.includes(f.mime_type));
    return isNewCandidate && hasExtractableFile;
  }

  it('shows the button for a new candidate with a PDF attached', () => {
    expect(shouldShowExtractButton(true, [{ mime_type: 'application/pdf' }])).toBe(true);
  });

  it('shows the button for a new candidate with an image attached', () => {
    expect(shouldShowExtractButton(true, [{ mime_type: 'image/png' }])).toBe(true);
  });

  it('hides the button when only a Word document is attached', () => {
    expect(shouldShowExtractButton(true, [{ mime_type: 'application/msword' }])).toBe(false);
  });

  it('hides the button with no files attached yet', () => {
    expect(shouldShowExtractButton(true, [])).toBe(false);
  });

  it('hides the button when editing an existing candidate, even with a PDF attached', () => {
    expect(shouldShowExtractButton(false, [{ mime_type: 'application/pdf' }])).toBe(false);
  });

  it('shows the button if at least one of several files is extractable', () => {
    expect(shouldShowExtractButton(true, [{ mime_type: 'application/msword' }, { mime_type: 'application/pdf' }])).toBe(true);
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

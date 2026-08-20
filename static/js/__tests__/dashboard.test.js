import { describe, it, expect, beforeEach } from 'vitest';

// Matches dashboard.js's loadRecruitmentDash() candidate-pipeline render —
// always lists all 7 canonical stages (matching Candidate Bank's stage
// filter list), rather than hiding Hired/Rejected/Withdrawn when their
// count is zero.
describe('Recruitment dashboard candidate pipeline', () => {
  const PIPELINE_STAGES = ['New','Screening','Interview','Offer','Hired','Rejected','Withdrawn'];
  const PIPELINE_COLORS = {New:'bg-slate-400',Screening:'bg-blue-400',Interview:'bg-purple-400',Offer:'bg-yellow-400',Hired:'bg-emerald-500',Rejected:'bg-red-400',Withdrawn:'bg-slate-300'};

  function statusColor(map, key, fallback) { return map[key] || fallback; }

  function renderPipeline(s) {
    const totalCands = s.total_candidates || 1;
    return s.total_candidates ? PIPELINE_STAGES.map(stage => {
      const cnt = s.cand_by_stage[stage] || 0;
      return `<div class="flex items-center gap-2">
        <div class="w-20 text-xs text-slate-600">${stage}</div>
        <div class="flex-1 bg-slate-100 rounded-full h-2">
          <div class="${statusColor(PIPELINE_COLORS, stage, 'bg-slate-400')} h-2 rounded-full" style="width:${Math.round(cnt/totalCands*100)}%"></div>
        </div>
        <div class="text-xs text-slate-500 w-5 text-right">${cnt}</div>
      </div>`;
    }).join('') : '<p class="text-slate-400 text-sm">No candidates yet.</p>';
  }

  beforeEach(() => {
    document.body.innerHTML = '<div id="rCandPipeline"></div>';
  });

  it('shows all 7 stages even when Hired/Rejected/Withdrawn are zero, matching Candidate Bank', () => {
    document.getElementById('rCandPipeline').innerHTML = renderPipeline({
      total_candidates: 8,
      cand_by_stage: { New: 3, Screening: 2, Interview: 1, Offer: 1, Withdrawn: 1 },
    });
    PIPELINE_STAGES.forEach(stage => {
      expect(document.getElementById('rCandPipeline').innerHTML).toContain(`>${stage}<`);
    });
  });

  it('renders a zero row for a stage with no candidates instead of omitting it', () => {
    document.getElementById('rCandPipeline').innerHTML = renderPipeline({
      total_candidates: 8,
      cand_by_stage: { New: 3, Screening: 2, Interview: 1, Offer: 1, Withdrawn: 1 },
    });
    const html = document.getElementById('rCandPipeline').innerHTML;
    const hiredRow = html.split('Hired<')[1];
    expect(hiredRow).toContain('>0<');
  });

  it('shows the empty state when there are no candidates at all', () => {
    document.getElementById('rCandPipeline').innerHTML = renderPipeline({
      total_candidates: 0,
      cand_by_stage: {},
    });
    expect(document.getElementById('rCandPipeline').innerHTML).toContain('No candidates yet.');
  });
});

// Matches dashboard.js's renderDashboard() Workforce tab additions —
// gender breakdown on the Total/Active/Inactive stat cards, and the
// Nationality/Race segmented bars under "Workforce Composition". Race is
// a validated required 7-value enum (core/constants.py's RACES) so every
// employee always has one — no "Undefined" bucket. Nationality is free
// text with no enum, so "Local" is a nationality==='Malaysian' heuristic.
describe('Workforce tab composition stats', () => {
  function genderLabel(arr) {
    return arr.length
      ? `${arr.filter(e=>e.gender==='Male').length} Male · ${arr.filter(e=>e.gender==='Female').length} Female` : '—';
  }

  function segments(employeesArr, total) {
    const localCount = employeesArr.filter(e=>e.nationality==='Malaysian').length;
    const nationality = [
      { label:'Local', count:localCount },
      { label:'Foreigner', count:employeesArr.length-localCount },
    ].filter(s=>s.count>0);
    const raceCounts = {};
    employeesArr.forEach(e=>{ raceCounts[e.race]=(raceCounts[e.race]||0)+1; });
    const race = Object.entries(raceCounts).sort((a,b)=>b[1]-a[1]).map(([label,count])=>({label,count}));
    return { nationality, race, nationalityPct: nationality.map(s=>Math.round(s.count/total*100)) };
  }

  const emps = [
    { gender:'Male', nationality:'Malaysian', race:'Malay', status:'Active' },
    { gender:'Female', nationality:'Malaysian', race:'Chinese', status:'Active' },
    { gender:'Male', nationality:'Indonesian', race:'Others', status:'Inactive' },
  ];

  it('formats gender counts as "N Male · N Female"', () => {
    expect(genderLabel(emps)).toBe('2 Male · 1 Female');
    expect(genderLabel(emps.filter(e=>e.status==='Active'))).toBe('1 Male · 1 Female');
  });

  it('shows an em dash for an empty group instead of "0 Male · 0 Female"', () => {
    expect(genderLabel([])).toBe('—');
  });

  it('splits nationality into Local/Foreigner via the Malaysian heuristic', () => {
    const { nationality } = segments(emps, emps.length);
    expect(nationality).toEqual([{ label:'Local', count:2 }, { label:'Foreigner', count:1 }]);
  });

  it('omits a zero-count nationality segment rather than rendering an empty bar slice', () => {
    const allLocal = [{ nationality:'Malaysian', race:'Malay' }, { nationality:'Malaysian', race:'Chinese' }];
    const { nationality } = segments(allLocal, allLocal.length);
    expect(nationality).toEqual([{ label:'Local', count:2 }]);
  });

  it('groups race counts using the real enum labels, one segment per race present', () => {
    const { race } = segments(emps, emps.length);
    expect(race).toHaveLength(3);
    expect(race.find(r=>r.label==='Malay').count).toBe(1);
    expect(race.find(r=>r.label==='Chinese').count).toBe(1);
    expect(race.find(r=>r.label==='Others').count).toBe(1);
    expect(race.find(r=>r.label==='Indian')).toBeUndefined();
  });

  it('never produces an "Undefined" race segment, since race is a required field', () => {
    const { race } = segments(emps, emps.length);
    expect(race.some(r=>r.label==='Undefined')).toBe(false);
  });
});

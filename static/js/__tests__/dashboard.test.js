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

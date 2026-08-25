import { describe, it, expect, beforeEach } from 'vitest';

// Matches dashboard.js's loadRecruitmentDash() candidate-pipeline render —
// always lists all 9 canonical stages (matching Candidate Bank's stage
// filter list), rather than hiding Hired/Rejected by Candidate/Rejected
// by Company/Withdrawn when their count is zero.
describe('Recruitment dashboard candidate pipeline', () => {
  const PIPELINE_STAGES = ['New','Screening','Interview','Pending Checks','Offer','Hired','Rejected by Candidate','Rejected by Company','Withdrawn'];
  const PIPELINE_COLORS = {New:'bg-slate-400',Screening:'bg-blue-400',Interview:'bg-purple-400','Pending Checks':'bg-orange-400',Offer:'bg-yellow-400',Hired:'bg-emerald-500','Rejected by Candidate':'bg-red-400','Rejected by Company':'bg-red-400',Withdrawn:'bg-slate-300'};

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

  it('shows all 9 stages even when Hired/Rejected by Candidate/Rejected by Company/Withdrawn are zero, matching Candidate Bank', () => {
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

// Matches dashboard.js's renderLeaveCalendarGrid — leave entries and
// onboarding/offboarding action items (due_date, read literally with no
// UTC/timezone conversion — see routers/onboarding.py's due_date being a
// plain HR-entered wall-clock value, not a *_at timestamp) share one
// combined per-day +N-more cap instead of each type getting its own.
describe('Leave Calendar — merging leave entries and onboarding action items per day', () => {
  function bucketByDay(entries, obItems, year, month) {
    const firstDay = new Date(year, month - 1, 1);
    const byDay = {};
    for (const e of entries) {
      const start = new Date(e.start_date + 'T00:00:00');
      const end = new Date(e.end_date + 'T00:00:00');
      for (let d = new Date(Math.max(start, firstDay)); d <= end && d.getMonth() === month - 1; d.setDate(d.getDate() + 1)) {
        const day = d.getDate();
        const dStr = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
        const dayPeriod = dStr === e.start_date ? e.start_day_period : (dStr === e.end_date ? e.end_day_period : null);
        (byDay[day] = byDay[day] || []).push({ ...e, _dayPeriod: dayPeriod });
      }
    }
    const obByDay = {};
    for (const o of obItems) {
      if (!o.due_date) continue;
      const d = new Date(o.due_date.slice(0, 10) + 'T00:00:00');
      if (d.getFullYear() === year && d.getMonth() === month - 1) {
        (obByDay[d.getDate()] = obByDay[d.getDate()] || []).push(o);
      }
    }
    return { byDay, obByDay };
  }

  function dayView(byDay, obByDay, day) {
    const dayItems = [
      ...(byDay[day] || []).map(e => ({ kind: 'leave', e })),
      ...(obByDay[day] || []).map(o => ({ kind: 'ob', o })),
    ];
    return { shown: dayItems.slice(0, 3), rest: dayItems.slice(3) };
  }

  function displayName(fullName, preferredName) {
    const full = (fullName || '').trim();
    const pref = (preferredName || '').trim();
    return pref || full;
  }

  function chipInner(item) {
    return item.kind === 'leave'
      ? `${displayName(item.e.full_name, item.e.preferred_name)}${item.e._dayPeriod ? ` (${item.e._dayPeriod})` : ''}`
      : `📌 ${item.o.title} — ${displayName(item.o.employee_name, item.o.employee_preferred_name)}`;
  }

  it('places a leave entry and an action item due the same day into the same bucket', () => {
    const { byDay, obByDay } = bucketByDay(
      [{ start_date: '2026-08-10', end_date: '2026-08-10', full_name: 'Jane Tan' }],
      [{ title: 'Submit IC copy', due_date: '2026-08-10 09:00:00' }],
      2026, 8
    );
    const { shown } = dayView(byDay, obByDay, 10);
    expect(shown.map(i => i.kind).sort()).toEqual(['leave', 'ob']);
  });

  it('reads due_date literally as the local date — no UTC/timezone shift applied', () => {
    // If this were run through parseUTC (appending 'Z'), a late-evening
    // due_date near midnight could shift onto the wrong day depending on
    // the browser's timezone offset. due_date is a plain wall-clock value,
    // so only the 'YYYY-MM-DD' prefix is read, verbatim.
    const { obByDay } = bucketByDay([], [{ title: 'Late item', due_date: '2026-08-31 23:30:00' }], 2026, 8);
    expect(obByDay[31]).toHaveLength(1);
    expect(obByDay[30]).toBeUndefined();
  });

  it('excludes an action item due in a different month', () => {
    const { obByDay } = bucketByDay([], [{ title: 'Next month item', due_date: '2026-09-01 09:00:00' }], 2026, 8);
    expect(obByDay[1]).toBeUndefined();
  });

  it('ignores an action item with no due_date set', () => {
    const { obByDay } = bucketByDay([], [{ title: 'No due date', due_date: null }], 2026, 8);
    expect(Object.keys(obByDay)).toHaveLength(0);
  });

  it('caps a busy day at 3 shown combined across both types, overflow in "rest"', () => {
    const leaveEntries = [
      { start_date: '2026-08-15', end_date: '2026-08-15', full_name: 'A' },
      { start_date: '2026-08-15', end_date: '2026-08-15', full_name: 'B' },
    ];
    const obItems = [
      { title: 'Item 1', due_date: '2026-08-15 09:00:00' },
      { title: 'Item 2', due_date: '2026-08-15 10:00:00' },
      { title: 'Item 3', due_date: '2026-08-15 11:00:00' },
    ];
    const { byDay, obByDay } = bucketByDay(leaveEntries, obItems, 2026, 8);
    const { shown, rest } = dayView(byDay, obByDay, 15);
    expect(shown).toHaveLength(3);
    expect(rest).toHaveLength(2);
  });

  it('shows the employee name after the item title, so HR knows who the action item is for', () => {
    const { obByDay } = bucketByDay(
      [],
      [{ title: 'Submit IC Copy', due_date: '2026-08-25 09:00:00', employee_name: 'Richie Teoh', employee_preferred_name: null }],
      2026, 8
    );
    const { shown } = dayView({}, obByDay, 25);
    expect(chipInner(shown[0])).toBe('📌 Submit IC Copy — Richie Teoh');
  });

  it('prefers the employee preferred name over full name in the chip, like the leave chip does', () => {
    const { obByDay } = bucketByDay(
      [],
      [{ title: 'Submit IC Copy', due_date: '2026-08-25 09:00:00', employee_name: 'Richard Teoh', employee_preferred_name: 'Richie' }],
      2026, 8
    );
    const { shown } = dayView({}, obByDay, 25);
    expect(chipInner(shown[0])).toBe('📌 Submit IC Copy — Richie');
  });

  it('shows the half-day period only on the start day of a multi-day range, not on the days after', () => {
    const { byDay } = bucketByDay(
      [{ start_date: '2026-08-10', end_date: '2026-08-12', full_name: 'Jane Tan', start_day_period: 'PM', end_day_period: null }],
      [], 2026, 8
    );
    expect(chipInner(dayView(byDay, {}, 10).shown[0])).toBe('Jane Tan (PM)');
    expect(chipInner(dayView(byDay, {}, 11).shown[0])).toBe('Jane Tan');
    expect(chipInner(dayView(byDay, {}, 12).shown[0])).toBe('Jane Tan');
  });

  it('shows the half-day period only on the end day of a multi-day range', () => {
    const { byDay } = bucketByDay(
      [{ start_date: '2026-08-10', end_date: '2026-08-12', full_name: 'Jane Tan', start_day_period: null, end_day_period: 'AM' }],
      [], 2026, 8
    );
    expect(chipInner(dayView(byDay, {}, 10).shown[0])).toBe('Jane Tan');
    expect(chipInner(dayView(byDay, {}, 11).shown[0])).toBe('Jane Tan');
    expect(chipInner(dayView(byDay, {}, 12).shown[0])).toBe('Jane Tan (AM)');
  });

  it('shows no period suffix for a full-day entry', () => {
    const { byDay } = bucketByDay(
      [{ start_date: '2026-08-10', end_date: '2026-08-10', full_name: 'Jane Tan', start_day_period: null, end_day_period: null }],
      [], 2026, 8
    );
    expect(chipInner(dayView(byDay, {}, 10).shown[0])).toBe('Jane Tan');
  });
});

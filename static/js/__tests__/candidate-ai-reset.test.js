import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL fillBlankCandidateFields / resetCandAiFilled (recruitment.js) against a DOM:
// attaching another resume (or removing one) must undo the previous AI extraction's fills —
// but never a value HR typed or edited themselves.
const rec = readFileSync(resolve(__dirname, '..', 'recruitment.js'), 'utf8');
const fnSource = name => {
  const start = rec.indexOf(`function ${name}(`);
  const end = rec.indexOf('\n}\n', start);
  expect(start).toBeGreaterThan(-1);
  return rec.slice(start, end + 2);
};
const lineSource = prefix => {
  const start = rec.indexOf(prefix);
  expect(start).toBeGreaterThan(-1);
  return rec.slice(start, rec.indexOf('\n', start) + 1);
};

let dupChecks;
const make = () => new Function('onCandIdentityInput', `
  ${lineSource('let candAiFilled')}
  ${lineSource('const CAND_AI_FIELD_DEFAULTS')}
  ${fnSource('resetCandAiFilled')}
  ${fnSource('fillBlankCandidateFields')}
  return { fill: fillBlankCandidateFields, reset: resetCandAiFilled, filled: () => candAiFilled };
`)(() => { dupChecks++; });

const IDS = ['candFullName', 'candEmail', 'candPhone', 'candIc', 'candNationality', 'candDob', 'candAddress',
  'candPosition', 'candCompany', 'candExp', 'candSkills', 'candEmpHistory', 'candField', 'candInstitution',
  'candGradYear', 'candCerts', 'candResume', 'candLinkedin'];
const val = id => document.getElementById(id).value;
const set = (id, v) => { document.getElementById(id).value = v; };

beforeEach(() => {
  dupChecks = 0;
  document.body.innerHTML = IDS.map(id => `<input id="${id}">`).join('') + `
    <select id="candGender"><option value="">-</option><option>Male</option><option>Female</option></select>
    <select id="candQual"><option value="">Select</option><option>Degree</option></select>
    <p id="candExtractAiStatus" class="text-xs text-emerald-600">Filled 3 fields</p>`;
  set('candNationality', 'Malaysian'); set('candExp', '0');
});

describe('undoing a previous AI extraction', () => {
  it('clears what the first resume filled, back to blank / the markup defaults', () => {
    const m = make();
    m.fill({ full_name: 'Aida', email: 'aida@x.com', nationality: 'Indonesian', experience_years: 7,
      gender: 'Female', highest_qualification: 'Degree', skills: 'SQL' });
    expect(val('candFullName')).toBe('Aida');
    expect(val('candNationality')).toBe('Indonesian');
    expect(val('candExp')).toBe('7');

    m.reset();
    expect(val('candFullName')).toBe('');
    expect(val('candEmail')).toBe('');
    expect(val('candSkills')).toBe('');
    expect(val('candNationality')).toBe('Malaysian'); // default, not blank
    expect(val('candExp')).toBe('0');                 // default, not blank
    expect(val('candGender')).toBe('');
    expect(val('candQual')).toBe('');
    expect(m.filled()).toEqual({});
    expect(document.getElementById('candExtractAiStatus').className).toContain('hidden');
    expect(dupChecks).toBe(1); // duplicate-candidate check re-run
  });

  it('lets the second resume fill every field, with nothing left over from the first', () => {
    const m = make();
    m.fill({ full_name: 'First Person', email: 'first@x.com', phone: '011', skills: 'Java' });
    m.reset();
    m.fill({ full_name: 'Second Person', email: 'second@x.com' });
    expect(val('candFullName')).toBe('Second Person');
    expect(val('candEmail')).toBe('second@x.com');
    expect(val('candPhone')).toBe('');   // the first resume's phone is gone
    expect(val('candSkills')).toBe('');
  });

  it('keeps a value HR typed over, or edited after, the extraction', () => {
    const m = make();
    set('candCompany', 'Typed Before'); // HR typed this before extracting: never overwritten, never reset
    m.fill({ full_name: 'Aida', phone: '011', current_company: 'From Resume' });
    expect(val('candCompany')).toBe('Typed Before');
    set('candPhone', '999-edited');     // HR corrected an AI-filled field
    m.reset();
    expect(val('candFullName')).toBe('');          // untouched AI fill: reset
    expect(val('candPhone')).toBe('999-edited');   // edited by HR: kept
    expect(val('candCompany')).toBe('Typed Before');
  });

  it('is a no-op when nothing was extracted', () => {
    const m = make();
    set('candFullName', 'HR typed');
    m.reset();
    expect(val('candFullName')).toBe('HR typed');
    expect(dupChecks).toBe(0);
  });
});

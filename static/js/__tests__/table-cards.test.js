import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL labelling logic from table-cards.js.
const src = readFileSync(resolve(__dirname, '..', 'table-cards.js'), 'utf8');
const { labelCardTable } = new Function(`${src.slice(0, src.indexOf('function labelAllCardTables'))}\nreturn { labelCardTable };`)();

const table = body => {
  document.body.innerHTML = `<table class="cards-on-phone"><thead><tr><th>Name ▲</th><th>Department</th><th> Joined  On </th><th></th></tr></thead><tbody>${body}</tbody></table>`;
  return document.querySelector('table');
};

describe('table-cards labelling', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('labels every cell after the first with its column name, cleaned of sort arrows and extra spaces', () => {
    const t = table('<tr><td>Aisyah</td><td>IT</td><td>2026-01-05</td><td><button>Edit</button></td></tr>');
    labelCardTable(t);
    const [name, dept, joined, actions] = [...t.querySelectorAll('td')];
    expect(name.hasAttribute('data-label')).toBe(false);       // the card's title
    expect(dept.getAttribute('data-label')).toBe('Department');
    expect(joined.getAttribute('data-label')).toBe('Joined On');
    expect(actions.hasAttribute('data-label')).toBe(false);    // empty header: no label
  });

  it('leaves single-cell rows (loading / empty messages) alone', () => {
    const t = table('<tr><td colspan="4">Loading…</td></tr>');
    labelCardTable(t);
    expect(t.querySelector('td').hasAttribute('data-label')).toBe(false);
  });

  it('is safe to re-run after the rows are rebuilt, and drops a label when a header goes blank', () => {
    const t = table('<tr><td>A</td><td>IT</td><td>x</td><td></td></tr>');
    labelCardTable(t); labelCardTable(t);
    expect(t.querySelectorAll('[data-label]')).toHaveLength(2);
    t.querySelector('thead th:nth-child(2)').textContent = '';
    labelCardTable(t);
    expect(t.querySelector('td:nth-child(2)').hasAttribute('data-label')).toBe(false);
  });

  it('does nothing for a table with no header', () => {
    document.body.innerHTML = '<table class="cards-on-phone"><tbody><tr><td>a</td><td>b</td></tr></tbody></table>';
    labelCardTable(document.querySelector('table'));
    expect(document.querySelector('[data-label]')).toBeNull();
  });
});

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// The app is one concatenated script (scripts/js-manifest.js) plus lazy modules, all sharing ONE global scope, so a second
// top-level `function foo` anywhere silently replaces the first (last one wins) and breaks its callers at runtime — which
// is how a new downloadCsv(filename, text) once replaced dashboard.js's downloadCsv(rows, filename) with no error until the
// button was clicked. Per-file unit tests can't see that; this does.
const root = resolve(__dirname, '..', '..', '..');
const manifest = require(resolve(root, 'scripts', 'js-manifest.js'));
const lazy = require(resolve(root, 'scripts', 'lazy-modules.js'));
const files = [...manifest, ...lazy];

function topLevelNames(src) {
  const names = [];
  // top-level only: the declaration starts in column 0 (the code base indents everything nested)
  for (const m of src.matchAll(/^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(/gm)) names.push(m[1]);
  for (const m of src.matchAll(/^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=/gm)) names.push(m[1]);
  return names;
}

// Pre-existing duplicates found when this test was written; each is a genuine override someone has already reasoned
// about (or never noticed). New ones must not appear — fix the name instead of adding to this list.
const KNOWN = new Set([]);

describe('bundle-wide globals', () => {
  it('no top-level function or variable name is declared in two files', () => {
    const seen = new Map();
    const dups = [];
    for (const f of files) {
      const src = readFileSync(resolve(root, 'static', 'js', f), 'utf8');
      for (const n of new Set(topLevelNames(src))) {
        if (seen.has(n) && !KNOWN.has(n)) dups.push(`${n}: ${seen.get(n)} and ${f}`);
        else seen.set(n, f);
      }
    }
    expect(dups).toEqual([]);
  });
});

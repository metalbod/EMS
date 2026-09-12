// Bundles every static/js/*.js file listed in scripts/js-manifest.js into
// one minified file — same "built locally, output committed" precedent
// as `npm run build:css` (tailwindcss): the Dockerfile just COPYs
// whatever's already in static/, no Node/npm runs inside the production
// container at all.
//
// These files aren't ES modules — they're plain global-scope scripts
// that share state via top-level `let`/`function` declarations (e.g.
// core.js's `let employees = ...`, read directly by every other file).
// This script preserves that by concatenating them in manifest order
// (load order matters) and minifying the result as one blob — not
// "bundling" in esbuild's module-graph sense, since there's no
// import/export to resolve here.
//
// Run via `npm run build:js` (or `npm run build`, alongside build:css)
// after editing any static/js/*.js file, before committing — mirrors
// the existing build:css workflow exactly.
const fs = require('fs');
const path = require('path');
const esbuild = require('esbuild');
const manifest = require('./js-manifest');
const lazyModules = require('./lazy-modules');

const ROOT = path.join(__dirname, '..');
const JS_DIR = path.join(ROOT, 'static', 'js');
const MODULES_DIR = path.join(JS_DIR, 'modules');
const OUT_NAME = 'app.bundle.js';
const OUT_FILE = path.join(JS_DIR, OUT_NAME);

const kb = n => (n / 1024).toFixed(1);

const missing = manifest.filter(name => !fs.existsSync(path.join(JS_DIR, name)));
if (missing.length) {
  console.error(`scripts/js-manifest.js lists file(s) that don't exist under static/js/: ${missing.join(', ')}`);
  process.exit(1);
}

const concatenated = manifest.map(name => {
  const code = fs.readFileSync(path.join(JS_DIR, name), 'utf8');
  return `// ---- ${name} ----\n${code}`;
  // Joined with `;\n` below (not just `\n`) so a source file missing a
  // trailing semicolon before an IIFE/regex-literal-looking line at the
  // start of the next file can't get silently mis-parsed as one
  // continued statement.
}).join('\n;\n');

const result = esbuild.transformSync(concatenated, {
  minify: true,
  sourcemap: 'external',
  sourcefile: OUT_NAME,
  target: 'es2019',
});

fs.writeFileSync(OUT_FILE, `${result.code}\n//# sourceMappingURL=${OUT_NAME}.map\n`);
fs.writeFileSync(`${OUT_FILE}.map`, result.map);

console.log(`Bundled ${manifest.length} files (${kb(concatenated.length)} KB) -> static/js/${OUT_NAME} (${kb(result.code.length)} KB minified)`);

// Lazy modules (Speed Audit item 7): each file in scripts/lazy-modules.js
// is minified on its own (not concatenated with the others — verified
// independent of each other when that list was created) and written to
// static/js/modules/<name>, fetched by the browser on demand via
// ensureModuleLoaded() in core.js instead of at login.
const missingLazy = lazyModules.filter(name => !fs.existsSync(path.join(JS_DIR, name)));
if (missingLazy.length) {
  console.error(`scripts/lazy-modules.js lists file(s) that don't exist under static/js/: ${missingLazy.join(', ')}`);
  process.exit(1);
}
fs.mkdirSync(MODULES_DIR, { recursive: true });
let lazyTotalRaw = 0, lazyTotalMin = 0;
for (const name of lazyModules) {
  const code = fs.readFileSync(path.join(JS_DIR, name), 'utf8');
  const out = esbuild.transformSync(code, {
    minify: true,
    sourcemap: 'external',
    sourcefile: name,
    target: 'es2019',
  });
  const outFile = path.join(MODULES_DIR, name);
  fs.writeFileSync(outFile, `${out.code}\n//# sourceMappingURL=${name}.map\n`);
  fs.writeFileSync(`${outFile}.map`, out.map);
  lazyTotalRaw += code.length;
  lazyTotalMin += out.code.length;
}
console.log(`Minified ${lazyModules.length} lazy module(s) (${kb(lazyTotalRaw)} KB) -> static/js/modules/*.js (${kb(lazyTotalMin)} KB minified)`);

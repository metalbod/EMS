// Files listed here are built as separate, individually-minified bundles
// under static/js/modules/<name> (by scripts/build-js.js) instead of being
// concatenated into the main static/js/app.bundle.js. Each is fetched by
// the browser only the first time its page is actually opened (see
// ensureModuleLoaded() in core.js), not at login — see Speed Audit item 7's
// research: these are exactly the files that are (a) never reached by a
// plain "employee" role's nav at all, and (b) don't mix in any
// employee-facing self-service screen the way leave.js/benefits.js/
// timesheet.js/etc. do, so deferring the whole file is safe.
//
// Adding a file here: also add its page-id -> module-name entry to
// LAZY_PAGE_MODULES in core.js's showPage() (or, if it's not reached via
// showPage at all — like employee-documents.js's view-modal tab, or
// locations.js's Add/Edit Employee dropdown — add an explicit
// ensureModuleLoaded() call at its actual call site instead), then run
// `npm run build:js`.
//
// Each of these must be self-contained relative to the others in this
// list (no file here may call a function only another file here defines
// — verified when this list was created) — they can load in any order,
// or not at all if that page is never opened.
module.exports = [
  'audit.js',
  'users.js',
  'institutions.js',
  'roles.js',
  'bulk-upload.js',
  'locations.js',
  'employee-documents.js',
  'approval-workflow.js',
  'ai-assistant-settings.js',
  'recruitment.js',
  'onboarding.js',
];

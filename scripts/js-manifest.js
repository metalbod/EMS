// Ordered list of static/js/*.js files bundled into static/js/app.bundle.js
// by scripts/build-js.js. This is the single source of truth for load
// order now that index.html references the one bundle instead of a
// <script> tag per file — these are plain global-scope scripts (no
// import/export), so later files read state top-level earlier ones
// declared (core.js's `let employees`, etc), meaning THIS ORDER MATTERS
// and must stay exactly what index.html used to list.
//
// This is the CORE bundle only — always downloaded and parsed at login,
// for every role. See scripts/lazy-modules.js for the other static/js/*.js
// files (HR/superadmin-only screens with no employee-facing self-service
// half — Recruitment, Onboarding/Offboarding, Audit Log, Users,
// Institutions, and several Settings pages), which are instead fetched on
// demand the first time their page is opened (Speed Audit item 7).
//
// Adding a new static/js/*.js file to the app: decide first whether it
// belongs here or in lazy-modules.js (only safe there if no role's
// personal/self-service screen depends on it — see that file's own
// comment), then add its filename in the position its dependencies
// require (same rule that governed where its <script> tag used to go),
// then run `npm run build:js`.
module.exports = [
  'list-state.js',
  'core.js',
  'employee-picker.js',
  'dashboard.js',
  'employees.js',
  'orgchart.js',
  'ld.js',
  'leave.js',
  'resignation.js',
  'timesheet.js',
  'notifications.js',
  'payroll.js',
  'compensation.js',
  'benefits.js',
  'attendance.js',
  'performance.js',
  'pip.js',
  'assistant.js',
  'app-init.js',
];

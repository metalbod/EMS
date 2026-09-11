// Ordered list of static/js/*.js files bundled into static/js/app.bundle.js
// by scripts/build-js.js. This is the single source of truth for load
// order now that index.html references the one bundle instead of a
// <script> tag per file — these are plain global-scope scripts (no
// import/export), so later files read state top-level earlier ones
// declared (core.js's `let employees`, etc), meaning THIS ORDER MATTERS
// and must stay exactly what index.html used to list.
//
// Adding a new static/js/*.js file to the app: add its filename here, in
// the position its dependencies require (same rule that governed where
// its <script> tag used to go), then run `npm run build:js`.
module.exports = [
  'list-state.js',
  'core.js',
  'employee-picker.js',
  'dashboard.js',
  'institutions.js',
  'employees.js',
  'orgchart.js',
  'audit.js',
  'users.js',
  'recruitment.js',
  'onboarding.js',
  'ld.js',
  'leave.js',
  'resignation.js',
  'approval-workflow.js',
  'roles.js',
  'employee-documents.js',
  'timesheet.js',
  'notifications.js',
  'payroll.js',
  'bulk-upload.js',
  'locations.js',
  'compensation.js',
  'benefits.js',
  'attendance.js',
  'performance.js',
  'pip.js',
  'assistant.js',
  'ai-assistant-settings.js',
  'app-init.js',
];

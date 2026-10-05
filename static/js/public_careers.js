// Public Careers — no-login job listing + application pages. Boot-time
// routing lives in app-init.js's own IIFE, which calls
// maybeShowPublicCareers() before deciding whether to show the login
// screen or the authenticated app shell; this file only renders once that
// decision has already been made in its favor. See routers/
// public_careers.py's module docstring for the backend side — same two
// endpoints serve both anonymous visitors and logged-in employees, so
// everything here uses plain fetch() (not core.js's api() helper, which
// assumes an authenticated session) and only ever reads an existing
// session token to prefill the form / tag the application, never requires
// one.
let careersResumeFile = null; // {file_name,mime_type,data_url} once a resume is selected

function maybeShowPublicCareers() {
  const applyMatch = window.location.pathname.match(/^\/careers\/apply\/([^/]+)\/?$/);
  if (applyMatch) {
    showPublicCareersShell();
    loadPublicApplyForm(applyMatch[1]);
    return true;
  }
  const listingMatch = window.location.pathname.match(/^\/careers\/([^/]+)\/?$/);
  if (listingMatch) {
    showPublicCareersShell();
    loadPublicCareersListing(listingMatch[1]);
    return true;
  }
  return false;
}

function showPublicCareersShell() {
  document.getElementById('loginScreen')?.classList.add('hidden');
  document.getElementById('appShell')?.classList.add('hidden');
  document.getElementById('publicCareersScreen').classList.remove('hidden');
}

async function loadPublicCareersListing(code) {
  document.getElementById('careersListingView').classList.remove('hidden');
  showGlobalLoading();
  let res;
  try { res = await fetch(`/api/public/careers/${encodeURIComponent(code)}`); }
  finally { hideGlobalLoading(); }
  if (!res.ok) { document.getElementById('careersListingNotFound').classList.remove('hidden'); return; }
  const data = await res.json();
  const list = document.getElementById('careersPositionsList');
  if (!data.positions.length) {
    document.getElementById('careersListingEmpty').classList.remove('hidden');
    return;
  }
  list.innerHTML = data.positions.map(p => `
    <a href="/careers/apply/${esc(p.public_token)}" class="block bg-white rounded-xl border border-slate-200 p-4 hover:border-blue-300 transition">
      <p class="font-semibold text-slate-800">${esc(p.title)}</p>
      <p class="text-sm text-slate-500">${esc(p.department)} · ${esc(p.employment_type)}</p>
    </a>`).join('');
}

async function loadPublicApplyForm(token) {
  document.getElementById('careersApplyView').classList.remove('hidden');
  showGlobalLoading();
  let res;
  try { res = await fetch(`/api/public/careers/apply/${encodeURIComponent(token)}`); }
  finally { hideGlobalLoading(); }
  if (!res.ok) { document.getElementById('careersApplyNotFound').classList.remove('hidden'); return; }
  const job = await res.json();
  document.getElementById('careersJobTitle').textContent = job.title;
  document.getElementById('careersJobMeta').textContent = `${job.department} · ${job.employment_type}`;
  document.getElementById('careersJobDescription').textContent = job.description || '';
  document.getElementById('careersApplyForm').classList.remove('hidden');
  if (job.turnstile_site_key) loadTurnstileWidget(job.turnstile_site_key);

  // Prefill from the logged-in employee's own profile, if any — a
  // convenience only; the submit endpoint works identically with or
  // without a session token (see routers/public_careers.py).
  const sessionToken = localStorage.getItem('token');
  if (!sessionToken) return;
  try {
    const me = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${sessionToken}` } });
    if (!me.ok) return;
    const u = await me.json();
    document.getElementById('careersFullName').value = u.full_name || '';
    document.getElementById('careersEmail').value = u.email || '';
  } catch (e) { /* best-effort only */ }
}

function loadTurnstileWidget(siteKey) {
  const widget = document.getElementById('careersTurnstileWidget');
  widget.dataset.sitekey = siteKey;
  if (document.getElementById('turnstileScript')) return;
  const s = document.createElement('script');
  s.id = 'turnstileScript';
  s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
  s.async = true; s.defer = true;
  document.head.appendChild(s);
}

function handleCareersResumeSelected(e) {
  const file = e.target.files?.[0];
  if (!file) { careersResumeFile = null; return; }
  const MAX_BYTES = 6 * 1024 * 1024;
  if (file.size > MAX_BYTES) {
    alert('File is too large. Please choose a file under ~6MB.');
    e.target.value = '';
    careersResumeFile = null;
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    careersResumeFile = { file_name: file.name, mime_type: file.type || 'application/octet-stream', data_url: reader.result };
    document.getElementById('careersResumeName').textContent = file.name;
  };
  reader.readAsDataURL(file);
}

async function submitPublicApplication(e) {
  e.preventDefault();
  const err = document.getElementById('careersApplyErr');
  err.classList.add('hidden');
  const match = window.location.pathname.match(/^\/careers\/apply\/([^/]+)\/?$/);
  const token = match ? match[1] : '';
  const body = {
    full_name: document.getElementById('careersFullName').value.trim(),
    email: document.getElementById('careersEmail').value.trim(),
    phone: document.getElementById('careersPhone').value || null,
    cover_note: document.getElementById('careersCoverNote').value || null,
    turnstile_token: window.turnstile ? window.turnstile.getResponse() : null,
  };
  if (careersResumeFile) {
    body.resume_file_name = careersResumeFile.file_name;
    body.resume_mime_type = careersResumeFile.mime_type;
    body.resume_data_url = careersResumeFile.data_url;
  }
  const headers = { 'Content-Type': 'application/json' };
  const sessionToken = localStorage.getItem('token');
  if (sessionToken) headers['Authorization'] = `Bearer ${sessionToken}`;

  showGlobalLoading();
  let res;
  try {
    res = await fetch(`/api/public/careers/apply/${encodeURIComponent(token)}`, {
      method: 'POST', headers, body: JSON.stringify(body),
    });
  } finally {
    hideGlobalLoading();
  }
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    err.textContent = d.detail || 'Something went wrong. Please try again.';
    err.classList.remove('hidden');
    if (window.turnstile) window.turnstile.reset();
    return;
  }
  document.getElementById('careersApplyForm').classList.add('hidden');
  document.getElementById('careersApplySuccess').classList.remove('hidden');
}

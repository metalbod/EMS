// ---------------------------------------------------------------------------
// Nav helpers — full-width labeled sidebar rail with accordion sub-menus.
// Sub-menus are collapsed by default and only expand when their group header
// is clicked.
// ---------------------------------------------------------------------------
let activeNavGroup = null;

function toggleNavGroup(name) {
  if (activeNavGroup === name) { collapseNavRail(); return; }
  document.querySelectorAll('.nav-submenu').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.nav-rail-btn').forEach(b => b.classList.remove('group-active'));
  document.querySelectorAll('.nav-rail-chevron').forEach(c => c.classList.remove('rot'));
  const panel = document.getElementById(`submenu-${name}`);
  if (!panel) return;
  panel.classList.remove('hidden');
  event?.currentTarget?.classList?.add('group-active');
  event?.currentTarget?.querySelector('.nav-rail-chevron')?.classList?.add('rot');
  activeNavGroup = name;
}

function collapseNavRail() {
  document.querySelectorAll('.nav-submenu').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.nav-rail-btn').forEach(b => b.classList.remove('group-active'));
  document.querySelectorAll('.nav-rail-chevron').forEach(c => c.classList.remove('rot'));
  activeNavGroup = null;
}

// Auto-collapse the open sub-menu when clicking anywhere outside the sidebar rail
document.addEventListener('click', e => {
  const rail = document.getElementById('sidebarRail');
  if (activeNavGroup && rail && !rail.contains(e.target)) collapseNavRail();
});

function esc(s) {
  return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---------------------------------------------------------------------------
// Active nav link styling
// ---------------------------------------------------------------------------
document.querySelectorAll('[data-page]').forEach(el => {
  const orig = el.className;
  el.addEventListener('click', () => {
    document.querySelectorAll('[data-page]').forEach(e => {
      e.style.background=''; e.style.color=''; e.style.fontWeight='';
    });
    el.style.background='#eff6ff'; el.style.color='#1d4ed8'; el.style.fontWeight='600';
  });
});


// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
(async()=>{
  const token=localStorage.getItem('token');
  if(!token) return;
  const res=await fetch('/api/auth/me',{headers:{Authorization:`Bearer ${token}`}});
  if(!res.ok){localStorage.removeItem('token');return;}
  currentUser=await res.json();
  bootApp();
})();

// ---------------------------------------------------------------------------

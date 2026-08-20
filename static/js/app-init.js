// ---------------------------------------------------------------------------
// Nav helpers — off-canvas burger drawer with accordion sub-menus.
// Sub-menus are collapsed by default and only expand when their group header
// is clicked. The whole drawer is closed after navigating to a page.
// ---------------------------------------------------------------------------
let activeNavGroup = null;

function toggleNavGroup(name) {
  if (activeNavGroup === name) { collapseNavGroups(); return; }
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

function collapseNavGroups() {
  document.querySelectorAll('.nav-submenu').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.nav-rail-btn').forEach(b => b.classList.remove('group-active'));
  document.querySelectorAll('.nav-rail-chevron').forEach(c => c.classList.remove('rot'));
  activeNavGroup = null;
}

// Below the lg breakpoint the sidebar is an off-canvas drawer (slide in/out);
// at lg and above it's a persistent column, so open/close are no-ops there —
// closeBurgerMenu() is called after every nav click regardless of viewport,
// and must not collapse the persistent desktop sidebar's expanded groups.
function openBurgerMenu() {
  document.getElementById('burgerDrawer').classList.remove('-translate-x-full');
  document.getElementById('navOverlay').classList.remove('hidden');
}

function closeBurgerMenu() {
  if (window.innerWidth >= 1024) return;
  document.getElementById('burgerDrawer').classList.add('-translate-x-full');
  document.getElementById('navOverlay').classList.add('hidden');
  collapseNavGroups();
}

function toggleBurgerMenu() {
  const isOpen = !document.getElementById('burgerDrawer').classList.contains('-translate-x-full');
  if (isOpen) closeBurgerMenu(); else openBurgerMenu();
}

function toggleUserMenu() {
  document.getElementById('userMenuDropdown').classList.toggle('hidden');
}
document.addEventListener('click', e => {
  if (!document.getElementById('userMenuWrap')?.contains(e.target))
    document.getElementById('userMenuDropdown')?.classList.add('hidden');
});

function esc(s) {
  return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Auto-linkifies bare http(s) URLs typed directly into free-text fields
// (notification messages, for a link an employee can click straight from
// the dashboard banner) — always escapes first, so this only ever wraps a
// URL pattern already-safe text found in already-escaped text in an
// anchor tag; it never trusts the source string as markup, unlike letting
// users type raw HTML would. Trims common trailing sentence punctuation
// (e.g. "See https://x.com." or "(https://x.com)") off the link itself so
// it isn't swallowed into the href.
function linkify(s) {
  return esc(s).replace(/(https?:\/\/[^\s<]+)/g, (url) => {
    const trailing = url.match(/[.,!?;:)\]]+$/);
    const href = trailing ? url.slice(0, -trailing[0].length) : url;
    const suffix = trailing ? trailing[0] : '';
    return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="underline hover:no-underline">${href}</a>${suffix}`;
  });
}

// ---------------------------------------------------------------------------
// Active nav link styling
// ---------------------------------------------------------------------------
document.querySelectorAll('[data-page]').forEach(el => {
  el.addEventListener('click', () => {
    document.querySelectorAll('[data-page]').forEach(e => e.classList.remove('active'));
    el.classList.add('active');
  });
});


installSubmitGuards();

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
(async()=>{
  const token=localStorage.getItem('token');
  if(!token) return;
  showGlobalLoading();
  let res;
  try {
    res=await fetch('/api/auth/me',{headers:{Authorization:`Bearer ${token}`}});
  } finally {
    hideGlobalLoading();
  }
  if(!res.ok){localStorage.removeItem('token');return;}
  currentUser=await res.json();
  bootApp();
})();

// ---------------------------------------------------------------------------

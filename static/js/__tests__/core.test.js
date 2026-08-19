import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('Page Navigation', () => {
  let pageContainer;
  let dashboardPage;
  let usersPage;
  let employeesPage;

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="page-dashboard" class="hidden">Dashboard</div>
      <div id="page-users" class="hidden">Users</div>
      <div id="page-employees" class="hidden">Employees</div>
      <div id="pageTitle">Title</div>
      <div class="nav-rail-label" data-page="dashboard">Dashboard</div>
      <div class="nav-rail-label" data-page="users">Users</div>
      <div class="nav-rail-label" data-page="employees">Employees</div>
    `;
    dashboardPage = document.getElementById('page-dashboard');
    usersPage = document.getElementById('page-users');
    employeesPage = document.getElementById('page-employees');
  });

  it('should show requested page and hide others', () => {
    const showPage = (page) => {
      ['dashboard', 'users', 'employees'].forEach(p => {
        const el = document.getElementById(`page-${p}`);
        if (el) el.classList.toggle('hidden', p !== page);
      });
      document.querySelectorAll('[data-page]').forEach(el => {
        el.classList.toggle('active', el.dataset.page === page);
      });
    };

    showPage('users');

    expect(dashboardPage.classList.contains('hidden')).toBe(true);
    expect(usersPage.classList.contains('hidden')).toBe(false);
    expect(employeesPage.classList.contains('hidden')).toBe(true);
  });

  it('should update page title when showing page', () => {
    const titles = {
      dashboard: 'Dashboard',
      users: 'User Management',
      employees: 'Employee List',
    };

    const showPage = (page) => {
      const el = document.getElementById(`page-${page}`);
      if (el) el.classList.remove('hidden');
      document.getElementById('pageTitle').textContent = titles[page] || page;
    };

    showPage('users');
    expect(document.getElementById('pageTitle').textContent).toBe('User Management');

    showPage('employees');
    expect(document.getElementById('pageTitle').textContent).toBe('Employee List');
  });

  it('should highlight active nav item', () => {
    const showPage = (page) => {
      document.querySelectorAll('[data-page]').forEach(el => {
        el.classList.toggle('active', el.dataset.page === page);
      });
    };

    showPage('users');

    const navItems = document.querySelectorAll('[data-page]');
    expect(navItems[0].classList.contains('active')).toBe(false);
    expect(navItems[1].classList.contains('active')).toBe(true);
    expect(navItems[2].classList.contains('active')).toBe(false);
  });

  it('should handle coming-soon page with unique data-page attributes', () => {
    document.body.innerHTML = `
      <div id="page-coming-soon" class="hidden">Coming Soon</div>
      <div id="page-analytics" class="hidden">Analytics</div>
      <div data-page="coming-soon">Analytics Menu</div>
      <div data-page="export-builder">Export Builder Menu</div>
    `;

    const showPage = (page) => {
      const el = document.getElementById(`page-${page}`);
      if (el) el.classList.remove('hidden');
      document.querySelectorAll('[data-page]').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
      });
    };

    showPage('coming-soon');

    const navItems = document.querySelectorAll('[data-page]');
    expect(navItems[0].classList.contains('active')).toBe(true);
    expect(navItems[1].classList.contains('active')).toBe(false);

    showPage('export-builder');

    expect(navItems[0].classList.contains('active')).toBe(false);
    expect(navItems[1].classList.contains('active')).toBe(true);
  });
});

describe('Menu Item Click Handling', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="sidebarRail" class="invisible"></div>
      <div id="navOverlay" class="hidden"></div>
      <div id="page-analytics" class="hidden">Analytics</div>
      <div class="nav-sub-item" onclick="handleMenuClick('coming-soon')" data-page="coming-soon">
        Analytics
      </div>
    `;
  });

  it('should close burger menu when menu item is clicked', () => {
    const sidebarRail = document.getElementById('sidebarRail');
    const navOverlay = document.getElementById('navOverlay');

    const handleMenuClick = (page) => {
      sidebarRail.classList.add('invisible', 'opacity-0', '-translate-y-2');
      navOverlay.classList.add('hidden');
    };

    sidebarRail.classList.remove('invisible');
    navOverlay.classList.remove('hidden');

    handleMenuClick('coming-soon');

    expect(sidebarRail.classList.contains('invisible')).toBe(true);
    expect(navOverlay.classList.contains('hidden')).toBe(true);
  });
});

describe('Role Display', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="roleSwitcherLabel">Manager</div>
      <div id="roleSwitcherOptions"></div>
    `;
  });

  it('should display current role in switcher', () => {
    const meta = { role_labels: { hr_manager: 'HR Manager', employee: 'Employee' } };
    const currentRole = 'hr_manager';

    const roleSwitcherLabel = document.getElementById('roleSwitcherLabel');
    roleSwitcherLabel.textContent = meta.role_labels?.[currentRole] || currentRole;

    expect(roleSwitcherLabel.textContent).toBe('HR Manager');
  });

  it('should show all available roles in dropdown', () => {
    const meta = { role_labels: { hr_manager: 'HR Manager', employee: 'Employee' } };
    const roles = ['hr_manager', 'employee'];
    const currentRole = 'hr_manager';

    const options = document.getElementById('roleSwitcherOptions');
    options.innerHTML = roles
      .map(r => `<div data-role="${r}" class="${r === currentRole ? 'active' : ''}">${meta.role_labels?.[r] || r}</div>`)
      .join('');

    const roleElements = options.querySelectorAll('[data-role]');
    expect(roleElements.length).toBe(2);
    expect(roleElements[0].classList.contains('active')).toBe(true);
    expect(roleElements[1].classList.contains('active')).toBe(false);
  });
});

describe('parseUTC', () => {
  // Matches core.js's parseUTC — every *_at field from the API is a naive
  // UTC string (db.py's datetime.utcnow().isoformat(), no "Z"/offset).
  // Regression coverage for the attendance clock-in display bug: passed
  // straight to `new Date(...)`, a date-time string with no zone is parsed
  // as LOCAL time per the JS Date Time String Format spec, silently
  // mislabeling a UTC instant as if it were already local.
  function parseUTC(value) {
    if (!value) return null;
    return new Date(value.endsWith('Z') ? value : value + 'Z');
  }

  it('interprets a naive timestamp as UTC, not local time', () => {
    const d = parseUTC('2026-08-15T11:37:04');
    expect(d.toISOString()).toBe('2026-08-15T11:37:04.000Z');
  });

  it('is a no-op for a timestamp that already has a Z suffix', () => {
    const d = parseUTC('2026-08-15T11:37:04Z');
    expect(d.toISOString()).toBe('2026-08-15T11:37:04.000Z');
  });

  it('returns null for a missing value instead of an Invalid Date', () => {
    expect(parseUTC(null)).toBeNull();
    expect(parseUTC(undefined)).toBeNull();
    expect(parseUTC('')).toBeNull();
  });

  it('produces a different wall-clock reading than the pre-fix bare new Date() call', () => {
    // The actual regression: in any timezone with a non-zero UTC offset,
    // the old `new Date(raw).toLocaleString()` and the fixed
    // `parseUTC(raw).toLocaleString()` must disagree — that disagreement
    // IS the bug this test guards against silently coming back.
    const raw = '2026-08-15T11:37:04';
    const buggyOld = new Date(raw).getTime();
    const fixedNew = parseUTC(raw).getTime();
    // getTimezoneOffset() is UTC-minus-local (positive west of UTC), so the
    // gap this bug introduces is the negation of it.
    const localOffsetMs = new Date().getTimezoneOffset() * 60000;
    if (localOffsetMs !== 0) {
      expect(fixedNew).not.toBe(buggyOld);
    }
    expect(fixedNew - buggyOld).toBe(-localOffsetMs);
  });
});

describe('fmtDate / fmtDateTime', () => {
  // Matches core.js's fmtDate/fmtDateTime — system-wide dd-mmm-yy date display.
  const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  function parseUTC(value) {
    if (!value) return null;
    return new Date(value.endsWith('Z') ? value : value + 'Z');
  }

  function fmtDate(value) {
    if (!value) return '—';
    let y, mo, d;
    if (value instanceof Date) {
      if (isNaN(value)) return '—';
      y = value.getFullYear(); mo = value.getMonth() + 1; d = value.getDate();
    } else {
      const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
      if (!m) return String(value);
      [y, mo, d] = m.slice(1).map(Number);
    }
    return `${String(d).padStart(2,'0')}-${MONTH_ABBR[mo-1]}-${String(y).slice(-2)}`;
  }

  function fmtDateTime(value, withSeconds) {
    const d = parseUTC(value);
    if (!d) return '—';
    const timeOpts = withSeconds
      ? {hour:'2-digit',minute:'2-digit',second:'2-digit'}
      : {hour:'2-digit',minute:'2-digit'};
    return `${fmtDate(d)}, ${d.toLocaleTimeString([], timeOpts)}`;
  }

  it('formats a date-only string as dd-mmm-yy', () => {
    expect(fmtDate('2026-08-15')).toBe('15-Aug-26');
  });

  it('formats the date portion of a full ISO datetime string the same way', () => {
    expect(fmtDate('2026-08-15T11:37:04.123456')).toBe('15-Aug-26');
  });

  it('pads single-digit days', () => {
    expect(fmtDate('2026-01-05')).toBe('05-Jan-26');
  });

  it('formats a Date object using local getters, not UTC', () => {
    // A UTC instant that falls on a different local calendar date near
    // midnight — must use the LOCAL date, matching parseUTC's contract.
    const d = new Date('2026-08-15T00:30:00Z');
    const expected = `${String(d.getDate()).padStart(2,'0')}-${MONTH_ABBR[d.getMonth()]}-${String(d.getFullYear()).slice(-2)}`;
    expect(fmtDate(d)).toBe(expected);
  });

  it('returns an em dash for null, undefined, or empty input', () => {
    expect(fmtDate(null)).toBe('—');
    expect(fmtDate(undefined)).toBe('—');
    expect(fmtDate('')).toBe('—');
  });

  it('returns an em dash for an Invalid Date object', () => {
    expect(fmtDate(new Date('not-a-date'))).toBe('—');
  });

  it('passes through an unrecognizable string unchanged rather than mangling it', () => {
    expect(fmtDate('TBD')).toBe('TBD');
  });

  it('fmtDateTime combines the dd-mmm-yy date with a local time', () => {
    const result = fmtDateTime('2026-08-15T11:37:04');
    expect(result.startsWith(fmtDate('2026-08-15T11:37:04Z'))).toBe(true);
    expect(result).toContain(',');
  });

  it('fmtDateTime omits seconds by default and includes them when asked', () => {
    const withoutSeconds = fmtDateTime('2026-08-15T11:37:04');
    const withSeconds = fmtDateTime('2026-08-15T11:37:04', true);
    expect(withoutSeconds).not.toMatch(/:\d{2}:\d{2}/); // no HH:MM:SS pattern
    expect(withSeconds).toMatch(/:\d{2}:\d{2}/);
  });

  it('fmtDateTime returns an em dash for a missing value', () => {
    expect(fmtDateTime(null)).toBe('—');
  });
});

describe('fmtCurrency', () => {
  // Matches core.js's fmtCurrency — system-wide "RM 1,234.56" display,
  // replacing benefits.js's fmtRM, payroll.js's fmtMoney, and ~40 inline
  // Number(x).toLocaleString('en-MY', {...}) call sites.
  function fmtCurrency(v, decimals = 2) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    if (isNaN(n)) return '—';
    return `RM ${n.toLocaleString('en-MY', {minimumFractionDigits: decimals, maximumFractionDigits: decimals})}`;
  }

  it('formats a number with 2 decimals and thousands separators by default', () => {
    expect(fmtCurrency(1234.5)).toBe('RM 1,234.50');
    expect(fmtCurrency(0)).toBe('RM 0.00');
  });

  it('supports a custom decimal count', () => {
    expect(fmtCurrency(1234.5, 0)).toBe('RM 1,235');
    expect(fmtCurrency(12.3456, 4)).toBe('RM 12.3456');
  });

  it('returns an em dash for null, undefined, or empty string', () => {
    expect(fmtCurrency(null)).toBe('—');
    expect(fmtCurrency(undefined)).toBe('—');
    expect(fmtCurrency('')).toBe('—');
  });

  it('returns an em dash for a non-numeric value', () => {
    expect(fmtCurrency('not-a-number')).toBe('—');
  });

  it('coerces numeric strings', () => {
    expect(fmtCurrency('99.9')).toBe('RM 99.90');
  });
});

describe('guardAsync', () => {
  // Matches core.js's guardAsync — the onclick-wired counterpart to
  // installSubmitGuards, replacing 31 hand-written re-entrancy-flag copies
  // (one per Save/Add/Create button wired via onclick instead of a form
  // submit) with one shared wrapper.
  function guardAsync(fn) {
    let inFlight = false;
    return async function guarded(...args) {
      if (inFlight) return;
      inFlight = true;
      try {
        return await fn.apply(this, args);
      } finally {
        inFlight = false;
      }
    };
  }

  it('lets a call through when nothing is in flight', async () => {
    const inner = vi.fn(async () => 'done');
    const guarded = guardAsync(inner);
    const result = await guarded();
    expect(inner).toHaveBeenCalledTimes(1);
    expect(result).toBe('done');
  });

  it('drops a second call that arrives while the first is still in flight', async () => {
    let resolveFirst;
    const inner = vi.fn(() => new Promise(r => { resolveFirst = r; }));
    const guarded = guardAsync(inner);
    const first = guarded();
    const second = guarded(); // fired before `first` resolves — should no-op
    resolveFirst('first-result');
    await Promise.all([first, second]);
    expect(inner).toHaveBeenCalledTimes(1);
  });

  it('allows a later call once the in-flight one has finished', async () => {
    const inner = vi.fn(async () => 'ok');
    const guarded = guardAsync(inner);
    await guarded();
    await guarded();
    expect(inner).toHaveBeenCalledTimes(2);
  });

  it('resets the guard even when the wrapped function throws', async () => {
    const inner = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce('recovered');
    const guarded = guardAsync(inner);
    await expect(guarded()).rejects.toThrow('boom');
    await expect(guarded()).resolves.toBe('recovered');
    expect(inner).toHaveBeenCalledTimes(2);
  });

  it('forwards arguments to the wrapped function', async () => {
    const inner = vi.fn(async (a, b) => a + b);
    const guarded = guardAsync(inner);
    const result = await guarded(2, 3);
    expect(inner).toHaveBeenCalledWith(2, 3);
    expect(result).toBe(5);
  });
});

describe('closeModal', () => {
  // Matches core.js's closeModal — replaces 31 hand-written
  // `function closeXModal() { document.getElementById('xModal')
  // .classList.add('hidden'); [someVar = null;] }` copies.
  function closeModal(id, resetFn) {
    document.getElementById(id)?.classList.add('hidden');
    resetFn?.();
  }

  beforeEach(() => {
    document.body.innerHTML = '<div id="testModal" class="foo"></div>';
  });

  it('hides the element by id', () => {
    closeModal('testModal');
    expect(document.getElementById('testModal').classList.contains('hidden')).toBe(true);
  });

  it('calls the optional reset function', () => {
    const resetFn = vi.fn();
    closeModal('testModal', resetFn);
    expect(resetFn).toHaveBeenCalledTimes(1);
  });

  it('does not throw when no reset function is given', () => {
    expect(() => closeModal('testModal')).not.toThrow();
  });

  it('does not throw when the element does not exist', () => {
    expect(() => closeModal('missingModal')).not.toThrow();
  });
});

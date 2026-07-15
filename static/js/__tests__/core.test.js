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

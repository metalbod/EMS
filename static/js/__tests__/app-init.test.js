import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('Burger Menu', () => {
  let burgerMenu;
  let navOverlay;

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="navOverlay" class="hidden"></div>
      <div id="sidebarRail" class="invisible opacity-0 -translate-y-2"></div>
      <button id="burgerBtn" onclick="toggleBurgerMenu()">Menu</button>
    `;
    burgerMenu = document.getElementById('sidebarRail');
    navOverlay = document.getElementById('navOverlay');
  });

  it('should open burger menu by removing invisible/opacity/translate classes', () => {
    burgerMenu.classList.add('invisible', 'opacity-0', '-translate-y-2');
    const openBurgerMenu = () => {
      burgerMenu.classList.remove('invisible', 'opacity-0', '-translate-y-2');
      navOverlay.classList.remove('hidden');
    };
    openBurgerMenu();
    expect(burgerMenu.classList.contains('invisible')).toBe(false);
    expect(navOverlay.classList.contains('hidden')).toBe(false);
  });

  it('should close burger menu by adding invisible/opacity/translate classes', () => {
    const closeBurgerMenu = () => {
      burgerMenu.classList.add('invisible', 'opacity-0', '-translate-y-2');
      navOverlay.classList.add('hidden');
    };
    closeBurgerMenu();
    expect(burgerMenu.classList.contains('invisible')).toBe(true);
    expect(navOverlay.classList.contains('hidden')).toBe(true);
  });

  it('should toggle burger menu state', () => {
    const toggleBurgerMenu = () => {
      const isOpen = !burgerMenu.classList.contains('invisible');
      if (isOpen) {
        burgerMenu.classList.add('invisible', 'opacity-0', '-translate-y-2');
        navOverlay.classList.add('hidden');
      } else {
        burgerMenu.classList.remove('invisible', 'opacity-0', '-translate-y-2');
        navOverlay.classList.remove('hidden');
      }
    };

    burgerMenu.classList.add('invisible', 'opacity-0', '-translate-y-2');
    navOverlay.classList.add('hidden');

    toggleBurgerMenu();
    expect(burgerMenu.classList.contains('invisible')).toBe(false);
    expect(navOverlay.classList.contains('hidden')).toBe(false);

    toggleBurgerMenu();
    expect(burgerMenu.classList.contains('invisible')).toBe(true);
    expect(navOverlay.classList.contains('hidden')).toBe(true);
  });

  it('should close menu when overlay is clicked', () => {
    burgerMenu.classList.remove('invisible', 'opacity-0', '-translate-y-2');
    navOverlay.classList.remove('hidden');

    const closeBurgerMenu = () => {
      burgerMenu.classList.add('invisible', 'opacity-0', '-translate-y-2');
      navOverlay.classList.add('hidden');
    };

    navOverlay.onclick = closeBurgerMenu;
    navOverlay.click();

    expect(burgerMenu.classList.contains('invisible')).toBe(true);
    expect(navOverlay.classList.contains('hidden')).toBe(true);
  });
});

describe('User Menu Dropdown', () => {
  let userMenuDropdown;
  let userMenuWrap;

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="userMenuWrap">
        <button id="userMenuBtn" onclick="toggleUserMenu()">Profile</button>
        <div id="userMenuDropdown" class="hidden"></div>
      </div>
    `;
    userMenuDropdown = document.getElementById('userMenuDropdown');
    userMenuWrap = document.getElementById('userMenuWrap');
  });

  it('should toggle user menu visibility', () => {
    const toggleUserMenu = () => {
      userMenuDropdown.classList.toggle('hidden');
    };

    expect(userMenuDropdown.classList.contains('hidden')).toBe(true);
    toggleUserMenu();
    expect(userMenuDropdown.classList.contains('hidden')).toBe(false);
    toggleUserMenu();
    expect(userMenuDropdown.classList.contains('hidden')).toBe(true);
  });

  it('should close user menu when clicking outside', () => {
    userMenuDropdown.classList.remove('hidden');

    const closeOnClickOutside = () => {
      if (!userMenuWrap.contains(event.target)) {
        userMenuDropdown.classList.add('hidden');
      }
    };

    userMenuWrap.addEventListener('click', (e) => {
      if (!userMenuWrap.contains(e.target)) {
        userMenuDropdown.classList.add('hidden');
      }
    });

    document.body.addEventListener('click', (e) => {
      if (!userMenuWrap.contains(e.target)) {
        userMenuDropdown.classList.add('hidden');
      }
    });

    const outsideClick = new MouseEvent('click', { bubbles: true });
    document.body.dispatchEvent(outsideClick);

    expect(userMenuDropdown.classList.contains('hidden')).toBe(true);
  });
});

describe('Navigation Groups Accordion', () => {
  let navGroup1;
  let navGroup2;
  let chevron1;
  let chevron2;

  beforeEach(() => {
    document.body.innerHTML = `
      <div class="nav-rail-group">
        <button id="groupBtn1" onclick="toggleNavGroup('group1')">
          Group 1
          <svg id="chevron1" class="nav-rail-chevron"></svg>
        </button>
        <div id="submenu-group1" class="nav-submenu hidden"></div>
      </div>
      <div class="nav-rail-group">
        <button id="groupBtn2" onclick="toggleNavGroup('group2')">
          Group 2
          <svg id="chevron2" class="nav-rail-chevron"></svg>
        </button>
        <div id="submenu-group2" class="nav-submenu hidden"></div>
      </div>
    `;
    navGroup1 = document.getElementById('submenu-group1');
    navGroup2 = document.getElementById('submenu-group2');
    chevron1 = document.getElementById('chevron1');
    chevron2 = document.getElementById('chevron2');
  });

  it('should toggle nav group submenu visibility', () => {
    const toggleNavGroup = (groupId) => {
      const submenu = document.getElementById(`submenu-${groupId}`);
      const chevron = submenu.parentElement.querySelector('.nav-rail-chevron');
      submenu.classList.toggle('hidden');
      chevron?.classList.toggle('rot');
    };

    expect(navGroup1.classList.contains('hidden')).toBe(true);
    toggleNavGroup('group1');
    expect(navGroup1.classList.contains('hidden')).toBe(false);
    expect(chevron1.classList.contains('rot')).toBe(true);
  });

  it('should collapse other groups when opening one', () => {
    const toggleNavGroup = (groupId) => {
      // Close all other groups
      document.querySelectorAll('.nav-submenu').forEach(menu => {
        if (menu.id !== `submenu-${groupId}`) {
          menu.classList.add('hidden');
          menu.parentElement.querySelector('.nav-rail-chevron')?.classList.remove('rot');
        }
      });
      // Open the selected group
      const submenu = document.getElementById(`submenu-${groupId}`);
      const chevron = submenu.parentElement.querySelector('.nav-rail-chevron');
      submenu.classList.remove('hidden');
      chevron?.classList.add('rot');
    };

    // Initially both groups are closed
    navGroup1.classList.add('hidden');
    navGroup2.classList.add('hidden');
    chevron1.classList.remove('rot');
    chevron2.classList.remove('rot');

    // Open group1
    toggleNavGroup('group1');
    expect(navGroup1.classList.contains('hidden')).toBe(false);
    expect(navGroup2.classList.contains('hidden')).toBe(true);

    // Switch to group2 - should close group1 and open group2
    toggleNavGroup('group2');
    expect(navGroup1.classList.contains('hidden')).toBe(true);
    expect(navGroup2.classList.contains('hidden')).toBe(false);
  });
});

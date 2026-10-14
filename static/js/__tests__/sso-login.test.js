import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Runs the REAL Microsoft-sign-in pieces from core.js (login screen) and sso-settings.js (Settings page).
const core = readFileSync(resolve(__dirname, '..', 'core.js'), 'utf8');
const start = core.indexOf('const SSO_ERROR_MESSAGES');
const end = core.indexOf('if (document.getElementById(\'loginCode\')?.value) refreshSsoButton();');
const settings = readFileSync(resolve(__dirname, '..', 'sso-settings.js'), 'utf8');
const ssoStatus = new Function(`${settings.slice(settings.indexOf('function ssoStatus('), settings.indexOf('function renderSsoSettings('))}\nreturn ssoStatus;`)();

function loadLogin(fetchImpl) {
  const ctx = { fetch: fetchImpl, showGlobalLoading() {}, hideGlobalLoading() {}, bootApp: vi.fn(), localStorage: { setItem: vi.fn() }, history: { replaceState: vi.fn() }, currentUser: null };
  const fn = new Function('fetch', 'showGlobalLoading', 'hideGlobalLoading', 'bootApp', 'localStorage', 'history', 'location',
    `let currentUser = null;\n${core.slice(start, end)}\nreturn { ssoErrorMessage, refreshSsoButton, handleSsoReturn, getUser: () => currentUser };`);
  return { ctx, api: (loc) => fn(ctx.fetch, ctx.showGlobalLoading, ctx.hideGlobalLoading, ctx.bootApp, ctx.localStorage, ctx.history, loc) };
}

beforeEach(() => {
  document.body.innerHTML = `<input id="loginCode" value=""/><div id="loginSsoWrap" class="hidden"></div><p id="loginErr" class="hidden"></p>`;
});

describe('ssoErrorMessage', () => {
  it('says something plain for every code the server can send, and a safe default for an unknown one', () => {
    const { api } = loadLogin(vi.fn());
    const { ssoErrorMessage } = api({ search: '', pathname: '/', hash: '' });
    for (const c of ['not_enabled', 'failed', 'expired', 'denied', 'no_account', 'inactive', 'suspended']) expect(ssoErrorMessage(c)).toMatch(/\w+/);
    expect(ssoErrorMessage('no_account')).toContain('Ask HR');
    expect(ssoErrorMessage('who-knows')).toBe(ssoErrorMessage('failed'));
  });
});

describe('the Microsoft button', () => {
  it('shows only when the typed company code has it on, and hides again for a blank code', async () => {
    const fetchImpl = vi.fn(async url => ({ ok: true, json: async () => ({ sso_enabled: url.includes('ACME') }) }));
    const { api } = loadLogin(fetchImpl);
    const { refreshSsoButton } = api({ search: '', pathname: '/', hash: '' });
    const wrap = document.getElementById('loginSsoWrap');
    document.getElementById('loginCode').value = 'ACME';
    await refreshSsoButton();
    expect(wrap.classList.contains('hidden')).toBe(false);
    document.getElementById('loginCode').value = 'OTHER';
    await refreshSsoButton();
    expect(wrap.classList.contains('hidden')).toBe(true);
    document.getElementById('loginCode').value = '';
    await refreshSsoButton();
    expect(wrap.classList.contains('hidden')).toBe(true);
  });

  it('stays hidden if the lookup fails', async () => {
    const { api } = loadLogin(vi.fn(async () => { throw new Error('offline'); }));
    const { refreshSsoButton } = api({ search: '', pathname: '/', hash: '' });
    document.getElementById('loginCode').value = 'ACME';
    await refreshSsoButton();
    expect(document.getElementById('loginSsoWrap').classList.contains('hidden')).toBe(true);
  });
});

describe('coming back from Microsoft', () => {
  it('does nothing on a normal page load', async () => {
    const { api } = loadLogin(vi.fn());
    expect(await api({ search: '', pathname: '/', hash: '' }).handleSsoReturn()).toBe(false);
  });

  it('shows the reason and cleans the address when Microsoft sign-in failed', async () => {
    const { ctx, api } = loadLogin(vi.fn());
    const loc = { search: '?sso_error=no_account', pathname: '/', hash: '#dashboard' };
    expect(await api(loc).handleSsoReturn()).toBe(true);
    expect(document.getElementById('loginErr').textContent).toContain('Ask HR');
    expect(document.getElementById('loginErr').classList.contains('hidden')).toBe(false);
    expect(ctx.history.replaceState).toHaveBeenCalledWith(null, '', '/#dashboard');   // the query string is gone
  });

  it('trades the one-time code for a session, removes it from the address, and boots the app', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ access_token: 'tok', user: { username: 'amirah' } }) }));
    const { ctx, api } = loadLogin(fetchImpl);
    expect(await api({ search: '?sso_code=abc123', pathname: '/', hash: '' }).handleSsoReturn()).toBe(true);
    expect(ctx.history.replaceState).toHaveBeenCalledWith(null, '', '/');
    expect(fetchImpl).toHaveBeenCalledWith('/api/auth/sso/exchange', expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: 'abc123' }) }));
    expect(ctx.localStorage.setItem).toHaveBeenCalledWith('token', 'tok');
    expect(ctx.bootApp).toHaveBeenCalled();
  });

  it('shows the server message when the code has expired', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: false, json: async () => ({ detail: 'That sign-in link has expired. Please try again.' }) }));
    const { ctx, api } = loadLogin(fetchImpl);
    await api({ search: '?sso_code=old', pathname: '/', hash: '' }).handleSsoReturn();
    expect(document.getElementById('loginErr').textContent).toContain('expired');
    expect(ctx.bootApp).not.toHaveBeenCalled();
    expect(ctx.localStorage.setItem).not.toHaveBeenCalled();
  });
});

describe('SSO settings status badge', () => {
  it('walks not set up, saved, tested, on', () => {
    expect(ssoStatus({ configured: false }).text).toBe('Not set up');
    expect(ssoStatus({ configured: true, enabled: false, last_test_ok: false }).text).toBe('Saved, not tested');
    expect(ssoStatus({ configured: true, enabled: false, last_test_ok: true }).text).toBe('Tested, off');
    expect(ssoStatus({ configured: true, enabled: true, last_test_ok: true }).text).toBe('On');
  });
});

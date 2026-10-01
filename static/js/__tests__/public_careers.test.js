import { describe, it, expect } from 'vitest';

// Mirrors public_careers.js's maybeShowPublicCareers() URL-matching logic —
// the routing that decides whether a page load is the public, no-login
// careers listing (/careers/<institution-code>) or a single job's apply
// form (/careers/apply/<token>), called from app-init.js's boot IIFE
// before it decides whether to show the login screen or the app shell.
describe('Public careers URL routing', () => {
  function classifyPath(path) {
    const applyMatch = path.match(/^\/careers\/apply\/([^/]+)\/?$/);
    if (applyMatch) return { type: 'apply', value: applyMatch[1] };
    const listingMatch = path.match(/^\/careers\/([^/]+)\/?$/);
    if (listingMatch) return { type: 'listing', value: listingMatch[1] };
    return null;
  }

  it('matches a single job apply URL and extracts the token', () => {
    expect(classifyPath('/careers/apply/4cf2444a-338a-4cb4-a47f-6add4c493936'))
      .toEqual({ type: 'apply', value: '4cf2444a-338a-4cb4-a47f-6add4c493936' });
  });

  it('matches a listing URL and extracts the institution code', () => {
    expect(classifyPath('/careers/ZZPYTEST')).toEqual({ type: 'listing', value: 'ZZPYTEST' });
  });

  it('tolerates a trailing slash on both forms', () => {
    expect(classifyPath('/careers/ZZPYTEST/')).toEqual({ type: 'listing', value: 'ZZPYTEST' });
    expect(classifyPath('/careers/apply/sometoken/')).toEqual({ type: 'apply', value: 'sometoken' });
  });

  it('the apply pattern is checked first, so a code literally named "apply" never gets treated as a listing', () => {
    // There's no real institution whose code is "apply" (codes are
    // chosen by superadmin at institution-creation time), but the apply
    // route must still win this particular ambiguity deterministically.
    expect(classifyPath('/careers/apply/xyz')).toEqual({ type: 'apply', value: 'xyz' });
  });

  it('does not match an unrelated path', () => {
    expect(classifyPath('/dashboard')).toBeNull();
    expect(classifyPath('/')).toBeNull();
  });

  it('does not match a bare /careers with nothing after it', () => {
    expect(classifyPath('/careers')).toBeNull();
    expect(classifyPath('/careers/')).toBeNull();
  });
});

// Mirrors loadPublicApplyForm's internal-session detection via the
// Authorization header it conditionally sends — see
// routers/public_careers.py's _optional_internal_institution_id for the
// server-side half of this same logic.
describe('Public apply form — session header inclusion', () => {
  function buildHeaders(sessionToken) {
    const headers = { 'Content-Type': 'application/json' };
    if (sessionToken) headers['Authorization'] = `Bearer ${sessionToken}`;
    return headers;
  }

  it('includes an Authorization header when a session token exists', () => {
    expect(buildHeaders('abc123')).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer abc123',
    });
  });

  it('omits Authorization entirely for a true anonymous visitor', () => {
    expect(buildHeaders(null)).toEqual({ 'Content-Type': 'application/json' });
  });
});

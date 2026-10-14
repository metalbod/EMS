# Sign in with Microsoft (Entra ID) — setup

Each company connects **its own** Entra app registration; EMS stores nothing shared between companies. Microsoft sign-in
works **alongside** passwords unless you choose to require it (section 4). By default nobody is created by signing in — a
Microsoft account must match a user HR has already set up in EMS (section 5 has opt-in alternatives).

## 1. In Microsoft Entra (your Entra admin)
1. **App registrations → New registration.** Name: `EMS`. Supported account types: **Accounts in this organizational
   directory only (single tenant)**.
2. **Redirect URI**: platform **Web**, value `https://<your EMS address>/api/auth/sso/callback`
   (production: `https://ems-app.fly.dev/api/auth/sso/callback`; for local testing also
   `http://localhost:8010/api/auth/sso/callback`). The exact address is shown on the EMS settings page.
3. **Certificates & secrets → New client secret.** Copy the secret **Value** at once (shown once). It expires (at most
   24 months): put a reminder in a calendar — when it lapses Microsoft sign-in stops until a new secret is saved in EMS.
4. **API permissions**: keep only Microsoft Graph delegated `openid`, `profile`, `email` (remove `User.Read`).
5. **Token configuration → Add optional claim → ID**: add `email` and `upn`.
6. From **Overview** note the **Directory (tenant) ID** and **Application (client) ID**.

## 2. In EMS (HR Manager)
**Settings → Single Sign-On**: enter the tenant ID, client ID and secret → **Save** → **Test sign-in** (signs you in to
Microsoft once; changes nothing for anyone else) → tick **Show Sign in with Microsoft on the login screen**. The switch can
only be turned on after a successful test, and changing any of the three values turns it off again.

## 3. How people are matched
First Microsoft sign-in: the account's email / UPN is matched to **exactly one** EMS user, by the user's email or by the work
email on their linked employee record. That links the Entra identity (tenant id + object id) to the user; afterwards the
identity is what counts, so a changed email doesn't break it. No match, two matches, or an account already linked to a
different Microsoft identity → "Your Microsoft account isn't set up in EMS yet". HR can **Unlink Microsoft** on a user
(Users page) so the next sign-in matches by email again.

## Notes
- Roles and access stay managed in EMS; MFA and conditional access stay in Entra.
- Deactivating a user in EMS stops their Microsoft sign-in at once. An EMS session already open lasts up to 8 hours.
- Every sign-in is in the login audit log with reason `sso`; settings changes, links and unlinks are in the activity log.

## 4. Requiring Microsoft sign-in (optional)
**Settings → Single Sign-On → Require Microsoft sign-in.** Once on, `/api/auth/login` refuses passwords for everyone except
platform admins and people marked **Emergency password access** (Users → Edit user; HR Manager only). Do this in order:
1. Let everyone sign in with Microsoft at least once (the page shows "N of M users have signed in").
2. Mark **one or two** trusted people for emergency password access — they are your way in if Microsoft or the client secret
   has a problem. EMS refuses to turn the requirement on until at least one exists, and until you yourself have signed in with
   Microsoft or hold emergency access.
3. People with no email address can never be matched; EMS lists them and asks you to confirm.
Turning Microsoft sign-in off also turns the requirement off. Reading and acknowledging a **policy** normally confirms with the
login password; while passwords are off, people are sent through Microsoft once more ("Confirm with Microsoft") and the
acknowledgement records that method.

## 5. Accounts and roles (optional, off by default)
- **Create the EMS account on first Microsoft sign-in** — only when the Microsoft email is the **work email** of exactly one
  active employee who has no login yet. They get the basic Employee role; anyone else is still refused.
- **Set roles from Entra groups** — map an Entra security group's **Object ID** to an EMS role. At each sign-in the person's EMS
  roles follow the mapped groups they belong to. Nothing changes for someone in no mapped group, for emergency-access people, or
  when Microsoft's token has no group list. In the app registration open **Token configuration → Add groups claim → Security
  groups → Group ID**. If a person is in more than 200 groups Microsoft omits the list from the token; EMS then leaves their roles
  alone (it does not call Microsoft Graph). Superadmin can't be assigned from a group. The **Test sign-in** result tells you how many
  groups the token carried.

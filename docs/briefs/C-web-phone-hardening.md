# Brief C: web app phone and durability hardening

**For:** Claude Code · **Written:** 2026-10-23 by Claude · **PR base:** the latest reviewed branch (after A, ideally after B)

## Why

Soul's review of PR #5 (2026-10-21) named the hosted web app (`laylaw/web`) as the primary path for
Chelsea on her phone and listed seven items before real mobile use. Item 1 (draft autosave tied to the
question) is done in `e72f64b`. Item 7 needs a host. This brief covers items 2–6.

## Read first

Soul's comments on PR #5 and PR #11 (GitHub), `HANDOFF.md` section 2, `SECURITY.md` (web app),
`laylaw/web/` (app.py, accounts.py, templates, static/app.js, app.css), `tests/test_web_security.py`,
and PR #11's screens: `laylaw/app/intake_pages.py`, `docs/INTAKE.md`, `docs/screenshots/intake/`.

## Build

1. **Saving when the page closes (Soul item 2).** On `pagehide` and `visibilitychange`, send the
   draft with `fetch(..., {keepalive: true})` where supported. Never say "saved" until the server
   confirms. Keep the CSRF and question-revision checks; the existing 409 on a stale save stays.
2. **Visible save state (item 3).** Near the answer box, show *Saving…*, *Saved at 3:42 PM* and
   *Offline: not saved*, with automatic retry on reconnect. Also show *Session expired: sign in again
   (your text is kept on this page)* and *Changed on another device*. Nothing goes in localStorage,
   sessionStorage or IndexedDB: that rule and its CI check stay. Say plainly in the UI copy that
   offline text isn't stored until it's sent.
3. **PR #11's phone design in the web app (item 4).** Port, don't reinvent:
   - progress and section label
   - choice cards
   - 44px minimum tap targets
   - explicit Back and Save for later
   - a review page with "Change" per answer
   - plain-language upload copy
   - tables that don't scroll sideways
   Keep the strict CSP: no inline script or style. Check at 320, 360 and 390px wide with Playwright and
   Chromium (pre-installed at `/opt/pw-browsers/chromium`; don't run `playwright install`). Commit
   screenshots of **synthetic** data to `docs/screenshots/web/`.
4. **Cross-device tests (item 5).** Phone and desktop on the same interview:
   - save a draft on one and advance the question on the other; neither the answer nor the new draft can be overwritten
   - an answer from the stale device is refused
   - sign-out on one device doesn't corrupt the other's state
5. **Second sign-in factor (item 6), required before any real client.**
   - TOTP (RFC 6238). Use the standard library `hmac` or a small, well-known library added to the `web` extra.
   - Operator enrolment: `admin.py enroll-totp USER` shows the secret and QR once. The secret is stored
     encrypted with the master key, never in logs.
   - 10 single-use recovery codes, hashed.
   - Sign-in asks for the code after the password. Lockout covers code failures too.
   - Disabling a user or resetting 2FA ends all their sessions.
   - Tests: wrong code, reused code, clock drift ±1 step, recovery code used once, lockout, log privacy (sentinel test).
6. **Leave alone:** client isolation, encryption at rest, private uploads, content-free logs, the
   engine (no engine changes in this brief).

## Done when

- Real-browser runs (Playwright, Chromium, phone emulation 390×844) show the save states, background
  and return, stale-device handling and session expiry, with screenshots in the PR.
- No sideways scrolling at 320/360/390px. Tap targets are at least 44px (checked in the test).
- The full suite and encrypted-store suite pass, plus the new tests. `test_web_security.py` is extended, not weakened.
- `SECURITY.md` web section updated (2FA, save behaviour). `HANDOFF.md` section 2 statuses updated.
- What can only be tested on a deployed host and a real phone (item 7) is listed in the PR as still open.

## Deliver

- Branch `feat/web-phone-hardening`, **draft** PR, screenshots and test results in the body.
- Synthetic data only. No deploy, no merge. Soul reviews; Michael approves.

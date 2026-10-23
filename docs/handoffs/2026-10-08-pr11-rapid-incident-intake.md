# Handoff — Laylaw Rapid Incident Intake MVP (2026-10-08)

Requested in Shared Agent Notes, "2026-10-08 — NEEDS CLAUDE CODE — LAYLAW RAPID INCIDENT INTAKE MVP",
plus Soul's same-day addendum (two-stage intake, light first screen).

**Branch:** `feat/rapid-incident-intake`, stacked on PR #3 (`feat/secure-local-mode`). Reuses PR #3's
encrypted vault, workspaces, uploads, audit log and local app; no second case vault.

## What was built

See `docs/INTAKE.md`. One working flow: create an isolated matter, answer the two-stage questions
one at a time, add files, review and change answers, view the chronology and evidence inventory,
and open the referral packet (on screen; see "Export" below).

## Tests (synthetic data only)

- `python -m pytest -q`: **154 passed** (133 from PR #3, 1 new regression test on PR #3, 20 for the intake).
- Covered: stage-one order with danger first; every choice has "I'm not sure"; no question asks for a
  legal classification; child questions only when a child was there, capped and explained; the
  child's words recorded once and never replaced; corrections keep earlier answers; answers that stop
  applying are set aside; gentle validation; save/resume round trip; chronology basis labels and kept
  hedges; unknown dates stay unknown; conflicts kept, not resolved; packet sections; packet neutrality
  (and refusal if Laylaw's wording drifts); the person's own strong words quoted unchanged; matter
  isolation (storage and URL); originals byte-for-byte with notes beside them; no child details or
  file bytes in plain text anywhere on disk or in the audit log; deleting one matter leaves others;
  a full first-time-user flow over HTTP; adult confirmation and CSRF.
- Two guards were broken on purpose (child words once-only; packet neutrality check); a test failed each time.
- **Phone check:** the whole flow was driven in Chromium at 390×844 (mobile emulation). No page scrolls
  sideways. Screenshots: `docs/screenshots/intake/`.

## Fix made to PR #3 along the way

Driving the app in a real browser showed PR #3 refused **every** form in Chrome/Edge, including
Unlock: `Referrer-Policy: no-referrer` makes Chromium send `Origin: null`, which the origin check
refuses. Fixed on PR #3's branch (`58abe85`): `same-origin`, still no referrer to other sites, with a
regression test. The http.client tests could not see this.

## Decisions for Soul / Michael

1. **Export of the packet.** PR #3 disables export for encrypted data, so the packet is on-screen only.
   The build request asks for an export. Options: keep on-screen/print; or a protected export file.
2. **Danger asked first**, not fifth as in the addendum's list, so the safety note appears before anything else.
3. Review of PR #3 (with the browser fix) comes first; this PR depends on it.

# Handoff — Laylaw real-client readiness pass (security layer)

**Date:** 2026-09-29 (America/Los_Angeles)
**From:** Claude → Soul / Michael
**Scope:** real-client blockers from `SECURITY.md` only. **The interviewer engine (`laylaw/interviewer/`) is unchanged**: no file in it was modified. Synthetic data only. **Not deployed. Not approved for real client data yet.**

## Repo, branch, commits
- **Repo:** https://github.com/dragondirty7-create/Laylaw_interviewer
- **Base:** `main` at `eaf01c8fbd96ad4232fdcbffad1f9d0b934270d0` (97 passing, confirmed before starting)
- **Branch:** `feat/real-client-security` → `main`. **PR:** https://github.com/dragondirty7-create/Laylaw_interviewer/pull/5 (open, not merged)
- **Code head:** `7b1040ad307e606b5bb645928a17ec85de8803ef`. The only later commit adds this `HANDOFF.md` section.

| Commit | What |
|---|---|
| `eed6f6e` | Encrypted per-client storage (`crypto.py`, `secure_store.py`) |
| `3a045ac` | Accounts, server-side sessions, lockout, audit log, operator CLI |
| `d25ac7a` | Web app: sign in, one-question interview, autosave, private uploads |
| `eb6f1aa` | Two-client isolation, session, storage and log-privacy tests; CI changes |
| `bbab410` | `SECURITY.md`, `README.md`, `docs/DEPLOY.md` |
| `172f9d5` | Signing in again ends the previous session (found in self-review) |
| `7b1040a` | Docs wording (the legacy-name CI check matched a word in DEPLOY.md) |

- **Deployment URL:** none. See "Remaining blockers".

## Security work completed
1. **Authentication.** Operator-created accounts only (`python -m laylaw.web.admin create-user`); no sign-up route. scrypt password hashes (N=2^15); 12-character minimum; passwords read with getpass, never from argv. The same response is given for a wrong password and an unknown user, including a dummy hash check. Lockout after 5 failures per username in 15 minutes, and 20 per IP. Login CSRF token. Disabling a user or resetting a password signs them out everywhere.
2. **Authorization / client isolation.** One account maps to one random opaque workspace id. **The client id comes only from the server-side session row; no route accepts one from the request.** Another client's interview or upload id returns the identical 404 as an id that does not exist. Ids are checked against strict patterns before any disk access. Every error fails closed.
3. **Secure storage.** AES-256-GCM for everything client-related: sessions, drafts, the displayed question, profile (display name and case label), and uploads. Per-client keys come from HKDF over the master key. Ciphertext is bound to client, kind and object id, so a copied, renamed or altered file is refused. The master key comes only from `LAYLAW_MASTER_KEY`, and the app will not start without a valid one. Paths are opaque (no names or filenames). Permissions are 0700 for directories and 0600 for files, including the SQLite WAL and SHM files. The accounts DB holds no case content or display names. CI fails if data or secret files are committed.
4. **Uploads.** Multiple files at once, at any time; an allowlist of types; 20 MB per file and 20 per request. Each upload is tied to the authenticated client and the interview. Downloads are authenticated, integrity-checked, and sent as `attachment` + `octet-stream` with a sandbox CSP. There are no public URLs or storage keys in the browser. **Uploads are parsed in memory.** Werkzeug's default would have written plaintext temp files for anything over 500 KB; that is turned off and tested.
5. **Session security.** An opaque 256-bit token in `__Host-laylaw` (`Secure; HttpOnly; SameSite=Strict`); only its hash is stored on the server. A new token is issued at each sign-in, and signing in again ends the old session. Sessions end after 30 minutes idle or 12 hours absolute. Sign-out deletes the server row, and a replayed cookie is refused everywhere. CSRF tokens and an Origin check are required on every POST. Strict CSP with no inline script, HSTS, `no-store`, no-referrer, and frame denial. **Nothing is put in browser storage.** Drafts autosave to the server, encrypted.
6. **Usable interface.** Sign in → "Start your interview" (family law or criminal defense, plus 18+ confirmation) or "Continue where you left off" → one question per page, with **Save answer / Skip / Not sure / Save and finish later**. Answers save on submit; typed-but-unsent text autosaves every ~1.5 s and survives sign-out. On return there is a "Welcome back" screen with the engine's resume prompt, and the interview continues at the same pending question. There is a "Supporting documents" panel with multi-file upload and a list of the client's own files. When the safety pause is active, a 911 notice is shown. An answer form from a stale tab is refused, so it cannot answer the wrong question. If the client says the workspace isn't theirs, a "Paused for now" page is shown until an operator runs `admin confirm-workspace`.
7. **Logging / privacy.** Logs name events and exception *types* only. Flask's traceback logging is overridden, because messages could contain answer text. The audit table holds event names and opaque ids. There are no analytics and no third-party resources. Tested: a sentinel string pushed through answers, drafts, filenames and file bodies never appears in logs or the audit table. Neither do passwords, tokens, CSRF values, the key, or display names.
8. **Interviewer untouched.** The web layer only calls the engine's public API: `start_path`, `next_question`, `answer`, `skip`, `not_sure`, `save_and_finish_later`, `resume`, `add_upload`, `confirm_workspace`. **No interviewer defect surfaced during UI integration.** Two integration details were handled in the web layer: orientation text shows only on the first `next_question()`, so the displayed wording is cached (encrypted) for reloads; and a "no" on workspace confirmation leaves the session PAUSED, so the UI shows the blocked page instead of the resume screen.

## Tests and results
- `python -m pytest -q`: **126 passed** (97 existing engine tests, unchanged, plus 29 new in `tests/test_web_security.py`).
- `LAYLAW_TEST_STORE=encrypted python -m pytest -q`: **125 passed, 1 skipped.** This re-runs the whole engine suite on the encrypted store. The skipped test is one required test whose final step plants a *plaintext* `.json` forgery. The encrypted store never reads plaintext files, and the encrypted equivalent (ciphertext copied or renamed between clients) is `test_ciphertext_is_bound_to_client_and_object`.
- **CI** on `7b1040a`, green on Python 3.10 and 3.12: https://github.com/dragondirty7-create/Laylaw_interviewer/actions/runs/36657337645 (pull_request) and https://github.com/dragondirty7-create/Laylaw_interviewer/actions/runs/36657307922 (push). CI now also re-runs the engine suite on the encrypted store and checks for committed data or secrets. (`172f9d5` failed only the legacy-name check, fixed in `7b1040a`.)
- **Live HTTP run** (waitress on localhost, fresh key, two synthetic accounts): sign-in for both; start; answer; a two-file multipart upload (`up2-0`); B → A's interview **404**, B → A's file **404**; A downloads own file as an attachment; static assets served; after sign-out `/home` shows sign-in. Data on disk was only `.enc` files under opaque ids, plus the accounts DB. All 0600/0700. The server log had no request content. The live data was deleted afterwards.
- **Not run:** a real-browser pass. The build environment had no browser (the Playwright download was blocked). The JavaScript autosave was tested at the endpoint level, not by typing in a browser.

## Two-client isolation results (synthetic A = "Alex Fictional", B = "Blair Fictional")
| Check | Result |
|---|---|
| A cannot view B's interview; B cannot view A's | Pass: 404 for both, byte-identical to a nonexistent id |
| Cross-client answer / resume / upload-into / draft POSTs | Pass: 404 each way; nothing was written to the other record (verified by decrypting both) |
| Each sees only their own uploads | Pass: A has 2, B has 1; the other's record ids 404 under their own interview URL too |
| Direct URL/API guessing (`..`, `%2e%2e`, `INT-../../x`, made-up `INT-` ids, other's `R-` ids) | Pass: 404 |
| Home lists only own interviews and own name | Pass |
| Each interview resumes correctly through the UI | Pass for both: draft kept, "Welcome back", same pending question, next answer recorded, `is_continuation` true |
| Sign-out blocks later access | Pass: replayed cookie refused on pages (302 to sign-in), draft API (401), and answer POST |
| Idle and absolute expiry | Pass |
| Unauthorized calls fail cleanly | Pass: 302 to sign-in / 401 JSON / 403 on CSRF or Origin failure, with generic pages |
| Ciphertext copied into B's folder, renamed, tampered, wrong key, record read via B's handle | Pass: all refused |
| Nothing readable at rest (names, case label, answer text, filenames, file bodies, drafts) | Pass |

## Remaining blockers (not "Chelsea-ready" yet)
1. **No deployment.** It needs an HTTPS host with a persistent, volume-encrypted private disk, `LAYLAW_MASTER_KEY` in a secret manager, encrypted backups stored apart from the key, and a single process (`docs/DEPLOY.md`). **Vercel functions as-is do not fit** (ephemeral filesystem). Using them would mean a different storage backend: private database plus private blob store. Choosing the host and region is a data-location decision.
2. **Privacy/legal review** (confidentiality, privilege expectations, who has operator access) has not been done.
3. **Deployed smoke test** has not been done: two synthetic accounts on the real instance, in Chelsea's own browser and phone, repeating the isolation table above plus typing a long answer, closing the tab, and returning.
4. **Known limitations**, accepted or to decide:
   - Whoever holds the key and the disk can read all data (server-side encryption, not end-to-end).
   - No second factor yet. TOTP is recommended.
   - No key-rotation command.
   - No retention or verified-deletion workflow.
   - Decrypted data is in server memory during requests.

## Ready for Soul's final real-client-readiness review?
**Yes, for the code and tests on PR #5.** Every item in the brief's READY definition that can be completed without a host is done and verified: authentication, isolation, storage, private uploads, session handling, the two-client tests, and save/resume through the UI. The remaining limitations are documented. **No, for real data.** That still needs blockers 1–3 above. No real client data has been entered anywhere.

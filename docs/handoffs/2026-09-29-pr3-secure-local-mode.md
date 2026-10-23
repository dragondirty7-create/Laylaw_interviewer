# Handoff — Laylaw, Issue #2: single-user secure local mode

**Date:** 2026-09-29 (America/Los_Angeles)
**From:** Claude → Soul / Michael
**Input:** Issue #2 and Soul's priority update (acceptance = Chelsea can actually use the Interviewer).
**Branch:** `feat/secure-local-mode`, base `eaf01c8fbd96ad4232fdcbffad1f9d0b934270d0` (current `main`).
**Status:** PR open for Soul's security/code review. **Not merged. Synthetic data only.**

## What was built
| Issue #2 item | Where | Summary |
|---|---|---|
| 1 Local-only access | `laylaw/app/server.py` | 127.0.0.1 only (other binds refused in code); one-time launch link → HttpOnly SameSite=Strict cookie; Host check; Origin + CSRF on every POST; no JS, strict CSP, `no-store` |
| 2 Single-user access gate | `laylaw/secure/vault.py`, `mode.py`, `secrets_store.py` | Passphrase (scrypt n=2^17) **and** device secret in the OS credential store (Windows Credential Manager / macOS Keychain via `keyring`); lockout after 5 failures; idle lock 15 min |
| 3 Encryption at rest | `vault.py`, `store.py` | Random data key; AES-256-GCM per file, bound to vault id + logical name; opaque HMAC file names; recovery code (256-bit, shown once, confirmed at init) |
| 4 Audit log | `laylaw/secure/audit.py` | HMAC-chained JSONL + head file; content-free (opaque refs, small codes only; free text rejected); edits/deletes/truncation detected |
| 5 Retention and deletion | `store.py`, app, CLI | Delete interview (app) / workspace (CLI): overwrite + unlink + index removal; limits documented |
| 6 Secure export boundary | `store.py`, `pages.py` | Export disabled for encrypted data (refused + audited); outputs on screen only |
| 7 Real-data mode gate | `mode.py`, `workspace.py` | Vault header mode `real`/`synthetic`; real refuses unless OS store, key present, KDF ≥ 2^15, private permissions, no stray plaintext, audit chain intact; plaintext `WorkspaceStore` refused with `LAYLAW_MODE=real` or in a vault |
| 8 Tests | `tests/test_secure_local_mode.py` (29), `tests/test_local_app.py` (7) | All listed cases + full HTTP walkthrough of Chelsea's workflow |
| Usability (Soul update) | app + `scripts/` + `docs/LOCAL_MODE.md` | Launch, unlock, new interview, one question at a time (Answer/Skip/Not sure/Save and finish later), save/exit, resume, encrypted uploads, finish, outputs, delete |

Engine (`laylaw/interviewer/*`) unchanged except the `WorkspaceStore` guard.

## Tests
`python -m pytest -q`: **133 passed** (97 existing + 29 + 7). CI green on `b9603cf` (3.10 and 3.12):
https://github.com/dragondirty7-create/Laylaw_interviewer/actions/runs/36631398852

## Finding for Soul (engine, not changed here)
Answering "What happened next?" with **"No, that's all."** is recorded as a new fact, which queues the
full follow-up set again, so the interview never ends if she keeps answering that way. "No." and
"Nothing else." end it correctly. `_NOTHING_MORE` in `session.py` doesn't accept "No, that's all." as
one phrase. It's a one-line fix, but it's engine behavior, so it's left for your call (next pass or this PR).

## Still blocking real use
1. Soul's review of this PR. 2. Setup on Chelsea's own computer and OS account (disk encryption, screen
lock, `init` run by her, recovery code on paper). 3. Privacy/legal review. See SECURITY.md.

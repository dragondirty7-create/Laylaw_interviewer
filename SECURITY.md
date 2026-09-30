# Security and data-handling status

**Status (2026-09-29): the web layer's security controls are built and tested with
synthetic data. It is NOT yet approved for real client data.** Real data waits on
the blockers at the bottom of this file: an HTTPS deployment that meets the host
requirements, a privacy/legal review, and a final real-client-readiness review.

Two parts of this repo have different status:

| Part | What it is | Real client data? |
|---|---|---|
| `laylaw.interviewer` | The interview engine (library, stdlib only). Its plain `WorkspaceStore` writes readable JSON. | **Never directly.** Use it only through the web layer's encrypted store. |
| `laylaw.web` | Authenticated web app: accounts, sessions, encrypted storage, private uploads, UI. | Only after the blockers below are cleared. |

## What the web layer does

### Authentication
- Accounts are created only by an operator (`python -m laylaw.web.admin create-user`). There is no sign-up page.
- Passwords: at least 12 characters, stored as scrypt hashes (N=2^15, r=8, p=1, 16-byte salt). Passwords are read with `getpass`, never from command-line arguments.
- Wrong password and unknown username give the same response and take the same work (a dummy hash is checked for unknown users).
- Lockout: 5 failures for a username in 15 minutes locks that username; 20 from one IP locks that IP. The lock applies even to the correct password.
- The sign-in form has a pre-authentication double-submit token (login CSRF).
- Disabling a user or resetting their password signs out all of that user's sessions immediately.

### Authorization and client isolation
- One account maps to exactly one client workspace. The workspace id is random (`c-` + 20 hex characters) and is stored only in the server-side accounts table.
- **No route takes a client id from the request.** Every read and write uses the client id from the authenticated server-side session row.
- An interview or upload id that is not in the caller's own workspace returns the same `404` page, byte for byte, as an id that does not exist. So a client cannot tell whether another client's id exists.
- Ids are checked against strict patterns before any file access. Path-traversal forms are refused. The engine's existing path guard stays in place underneath.
- Errors fail closed: a decryption failure, a mismatched stored client id, or a malformed id all become "not found" or "access denied". Nothing falls back to a readable path.

### Storage at rest
- All client data is encrypted with AES-256-GCM: session records, unsent drafts, the last-shown question, the client profile (display name and case label), and uploaded files.
- Each client has its own key, derived from one master key with HKDF-SHA256 and the client id. Each ciphertext is bound to its client, kind and object id through the associated data. A file copied into another client's folder, renamed to another id, or altered by one byte fails to decrypt and is refused. This is tested.
- The master key comes only from the `LAYLAW_MASTER_KEY` environment variable. The app refuses to start if it is missing or not exactly 32 bytes. It is never read from source control or the data directory. CI fails if data files, `.env` files, or a literal key are committed.
- Paths on disk contain no names, filenames, or case details. Uploads are stored as `uploads/<interview id>/<random record id>.enc`; the original filename exists only inside the encrypted session record.
- Data directories are `0700`, files are `0600`, and that includes the SQLite database and its WAL and SHM files.
- The accounts database holds usernames, password hashes, opaque workspace ids, hashed session tokens, failed-login timestamps, and audit events. It holds no case facts, display names, filenames or document content.
- Uploads are parsed **in memory**. Werkzeug's default of spilling uploads over 500 KB to temporary files on disk is turned off, so no plaintext copy is written. The request size cap bounds the memory used.

### Uploads
- Several files can be uploaded at once, at any point in the interview. There is a limit of 20 files per request and 20 MB per file, and only an allowlist of document, image, audio and video types is accepted.
- Every upload is attached to the authenticated client and the specific interview: `SupportingRecord.client_id` and `session_id`.
- There are no public URLs and no storage keys in the browser. A download is an authenticated request that checks the file belongs to that client and interview, verifies it against its stored SHA-256 hash, and sends it as `application/octet-stream` with `Content-Disposition: attachment` and a sandboxing CSP. That prevents an uploaded HTML or SVG file from running in the app's origin.

### Sessions
- The browser holds one opaque random token (256 bits) in a cookie named `__Host-laylaw`, set with `Secure; HttpOnly; SameSite=Strict; Path=/` and no `Domain` or expiry. The server stores only the token's SHA-256 hash.
- A new token is issued at every sign-in. Sessions end after 30 minutes of inactivity, or 12 hours after sign-in regardless of activity.
- Sign-out deletes the server-side session. A replayed old cookie is refused on every page and API endpoint. This is tested.
- Every state-changing request needs a CSRF token (form field or `X-CSRF-Token` header), and any cross-origin `Origin` header is refused.
- Each answer form carries a token bound to the exact question on screen. A stale tab cannot answer a different question than the one it shows.
- Nothing is put in `localStorage`, `sessionStorage`, IndexedDB, or `document.cookie`. Unsent answer text is autosaved to the server, encrypted, not to the browser. CI checks this.
- Headers: a strict CSP (`default-src 'none'; script-src 'self'`, no inline script), `frame-ancestors 'none'`, HSTS, `nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` on every page.

### Logging and privacy
- Application logs record event names and exception **types** only, never exception messages or tracebacks, because those could contain answer text.
- Answers, drafts, filenames, document contents, display names, passwords, session tokens, CSRF tokens and the master key never appear in logs. This is tested with a sentinel string passed through every flow.
- The audit table records events (sign-in, failed sign-in, lockout, sign-out, expiry, interview started, answer saved, upload stored, upload downloaded, operator actions) with opaque ids only.
- There is no analytics, telemetry, or third-party script. No external resources are loaded.
- The production server (waitress) keeps no access log by default. If a proxy logs requests, its logs contain only paths with opaque ids.

## Remaining limitations (known and accepted for now, or open)
- **The operator can read everything.** Whoever holds `LAYLAW_MASTER_KEY` and the data directory can decrypt all client data. This is server-side encryption, not end-to-end encryption. It protects against a stolen disk, a stolen backup, or a misconfigured file share. It does not protect against a compromised running server or a compromised operator.
- **Password-only sign-in.** There is no second factor yet. A TOTP second factor is recommended before, or soon after, the first real client.
- **No key rotation tool.** Rotating the master key currently means re-encrypting offline. A `rekey` command is not built.
- **No retention or verified-deletion workflow**, and no audit-log retention policy. Deleting a client is a manual operator action.
- **Decrypted data exists in server memory** while a request is handled.
- **Classifiers remain keyword backstops** (danger, advocacy, source typing), as before.
- **The JavaScript autosave was tested at the API level only.** The build environment had no browser. The server, cookies, multipart uploads and static files were tested over real HTTP with waitress.

## Blockers before real client data
1. **Deployment that meets the host requirements** (see `docs/DEPLOY.md`): HTTPS only; a persistent private disk that is encrypted at the volume level; `LAYLAW_MASTER_KEY` in a secret manager; encrypted backups of the data directory kept separately from the key; one process (the app uses per-process locks). Serverless hosts with ephemeral disks, including Vercel functions as-is, do not meet this.
2. **Data-location decision and privacy/legal review:** where the data lives, who has operator access, confidentiality and privilege expectations. Nothing in this repo is covered by attorney-client privilege.
3. **Final real-client-readiness review** (Soul) of this branch and the deployed instance.
4. **A synthetic-account smoke test on the deployed instance**, run in the client's own browser and phone, before any real account is created.

## Test data
All tests and fixtures use synthetic, fictional data. Do not commit real case
facts, names, filings, screenshots, uploads, logs, databases, keys, or snapshots.

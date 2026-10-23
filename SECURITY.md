# Security and data-handling status

**Status (2026-10-23): nothing in this repo is approved for real client data. Use synthetic,
fictional data everywhere.** Current status and next steps: [HANDOFF.md](HANDOFF.md).

Laylaw can run in several ways, and they are not equally safe:

| | Plain library | Hosted web app | Secure local mode | Voice interview kit |
|---|---|---|---|---|
| Code | `laylaw.interviewer` `WorkspaceStore` | `laylaw.web` (PR #5) | `laylaw.secure` + `laylaw.app` (PR #3) | `docs/VOICE_INTERVIEW_KIT.md` (PR #13) |
| What it is | Readable JSON, for tests and development | Sign-in web app, one encrypted workspace per client, any device | One person, one computer, encrypted vault, 127.0.0.1 only | ChatGPT Voice plus a separate audio recording |
| Real case data | **Never** | Only after the blockers below are cleared | Only after its review and setup below | The chat is held by a third party; treat it as a copy, never the record |
| Encryption at rest | None | AES-256-GCM, per-client keys from one master key | AES-256-GCM, per-file, key wrapped by passphrase + device secret | Outside Laylaw |
| Access control | None | Operator-created accounts, scrypt, lockout, server sessions (2FA not yet) | Passphrase + OS credential store | Outside Laylaw |
| Audit log | None | Content-free events table | HMAC-chained, content-free | Session log kept by hand in the restricted vault |

**Direction (Soul, 2026-10-21):** the hosted web app is the primary path for a client on a phone.
Secure local mode stays a single-computer option and the source of the intake screens. It is not to
become a second hosted app. Whether it is kept as a real-data option is an open decision (HANDOFF.md, step D).

The plaintext `WorkspaceStore` refuses to start when `LAYLAW_MODE=real` is set or inside a vault
folder, so real data can't silently fall back to plaintext. The engine itself is the same in every
mode: provenance rules, one-question-at-a-time flow, safety pause and outputs. The encrypted stores
implement the same small interface the engine already used (`client_id`, `save_session`, `store_upload`).

## Hosted web app (`laylaw.web`)

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
- Draft autosave is bound to the same question revision. A save from a stale tab or another device gets `409` and writes nothing; the page stops autosaving and says the interview changed elsewhere.
- Nothing is put in `localStorage`, `sessionStorage`, IndexedDB, or `document.cookie`. Unsent answer text is autosaved to the server, encrypted, not to the browser. CI checks this.
- Headers: a strict CSP (`default-src 'none'; script-src 'self'`, no inline script), `frame-ancestors 'none'`, HSTS, `nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` on every page.

### Logging and privacy
- Application logs record event names and exception **types** only, never exception messages or tracebacks, because those could contain answer text.
- Answers, drafts, filenames, document contents, display names, passwords, session tokens, CSRF tokens and the master key never appear in logs. This is tested with a sentinel string passed through every flow.
- The audit table records events (sign-in, failed sign-in, lockout, sign-out, expiry, interview started, answer saved, upload stored, upload downloaded, operator actions) with opaque ids only.
- There is no analytics, telemetry, or third-party script. No external resources are loaded.
- The production server (waitress) keeps no access log by default. If a proxy logs requests, its logs contain only paths with opaque ids.

### Known limitations (accepted for now, or open)
- **The operator can read everything.** Whoever holds `LAYLAW_MASTER_KEY` and the data directory can decrypt all client data. This is server-side encryption, not end-to-end encryption. It protects against a stolen disk, a stolen backup, or a misconfigured file share. It does not protect against a compromised running server or a compromised operator.
- **Password-only sign-in.** There is no second factor yet. A TOTP second factor is recommended before, or soon after, the first real client.
- **No key rotation tool.** Rotating the master key currently means re-encrypting offline. A `rekey` command is not built.
- **No retention or verified-deletion workflow**, and no audit-log retention policy. Deleting a client is a manual operator action.
- **Decrypted data exists in server memory** while a request is handled.
- **Classifiers remain keyword backstops** (danger, advocacy, source typing), as before.
- **The JavaScript autosave was tested at the API level only.** The build environment had no browser. The server, cookies, multipart uploads and static files were tested over real HTTP with waitress.

## Secure local mode (`laylaw.secure`, `laylaw.app`)

**Threat model in one paragraph.** One person (Chelsea) uses Laylaw on one
computer and one OS account that only she signs into. We protect case data
from: someone who gets a copy of the files (stolen laptop without the
passphrase, a synced or backed-up folder, a repaired disk), other accounts on
the same computer, other web pages open in her browser, and accidental
plaintext copies inside the app. We do **not** protect against someone who is
signed into her OS account while Laylaw is unlocked, malware running as her
account, or anyone who knows her passphrase and uses her computer.

### Access gate
* Opening the vault needs **both** the passphrase (12+ characters, stretched
  with scrypt, n=2^17) **and** a 256-bit device secret kept in the OS
  credential store for her OS account (Windows Credential Manager or macOS
  Keychain, through the maintained `keyring` library). A copied data folder plus
  the passphrase doesn't open it; the OS account without the passphrase doesn't
  either.
* Five wrong passphrases lock the gate for 60 seconds. Every attempt, success
  or failure, is audited.
* The app locks after 15 idle minutes, on **Lock**, and on exit. While locked
  it shows nothing about any case.

### Key storage, encryption, recovery
* A random 256-bit data key encrypts everything. It is stored only wrapped:
  once under the passphrase+device key, once under the recovery code.
* Files are AES-256-GCM (`cryptography` library) with a random nonce. Each
  file's associated data binds it to this vault and its logical name, so a
  file can't be edited, swapped into another client's workspace, or moved
  without failing authentication. File names on disk are HMACs: no client
  labels, names, session ids or upload file names appear.
* **Recovery code.** Shown once at `init`, 256 bits, written down on paper and
  stored away from the computer. It restores access after a forgotten
  passphrase or a new/reinstalled computer (`python -m laylaw recover`).
  **If the passphrase-and-this-computer AND the recovery code are both lost,
  the data is gone for everyone, including us.** `init` makes the user type
  part of the code back before finishing, so this can't be skipped silently.
* Backups: copying the vault folder is safe (it's ciphertext). A backup is only
  usable with the recovery code, or with this computer's OS account plus the
  passphrase.

### Local-only access
* The app listens on 127.0.0.1 only; any other bind address is refused in code.
* It's opened with a one-time launch link that sets an HttpOnly,
  SameSite=Strict cookie. Requests without it, including from other OS
  accounts or other programs probing the port, get nothing.
* The Host header must be the loopback address and port (blocks DNS
  rebinding). Every POST needs a per-launch CSRF token, and a cross-site or
  `null` Origin is refused.
* No JavaScript. A strict Content-Security-Policy, `no-store` caching (case
  text isn't written to the browser cache), no framing, no referrers.

### Audit log
* Records: vault created, app start/stop, unlock ok/failed, lockout, lock
  (manual/idle/exit), session created/opened/saved/saved-for-later/resumed,
  upload stored/read, outputs viewed, export refused, session/workspace
  deleted, passphrase changed, recovery used/failed, integrity errors,
  readiness refusals.
* Contents: time, event, opaque HMAC references for workspace and session,
  and small numbers/codes (byte counts, attempt counts). No names, facts,
  answers, file names or document contents; the logger rejects free text.
  Routine saves are logged at most once a minute per session.
* Tamper-evident: each entry carries an HMAC chained to the previous one, and
  a head file records the last entry, so edits, deletions, reordering and
  truncation are detected (`python -m laylaw verify-audit`). A failed chain
  makes the readiness check refuse to open the vault until it's reviewed
  (`audit-archive` moves the log aside and starts a new chain).
* Limits: the HMAC key lives in the OS credential store (so failed unlocks can
  be logged before the passphrase is known). Someone in control of her OS
  account can rewrite the whole log consistently, and someone with file access
  can roll both files back to an earlier consistent state.

### Retention and deletion
* Delete an interview in the app (type DELETE to confirm); delete a whole
  workspace with `python -m laylaw delete-workspace --client LABEL`.
* The app overwrites each encrypted file with random bytes, then removes it,
  and removes it from the index; tests verify the files are gone and the data
  can't be loaded or listed.
* What deletion can't guarantee: SSDs, journaling/copy-on-write file systems,
  OS snapshots, and backups may keep old encrypted copies. Those copies are
  still ciphertext, but anyone holding the recovery code (or this computer and
  the passphrase) could decrypt a restored old copy. There is no automatic
  retention period in this phase; deletion is manual.

### Export
* Export of real case material is **disabled** (`SecureStore.export` refuses and
  logs it). Outputs are viewed on screen only. Printing or saving the outputs
  page from the browser creates an unencrypted copy; the page says so.

### Real-data gate
A vault created with `python -m laylaw init` is a real-data vault. Laylaw
refuses to open it, and says why, unless all of these hold:
* `cryptography` is installed;
* the device secret is in an OS-protected credential store (plain-file,
  in-memory or missing keyrings are refused) and is present;
* passphrase stretching is at least scrypt n=2^15;
* on macOS/Linux, the vault folder, data folder and header are private to the
  user (Windows ACLs aren't checked; keep the vault in her own profile folder,
  which is the default);
* the data folder holds only encrypted Laylaw files, and no plaintext `clients`
  folder exists in the vault;
* the audit log verifies.

`python -m laylaw init --synthetic` makes a vault with the same encryption but
relaxed environment checks, marked "SYNTHETIC DATA ONLY" in the app. It is for
demos and tests.

## Rapid intakes (`laylaw.intake`)

- Run inside secure local mode and use its encrypted vault, audit log and deletion. There is no second vault.
- Each intake is its own isolated matter and shares nothing with any interview or other intake.
- Files are stored encrypted with a SHA-256 fingerprint taken at upload; notes sit beside the file, never inside it.
- The referral packet is shown on screen only (export is disabled for encrypted data), and Laylaw's own
  wording is checked against the advocacy guard and a list of conclusion words before it is shown.
- The criminal/supervision intake (PR #12) is a draft: **not approved for merge or real-client use** (Soul, 2026-10-17).

## Voice interview kit

- The ChatGPT conversation is held by a third party. Use the account's data controls as the case owner
  decides, and treat the chat as a copy, not the record.
- The recording, checkpoints and chat export live only in the restricted case vault, never in this repo,
  issues, PRs or screenshots. The original audio is kept unchanged with its SHA-256 fingerprint.

## Blockers before real client data

Web app:

1. **Deployment that meets the host requirements** (see `docs/DEPLOY.md`): HTTPS only; a persistent private disk that is encrypted at the volume level; `LAYLAW_MASTER_KEY` in a secret manager; encrypted backups of the data directory kept separately from the key; one process (the app uses per-process locks). Serverless hosts with ephemeral disks, including Vercel functions as-is, do not meet this.
2. **Data-location decision and privacy/legal review:** where the data lives, who has operator access, confidentiality and privilege expectations. Nothing in this repo is covered by attorney-client privilege.
3. **Final real-client-readiness review** (Soul) of the web app and the deployed instance.
4. **A synthetic-account smoke test on the deployed instance**, run in the client's own browser and phone, before any real account is created.
5. **Soul's 2026-10-21 phone and durability list**, including 2FA as a requirement before the first real client (see HANDOFF.md, section 2).

Secure local mode:

1. **Soul's security and code review of PR #3.**
2. Set up on Chelsea's own computer: her own OS account with a sign-in
   password, full-disk encryption on (BitLocker/FileVault), automatic
   screen lock, Python and the `secure` extra installed, `python -m laylaw
   init` run by her (so only she knows the passphrase), recovery code on paper.
3. A privacy and legal review of confidentiality and privilege expectations.
4. Known gaps: keyword classifiers (danger, sources, advocacy guard) remain
   English keyword matching; attribution of answers relies on the single
   signed-in user; no automatic retention; no secure export.

## Test data

All tests and fixtures use synthetic, fictional data. Do not commit real case facts, names, filings,
screenshots, uploads, logs, databases, vaults, keys, or snapshots.

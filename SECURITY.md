# Security and data-handling status

Laylaw has three ways to run. They are not equally safe. **Only the hardened
single-user local mode may ever hold real case information, and only after
Soul's security review of Issue #2 passes.** Until then, use synthetic data
everywhere.

| | Synthetic / dev library | Hardened single-user local mode | Public or multi-user |
|---|---|---|---|
| What it is | `WorkspaceStore` plaintext JSON, used by tests and development | `python -m laylaw run`: encrypted vault + local browser app on one computer | Anything served to other people or other machines |
| Real case data | **Never** | Only after security review passes, on one controlled computer | **Not approved.** Not built. |
| Encryption at rest | None | AES-256-GCM, authenticated, per-file | n/a |
| Access control | None | Passphrase + OS-account device secret | n/a |
| Audit log | None | HMAC-chained, content-free | n/a |

The plaintext `WorkspaceStore` refuses to start when `LAYLAW_MODE=real` is set or
inside a vault folder, so real data can't silently fall back to plaintext.

## Hardened single-user local mode

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

### Unchanged from PR #1
The Interviewer engine is unchanged: provenance rules, one-question-at-a-time
flow, safety pause, outputs. The encrypted store implements the same small
interface the engine already used (`client_id`, `save_session`,
`store_upload`).

## What still stands between this and real use
1. **Soul's security and code review of this PR.**
2. Set up on Chelsea's own computer: her own OS account with a sign-in
   password, full-disk encryption on (BitLocker/FileVault), automatic
   screen lock, Python and the `secure` extra installed, `python -m laylaw
   init` run by her (so only she knows the passphrase), recovery code on paper.
3. A privacy and legal review of confidentiality and privilege expectations.
4. Known gaps: keyword classifiers (danger, sources, advocacy guard) remain
   English keyword matching; attribution of answers relies on the single
   signed-in user; no automatic retention; no secure export.

## Test data
All tests and fixtures use synthetic, fictional data. Do not commit real case
facts, names, filings, screenshots, uploads, logs, vaults, or snapshots.

# Security and data-handling status

**This code is not production-ready for real client data.** Read this before
using it with anything other than synthetic test data.

## What exists today
- **Client workspaces** are separate directories on one filesystem. The code
  validates client and session IDs, refuses paths that escape a workspace, and
  checks the stored client ID on every load and save.
- **Saves** write JSON files atomically, and uploads are stored with a SHA-256
  hash.

## What does NOT exist yet
- **No encryption at rest.** Session JSON and uploaded files are plain files on
  disk. Anyone with filesystem access can read them.
- **No authentication or authorization.** Nothing checks *who* is calling. A
  caller that can construct `WorkspaceStore(root).workspace("client-x")` can
  read that client's data. Directory isolation prevents *accidental*
  cross-client mixing in code paths; it is **not** a multi-user security
  boundary.
- **No audit log, retention policy, or deletion workflow.**
- **No secrets handling, TLS, or network service.** This is a library.
- **Keyword classifiers are backstops.** Present-danger detection and the
  advocacy guard are keyword lists. They can miss things and must not replace
  human judgment.

## Before real client data
1. Put storage behind authenticated, per-user authorization.
2. Encrypt data at rest and in transit, with managed keys.
3. Add audit logging, retention, and verified deletion.
4. Complete a privacy and legal review (confidentiality, privilege
   expectations, data location).

## Test data
All tests and fixtures use synthetic, fictional data. Do not commit real case
facts, names, filings, screenshots, uploads, logs, or snapshots.

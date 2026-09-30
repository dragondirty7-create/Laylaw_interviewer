# Laylaw

Laylaw Interviewer: structured, neutral fact-gathering for adults.

> **Golden rule:** DO NOT MAKE THE CASE BETTER. MAKE THE RECORD BETTER.

This package implements the **INTERVIEW** stage of the Laylaw pipeline
(`INTERVIEW -> ORGANIZE -> VERIFY -> ANALYZE -> DRAFT`), built to the
*Laylaw Interviewer — Canonical Specification* (Drive). Later stages are
separate and are refused from inside INTERVIEW mode.

## Layout

```
laylaw/interviewer/
  models.py     record types (facts, dates, sources, records, discrepancies, statuses)
  classify.py   conservative text classifiers (hedges, date precision, source, requests, safety)
  session.py    the interview engine: orientation, free account, one-at-a-time clarification,
                record hook, end-of-section check, final check, save/resume, documents
  guard.py      INTERVIEW-mode guard against advocacy / strategy / legal analysis
  outputs.py    the 7 outputs: Interview Record, Fact Table, Timeline, Evidence Follow-up,
                Open Questions, Requested Outcomes, Handoff Summary
  workspace.py  isolated per-client workspaces, atomic saves, uploads
  paths.py      section specs; family-law and criminal-defense paths (same engine, same rules);
                adaptive section selection; intake/preflight questions
  research_basis.py  Research Basis template/record (never read by the engine)
laylaw/web/          authenticated, encrypted, per-client web app (optional extra: pip install -e ".[web]")
  app.py        routes: sign in/out, start/resume, one-question answer form, autosaved drafts, uploads
  accounts.py   operator-created accounts, scrypt passwords, server-side sessions, lockout, audit log
  crypto.py     AES-256-GCM with per-client HKDF keys; master key from LAYLAW_MASTER_KEY only
  secure_store.py  encrypted drop-in for ClientWorkspace (the engine is unchanged)
  admin.py      operator CLI (create-user, reset-password, confirm-workspace, ...)
  wsgi.py       production entry point (waitress, behind an HTTPS proxy)
laylaw/organize/
  interface.py  read-only export + protocol for a future ORGANIZE stage (case packet lives there)
docs/RESEARCH_BASIS.md  the Research Basis template
docs/DEPLOY.md          host requirements and deployment steps (not deployed)
tests/
  test_required.py     the 11 tests required by the Claude Code handoff
  test_repair_pass.py  corrections, controls, criminal path, preflight, propositions,
                       discrepancies, source typing, sections, candidates, ORGANIZE, research
  test_extra.py        criminal-path engine parity, safety pause
  test_audit_repairs.py  regressions for the fdd7d449 audit: provenance, unknown basis,
                       acknowledgements vs corrections, discrepancy binding, attributed
                       wording, immediate-danger preflight, conflict labels
  test_web_security.py auth, sessions, CSRF, two-client isolation, encryption at rest,
                       private uploads, UI save/resume, log privacy (synthetic clients A and B)
.github/workflows/tests.yml  CI: full pytest suite on every push and PR
```

## Interview controls

At any question the interviewee can answer **"skip"**, **"not sure"** (or "I don't
know"), or **"save and finish later"**. These are recorded as controls, never as
facts. Save-and-finish-later keeps the exact pending question as the resume point.

## Corrections

Recap and final-check corrections never edit the original. The engine creates
a new fact version in the interviewee's words, linked by `correction_of` and
`superseded_by`, and every output shows both versions. A bare "yes" is an
acknowledgement, not a correction: the engine asks what should change first.
"Is there anything important I missed?" records additions and replaces nothing.

## Provenance

Every fact, correction, and alternate account is an exact slice of the
interviewee's logged answer. Outside the question flow, `log_answer(text,
question=...)` (or `record_statement(...)`) is the only way to enter their
words; generated or paraphrased text raises `ProvenanceError`. A claim with no
stated basis ("They were using drugs.") is recorded as UNKNOWN and followed by
"How do you know that?".

## Security status

The engine's plain `WorkspaceStore` writes readable JSON and has no authentication:
use it for synthetic data only. The `laylaw.web` layer adds authentication, per-client
authorization, encryption at rest, private uploads and secure sessions, tested with
two synthetic clients. **It is not yet approved for real client data**: it still needs
an HTTPS deployment meeting `docs/DEPLOY.md`, a privacy/legal review, and a final
readiness review. See [SECURITY.md](SECURITY.md).

## Run

```
pip install pytest "flask>=3.0,<4" "cryptography>=42" waitress
python -m pytest -q                               # everything
LAYLAW_TEST_STORE=encrypted python -m pytest -q   # engine suite again, on the encrypted store
```

The engine has no runtime dependencies (Python 3.10+ standard library only).
The web layer needs Flask, cryptography and waitress (`pip install -e ".[web]"`).

Local web run with synthetic accounts only (plain HTTP needs `LAYLAW_COOKIE_SECURE=0`;
never use that setting in production):

```
export LAYLAW_DATA_DIR=./laylaw-data LAYLAW_MASTER_KEY="$(python -m laylaw.web.admin generate-key)"
python -m laylaw.web.admin create-user test.fictional --display-name "Test Fictional"
LAYLAW_COOKIE_SECURE=0 waitress-serve --listen=127.0.0.1:8080 laylaw.web.wsgi:app
```

## Quick use

```python
from laylaw.interviewer import WorkspaceStore, InterviewSession, outputs

ws = WorkspaceStore("./laylaw-data").workspace("client-001")
s = InterviewSession.start(ws, case_id="CASE-1", interviewee="Jordan Avery",
                           interviewer="Laylaw Interviewer", purpose="Intake",
                           sections=["Specific incidents"], interviewee_is_adult=True)
print(s.next_question())        # always exactly one question
s.answer("I think the pickup was late.")
s.interrupt()                   # safe to stop any time
s = ws.load_session(s.interview_id); print(s.resume())
print(outputs.handoff_summary(s))
```

## Test data

All test data is synthetic and fictional. Do not put real case facts in
fixtures, demo data, logs, screenshots, or snapshots.

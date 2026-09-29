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
laylaw/secure/
  vault.py      key hierarchy, access gate, recovery code, AES-GCM files bound to logical names
  store.py      encrypted drop-in workspace store (sessions, uploads, deletion); export disabled
  audit.py      HMAC-chained, content-free audit log
  mode.py       real-data readiness gate and passphrase gate with lockout
  secrets_store.py  OS credential store (keyring) with backend allowlist
laylaw/app/
  server.py     127.0.0.1-only local app (launch token, CSRF, Host/Origin checks, idle lock)
  pages.py      no-JavaScript HTML pages
laylaw/__main__.py  CLI: init, run, doctor, recover, change-passphrase, verify-audit, ...
scripts/        double-click launchers for Windows and Mac
laylaw/organize/
  interface.py  read-only export + protocol for a future ORGANIZE stage (case packet lives there)
docs/RESEARCH_BASIS.md  the Research Basis template
tests/
  test_required.py     the 11 tests required by the Claude Code handoff
  test_repair_pass.py  corrections, controls, criminal path, preflight, propositions,
                       discrepancies, source typing, sections, candidates, ORGANIZE, research
  test_extra.py        criminal-path engine parity, safety pause
  test_audit_repairs.py  regressions for the fdd7d449 audit: provenance, unknown basis,
                       acknowledgements vs corrections, discrepancy binding, attributed
                       wording, immediate-danger preflight, conflict labels
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

* **Plaintext library (`WorkspaceStore`)**: synthetic/development data only. No
  encryption, no authentication. Refused when `LAYLAW_MODE=real` or inside a vault.
* **Hardened single-user local mode** (`python -m laylaw run`): encrypted vault,
  passphrase + OS credential store access gate, content-free tamper-evident audit
  log, deletion, local-only browser app. Awaiting Soul's security review; use
  synthetic data until it passes.
* **Public or multi-user use**: not approved and not built.

See [SECURITY.md](SECURITY.md) and the setup/use walkthrough in
[docs/LOCAL_MODE.md](docs/LOCAL_MODE.md).

## Run

```
pip install ".[test]"
python -m pytest -q
```

The engine has no runtime dependencies (Python 3.10+ standard library). The
hardened local mode needs the `secure` extra (`cryptography`, `keyring`):

```
pip install ".[secure]"
python -m laylaw init      # once: create the encrypted vault, get the recovery code
python -m laylaw run       # start the local app in the browser
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

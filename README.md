# Laylaw

Laylaw Interviewer: structured, neutral fact-gathering for adults.

> **Golden rule:** DO NOT MAKE THE CASE BETTER. MAKE THE RECORD BETTER.

This repo implements the **INTERVIEW** stage of the Laylaw pipeline
(`INTERVIEW -> ORGANIZE -> VERIFY -> ANALYZE -> DRAFT`), built to the
*Laylaw Interviewer — Canonical Specification* (Drive). Later stages are
separate and are refused from inside INTERVIEW mode.

**Status and next steps live in [HANDOFF.md](HANDOFF.md).** Nothing here is approved
for real client data yet: use synthetic data everywhere (see [SECURITY.md](SECURITY.md)).

## The parts

| Part | What it is | Run it |
|---|---|---|
| **Interviewer engine** (`laylaw/interviewer`) | The library every other part uses. One question at a time, provenance on every fact, corrections that never overwrite, seven outputs. Standard library only. | `python -m pytest -q` |
| **Hosted web app** (`laylaw/web`) | Sign-in, server-side sessions, encrypted per-client storage, private uploads, one-question pages with autosave. The planned route for a client on a phone. | See *Web app* below |
| **Secure local mode** (`laylaw/secure`, `laylaw/app`) | One person, one computer: encrypted vault, passphrase + OS credential store, tamper-evident audit log, 127.0.0.1-only app. | `python -m laylaw run` |
| **Rapid intakes** (`laylaw/intake`) | Short urgent intakes inside the local app: incident ([docs/INTAKE.md](docs/INTAKE.md)) and criminal/supervision (draft). | Local app home page |
| **Voice interview kit** | Interim runbook for an interview by voice before the phone app is ready. | [docs/VOICE_INTERVIEW_KIT.md](docs/VOICE_INTERVIEW_KIT.md) |

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
laylaw/organize/
  interface.py  read-only export + protocol for a future ORGANIZE stage (case packet lives there)
laylaw/web/          hosted web app (pip install -e ".[web]")
  app.py        routes: sign in/out, start/resume, one-question answer form, autosaved drafts, uploads
  accounts.py   operator-created accounts, scrypt passwords, server-side sessions, lockout, audit log
  crypto.py     AES-256-GCM with per-client HKDF keys; master key from LAYLAW_MASTER_KEY only
  secure_store.py  encrypted drop-in for ClientWorkspace (the engine is unchanged)
  admin.py      operator CLI (create-user, reset-password, confirm-workspace, ...)
  wsgi.py       production entry point (waitress, behind an HTTPS proxy)
laylaw/secure/       secure local mode (pip install -e ".[secure]")
  vault.py      key hierarchy, access gate, recovery code, AES-GCM files bound to logical names
  store.py      encrypted drop-in workspace store (sessions, uploads, deletion); export disabled
  audit.py      HMAC-chained, content-free audit log
  mode.py       real-data readiness gate and passphrase gate with lockout
  secrets_store.py  OS credential store (keyring) with backend allowlist
laylaw/app/
  server.py     127.0.0.1-only local app (launch token, CSRF, Host/Origin checks, idle lock)
  pages.py      no-JavaScript HTML pages
  intake_pages.py  rapid intake screens (/n/... routes)
laylaw/intake/
  steps.py, supervision_steps.py, flows.py   intake questions, stages, conditions, "why we ask"
  model.py      answers, corrections (earlier answers kept), the child's words, evidence
  chronology.py chronology, conflicts, open questions, evidence inventory
  packet.py, supervision_outputs.py   referral packets and their neutrality checks
  service.py    storage in the encrypted vault
laylaw/__main__.py  local-mode CLI: init, run, doctor, recover, change-passphrase, verify-audit, ...
scripts/        double-click launchers for Windows and Mac; supervision visual QA script
docs/
  DEPLOY.md     host requirements for the web app (not deployed)
  LOCAL_MODE.md setup and use of secure local mode
  INTAKE.md     Rapid Incident Intake
  VOICE_INTERVIEW_KIT.md  interim voice interview runbook (ChatGPT Voice + separate recording)
  RESEARCH_BASIS.md  the Research Basis template
  handoffs/     earlier handoff notes (history)
  screenshots/  phone-width screenshots, synthetic data only
tests/
  test_required.py, test_repair_pass.py, test_extra.py, test_audit_repairs.py   engine
  test_web_security.py   auth, sessions, CSRF, two-client isolation, encryption at rest,
                         private uploads, draft/question binding, log privacy
  test_secure_local_mode.py, test_local_app.py   vault, audit log, deletion, local app
  test_rapid_intake.py, test_supervision_intake.py   intakes
.github/workflows/tests.yml  CI: full suite, engine suite on the encrypted store, secret and naming checks
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

## Run

Tests (everything):

```
pip install -e ".[test]"
python -m pytest -q                               # whole suite
LAYLAW_TEST_STORE=encrypted python -m pytest -q   # engine suite again, on the encrypted store
```

The engine has no runtime dependencies (Python 3.10+ standard library only).

**Secure local mode** (`cryptography`, `keyring`):

```
pip install -e ".[secure]"
python -m laylaw init      # once: create the encrypted vault, get the recovery code
python -m laylaw run       # start the local app in the browser
```

**Web app** (`flask`, `cryptography`, `waitress`), local run with synthetic accounts only. Plain
HTTP needs `LAYLAW_COOKIE_SECURE=0`; never use that setting in production:

```
pip install -e ".[web]"
export LAYLAW_DATA_DIR=./laylaw-data LAYLAW_MASTER_KEY="$(python -m laylaw.web.admin generate-key)"
python -m laylaw.web.admin create-user test.fictional --display-name "Test Fictional"
LAYLAW_COOKIE_SECURE=0 waitress-serve --listen=127.0.0.1:8080 laylaw.web.wsgi:app
```

## Quick use (engine)

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

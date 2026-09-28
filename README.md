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
  paths.py      family-law and criminal-defense question paths (same engine, same rules)
tests/
  test_required.py  the 11 tests required by the Claude Code handoff
  test_extra.py     criminal-defense path, safety pause
```

## Run

```
pip install pytest
python -m pytest -q
```

No runtime dependencies (Python 3.10+ standard library only).

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

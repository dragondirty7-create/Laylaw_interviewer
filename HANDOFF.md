# Handoff — Laylaw Interviewer, PR #1 audit repair pass

**Date:** 2026-09-28 (America/Los_Angeles)
**From:** Claude → Soul / Michael
**Input:** Soul audit follow-up, HOLD at `fdd7d449` (https://github.com/dragondirty7-create/Laylaw_interviewer/pull/1#issuecomment-5874385241; Drive mirror *Claude Code Handoff — Laylaw Interviewer*).
**Scope:** the seven audit items only. Architecture, section defaults, and the resolved criminal-path / Build Notes comparison are unchanged. No LLM layer, no new features. Synthetic data only. **Not merged, not deployed.**

## Branch and commits
- **Branch:** `feat/interviewer-core` → `main`. PR #1 head was `fdd7d449` (= audit baseline) when this pass started; no newer work existed to preserve.
- **Repair commits** (in order):

| Commit | What |
|---|---|
| `b64b626` | Regression tests for the seven findings (fail at `fdd7d449`) |
| `52de607` | 1. Traceable source text for facts, corrections, alternate accounts |
| `63ec0d1` | 2. Unknown basis of knowledge stays UNKNOWN |
| `1103ad1` | 3. Acknowledgements, additions, corrections separated |
| `352ec58` | 4. Clarifications bound to exact discrepancy id (incl. save/resume) |
| `00aca9c` | 5. Attributed wording preserved; guard kept for generated advocacy |
| `127a465` | 6. Immediate danger asked separately; plain "Yes" pauses |
| `ae5d5b5` | 7. Conflicts labeled by actual field |
| `a064d5d` | Follow-up edge cases found in self-review (each with a test) |
| `6f6dfb7` | Docs for the pass (reviewed by Soul: one HOLD, below) |
| `10aad5c` | 6 follow-up: a skipped immediate-danger question pauses for safety |

- **Final code SHA:** `10aad5cc8e14d3ecab667210aec9dd8d99d9ccb4`. The only later commit is the documentation commit that adds this update (`HANDOFF.md` only). A commit cannot contain its own hash, so that exact final head SHA and its CI runs are recorded in the PR #1 description and the completion comment.

## Files changed since `fdd7d449`
- **Engine:** `laylaw/interviewer/session.py`, `classify.py`, `guard.py`, `outputs.py`, `paths.py`, `models.py`
- **New tests:** `tests/test_audit_repairs.py` (31 test functions, 56 cases)
- **Updated tests:** `tests/test_required.py` — call-site change only: 13 fact-seeding calls moved from `record_fact(text, topic=…)` (now refused without a logged answer) to `record_statement(…)`; no assertion changed. `tests/test_repair_pass.py` — preflight tests updated for the split danger question and its position; one alternate-account call now logs the interviewee's words first; seeding calls as above.
- **Docs:** `HANDOFF.md`, `README.md`, `SECURITY.md` (one limitation added; real-client restriction unchanged)

## Test results
- `python -m pytest -q`: **97 passed** locally on Python 3.10 and 3.12 (was 40 before this pass, 96 at `6f6dfb7`). Breakdown: `test_required.py` 18, `test_repair_pass.py` 19, `test_extra.py` 3, `test_audit_repairs.py` 57.
- **Regression tests catch the original failures:** the final `tests/test_audit_repairs.py` run against the unmodified `fdd7d449` source gives **40 failed, 12 passed**. Failures per item: 1 → 4, 2 → 3, 3 → 12, 4 → 5, 5 → 2, 6 → 10, 7 → 4. The 12 that pass there are deliberate controls for behavior that must not change (explicit firsthand / secondhand / inference / document typing; bare "No" changes nothing; genuine date conflicts keep the date label).
- The audit's literal reproductions were replayed on the repaired head: generated `record_fact` → `ProvenanceError`; "They were using drugs." → `unknown`; recap "Yes" → fact unchanged, next question "What should I change?"; "Taylor was there." → PEOPLE PRESENT clarified, LOCATION still unresolved; "He was abusive." → all seven outputs render with the wording kept; danger "Yes" → `paused_for_safety`; Library-vs-Park → LOCATION label only.
- CI naming check (legacy name) clean.

## Status of each audit item

| # | Item | Status | What changed |
|---|---|---|---|
| 1 | Traceable source text (audit 4) | **Repaired** | `record_fact`, `correct_fact`, `record_conflicting_account` require an exact slice of a logged answer (`raw_answer_id` + `span`, or a statement found verbatim); otherwise `ProvenanceError` before anything changes. `log_answer(text, question=…)` is the one declared entry for the interviewee's words outside the question flow (kept as a turn with its question); `record_statement` wraps it. Recap/final corrections and document-candidate replies are logged and linked on the `Correction`. Paraphrases are refused on every path. |
| 2 | Unknown basis (audit 5) | **Repaired** | `classify_source` returns firsthand only when the words establish it (own perception, or own act); otherwise UNKNOWN. "How do you know that?" is queued for UNKNOWN and its answer sets the basis (or leaves it UNKNOWN). UNKNOWN survives all outputs and save/load. |
| 3 | Ack / addition / correction (audit 1) | **Repaired** | Each check question has a role. A bare acknowledgement never becomes content: it asks one follow-up ("What should I change?", "Which part did I make sound more certain than you meant?", "What did I miss?"); the numbered-item question comes only after substantive words exist. "Anything I missed?" records additions and replaces nothing. A leading "Yes," is sliced off; the full answer stays on the Correction. |
| 4 | Discrepancy binding (audit 2) | **Repaired** | `PendingQuestion.ref` holds the discrepancy id and is saved/loaded. Answers, skips and "not sure" act on that discrepancy only. Pre-repair saves fall back only when exactly one discrepancy is open for the fact; with several, nothing is resolved and the answer is kept as a note. |
| 5 | Attributed wording vs guard (audit 3) | **Repaired** | The guard takes `attributed` wording (`InterviewSession.attributed_texts()`: answers, statements, fact fields, corrections, intake, requests, document findings/candidates, interviewee-mentioned records). Only attributed strings that would themselves trip a pattern are set aside, verbatim. All renderers and `_emit` use it; Fact Table/Timeline are checked value by value. Engine-authored advocacy still raises. |
| 6 | Immediate danger (audit 6) | **Repaired** (skip follow-up `10aad5c`) | Preflight asks "Is anyone in immediate danger right now?" alone, then "Is there another urgent concern we should know about before we start?". Anything but a clear no ("Yes", "Maybe", "not sure", or **skip**) pauses for safety and is kept as intake (skip as `status="skipped"`, never read as "no"); the safety check is the next question, the pause survives save/reload, and the danger question isn't re-asked after the safety check. "No"/"not yet" to the safety check keeps the pause; "No, I'm safe now" resumes. Non-danger urgency stays administrative intake. |
| 7 | Conflict labels (audit 7) | **Repaired** | `outputs.discrepancy_label()` names the actual field (DATE, LOCATION, PEOPLE PRESENT, SEQUENCE, ACCOUNT) in the Fact Table, Timeline, Open Questions and Interview Record. |

## Final review follow-up (Soul, at `6f6dfb7`)
- **Finding:** a typed or API `skip` on the immediate-danger question was recorded and flagged but left the session ACTIVE, so ordinary preflight continued. Everything else in the pass was reviewed as consistent.
- **Fix (`10aad5c`):** skip now takes the same path as any non-"no" answer: intake `status="skipped"`, a safety note and open question, `PAUSED_FOR_SAFETY`, and the existing safety check next. A clear "No" is unchanged. No redesign of preflight or the safety flow.
- **Test:** `test_6_skipping_the_danger_question_pauses_and_is_not_treated_as_safe` (API and typed skip) asserts the skipped intake item, the pause, the safety question next, the pause after save/reload, and that ordinary preflight resumes only after the safety check. It fails on the `6f6dfb7` code (2 of 2 cases; the session stayed ACTIVE) and passes now.
- **Results:** 97 passed locally (3.10, 3.12). CI on `10aad5cc8e14d3ecab667210aec9dd8d99d9ccb4`, all jobs success (3.10 and 3.12; full suite and naming check):
  - pull_request: https://github.com/dragondirty7-create/Laylaw_interviewer/actions/runs/36466587708
  - push: https://github.com/dragondirty7-create/Laylaw_interviewer/actions/runs/36466582003

## Remaining limitations
- **Real-client use remains blocked.** No authentication, authorization, or encryption at rest (see `SECURITY.md`). This pass does not change that boundary; this is a synthetic-data prototype.
- **Attribution is caller-declared.** `log_answer` / `record_statement` accept the words the caller says the interviewee gave, with the question asked. The engine refuses untraceable and paraphrased text, but it cannot authenticate who typed an answer; that belongs with the authentication prerequisite.
- **Classifiers remain English keyword matching** (sources, acknowledgements, danger/safety, advocacy). They lean cautious — any non-"no" to the danger question pauses — but can misread unusual phrasing. The advocacy guard remains a backstop, not a substitute for review.
- **Firsthand detection is conservative:** some firsthand accounts without a perception/action cue ("The car was blue.") are UNKNOWN until the interviewee answers "How do you know that?". That is intended.
- **Question volume** is unchanged (the LLM layer and question prioritization stay deferred per the audit).
- Prior items still stand: no semantic contradiction detection between free-text answers; correction content is the interviewee's correction sentence, not a merged restatement; next-hearing dates appear in the Timeline.

## Next recommended step
1. Soul's final review of PR #1 at the final head recorded in the PR description and completion comment. PR #1 stays open and unmerged until then.
2. If accepted, merge as a clearly documented synthetic-data library. Real-client use waits for the `SECURITY.md` prerequisites.
3. Then decide on the deferred items: the LLM conversation layer (engine stays the only writer of the record) and question prioritization.

---

# Previous pass (for history) — PR #1 repair pass before the audit

**Date:** 2026-09-28 (America/Los_Angeles)
**From:** Claude (Claude Code) → Soul / Michael
**Sources of truth:** *Laylaw Interviewer — Canonical Specification*; *Claude Code Handoff — Laylaw Interviewer*; *Laylaw — Interviewer Agent, Client Workspaces & Criminal Defense — Build Notes* (read 2026-09-28, after it was shared); the repair-pass instructions (2026-09-28).

## Repo, branch, commits
- **Repo:** https://github.com/dragondirty7-create/Laylaw_interviewer
- **Branch:** `feat/interviewer-core` → `main`. **PR:** https://github.com/dragondirty7-create/Laylaw_interviewer/pull/1 (not merged)
- **Code head commit:** `28a3c1c` (Build Notes alignment). It follows `d119955` (the repair pass). Commits after `28a3c1c` change only `HANDOFF.md`.
- **Previous head:** `b6faa7e` (pass 1).

## Tests
`python -m pytest -q`: **40 passed**, run locally on Python 3.11. Breakdown: `test_required.py` 18 (the 11 required tests, with test 2 run for 7 date phrasings, plus one hedging case), `test_repair_pass.py` 19, `test_extra.py` 3.
Mutation check: I disabled 19 rules one at a time and **each change made a test fail**. The 14 repair-pass rules are listed below. The 5 Build Notes rules are: workspace gate, "not sure" is not confirmation, summary separation, notes-aligned family default, and no safety section by default. The rules: correction keeps the original, control detection, save-later pending, criminal default, proposition split, location overwrite, witness typing, family default, candidate overwrite, intake-as-fact, strict item targeting, paraphrase refusal, research review gate, final-check correction.
An end-to-end demo run found 2 bugs, both fixed with regression tests: a bare "No" was recorded as a requested outcome, and a hedge didn't cover the date in the same statement.

## Files changed (since `b6faa7e`)
- **Engine:** `laylaw/interviewer/session.py`, `models.py`, `classify.py`, `outputs.py`, `paths.py`
- **New:** `laylaw/interviewer/research_basis.py`, `laylaw/organize/__init__.py`, `laylaw/organize/interface.py`, `docs/RESEARCH_BASIS.md`, `SECURITY.md`, `.github/workflows/tests.yml`, `tests/test_repair_pass.py`
- **Updated:** `tests/test_extra.py` (criminal-path test moved to the new section names), `README.md`, `HANDOFF.md`
- `tests/test_required.py` is **unchanged**. All 11 required tests still pass.

## Status of each item

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Structured corrections | **Complete** | Recap and final-check corrections create a new fact in the interviewee's words, linked by `correction_of` / `superseded_by`. The original is kept and marked SUPERSEDED. A `Correction` record stores `via`, target, and new version. If the target is unclear, the engine lists the numbered items and asks which one. A number inside a correction ("2 kids were there") is never taken as an item number. The Fact Table, Timeline (original and correction side by side), Interview Record, and Handoff all show both versions. |
| 2 | Skip / Not sure / Save-and-finish-later | **Complete** | Handled by the engine, either as `skip()` / `not_sure()` / `save_and_finish_later()` or when the whole answer is the command. Turns carry `control`, and no fact is ever created. "Not sure" on a date stores UNKNOWN. Save-for-later keeps the exact pending question and resumes there after reload. Tested for both the opening prompt and clarifying questions. |
| 3 | Criminal-defense path | **Complete, checked against Build Notes** | Order: charges exactly as on paperwork → court / case number / next hearing → custody or release conditions → attorney or public defender status → procedural history → available records. This matches the Build Notes path and its rule "start with paperwork and procedural facts". An account of the events is only an optional section and is off by default. The notice says plainly that nothing is covered by attorney-client privilege. It uses the same engine. |
| 4 | Intake / preflight | **Complete** | Neutral questions: workspace confirmation (added from the Build Notes), immediate danger or urgent concern, upcoming hearing or deadline, what they need help with first, and for criminal matters custody and counsel status. Answers are stored as `IntakeItem` administrative metadata, separate from facts. An urgent-danger answer pauses the interview for safety. Preflight is on by default for `start_path`; direct `InterviewSession.start` doesn't use it. |
| 5 | Proposition splitting | **Complete** | The raw answer is always kept. Propositions are exact `[start, end)` slices of it, each with its own source, certainty, and date. The date comes only from the interviewee's own words in that slice. `record_proposition` accepts only a slice. A statement that isn't an exact slice (e.g. an LLM paraphrase) raises `ProvenanceError`. Splitting uses deterministic sentence boundaries. |
| 6 | Broader discrepancies | **Complete (detection limits noted)** | Location, people present, sequence, and "account" conflicts keep both recollections and ask the spec's neutral question. The engine never picks a version. Detection covers: the same fact re-answered, facts sharing an `event_key`, conflicting `record_sequence` calls, and `record_conflicting_account`. **It cannot detect contradictions in meaning between free-text answers**; that needs the future LLM layer and is flagged. |
| 7 | Supporting-source typing | **Complete** | The `SupportingSourceType` labels are document/file, email/text, court record, witness/person, and other. A witness is never stored as a document; it is labeled POTENTIAL WITNESS and sets WITNESS IDENTIFIED. The type carries through to provenance labels and the Evidence Follow-up list. |
| 8 | Adaptive paths | **Complete** | The 26 canonical family-law sections are preserved in `available_sections`. The default is the Build Notes family path (11 sections; see the Build Notes check below), not all 26. "Specific safety concerns" is never in the default. `suggest_sections` works from the interviewee's own intake words and only suggests; nothing is added automatically. `add_section` and `remove_section` check against the canonical set. |
| 9 | Document-derived candidates | **Complete** | `propose_document_candidate` stores a candidate that is never merged into the recollection or the timeline. `respond_to_candidate` handles confirm, correct, or reject. Confirm and correct create a linked new version in the client's words; the original is kept. |
| 10 | Case packet after INTERVIEW | **Complete (interface only, by design)** | The 7 canonical outputs are unchanged. `laylaw.organize.export_for_organize` provides a versioned read-only snapshot, with rules for later stages. An `Organizer` protocol covers overview, timeline, document index, missing-info checklist, and questions for counsel. No ORGANIZE logic is built, and INTERVIEW still refuses the later stages. |
| 11 | Research Basis | **Complete** | Canonical template in `docs/RESEARCH_BASIS.md`, plus `research_basis.py`. `mark_applied` refuses unreviewed entries and single blog or advocacy sources. Conflicts are flagged and preserved. The engine never reads it. No research entries were added. |
| 12 | CI | **Complete, passing** | `.github/workflows/tests.yml` runs the full pytest suite on every push and PR (Python 3.10 and 3.12), plus a naming check. The first runs on `c64a802` passed for both push and pull_request: https://github.com/dragondirty7-create/Laylaw_interviewer/actions/runs/36436112134 |
| 13 | Synthetic-only data | **Complete** | Repo scan: no real names (including the spec's examples), no uploads, logs, screenshots, or snapshots, and no legacy project name. |
| 14 | Storage security documented | **Complete** | `SECURITY.md` and README: no encryption at rest, no authentication; directory isolation is not a multi-user security boundary; not production-ready. |

## Build Notes check (read after it was shared)
| Build Notes item | Status |
|---|---|
| One shared interviewer, separate family-law and criminal-defense paths, calm tone, one question at a time, remembers answers, resumes | Already in place |
| Skip, Not sure, Save and finish later | Already in place (item 2) |
| **Choose the client and case type; confirm whose workspace is open** | **Added now.** The first preflight question confirms the interviewee and case. "No", "skip" or "not sure" stops the interview (`next_question()` returns nothing) until an operator calls `confirm_workspace()`. |
| Urgency: hearings, deadlines, immediate concerns; criminal custody and lawyer | Already in place (item 4) |
| "What do you need help with first?" | Already in place, same wording |
| Documents: multiple uploads; extract dates and details, then client confirms | Uploads and confirmation are in place (item 9). No automatic extractor is built; any extractor must go through `propose_document_candidate`. |
| **Family-law path: children and current arrangements, existing orders and filed papers, service status, income/expenses/support, relevant events and supporting records** | **Added now.** This is the default family selection: Case basics, Current household (children and arrangements), Current parenting routine, Court orders, Court filings, Service status, Finances, Support history, Specific incidents (neutral prompt that allows "none"), Available records, and Current requested arrangement. Specific safety concerns is never in the default. |
| Criminal-defense path | Matches (item 3) |
| **Review the summary together: what the client reported / what documents show / what remains unknown** | **Added now.** Before the final check, a summary review lists these three separately. Unconfirmed document candidates are labeled "not yet confirmed by you". |
| Case packet (overview, dated timeline, document index, missing-info checklist, questions for counsel) | Interface only, after INTERVIEW (item 10) |
| Two more client workspaces, separate documents, answers and timelines | Supported by the workspace model and tested for isolation. The actual client names and details still need to be supplied; none were created. |
| Fictional-case tests (interrupted, save/resume, uploads, workspace separation) | In place |
| Rename the legacy naming in Drive folders, documents and labels | **Outside this repo.** No legacy name appears in the repo (CI checks). Renaming the Drive items is a separate task after reviewing references and links. |

## Remaining deviations / known gaps
- **Classifiers are still keyword matching** (English only), including hedges, sources, controls, witness typing, safety, and the advocacy guard. They lean toward caution but will miss unusual phrasing. There is no conversational LLM layer yet.
- **Question volume:** every proposition gets the full set of follow-up questions (when, who, where, how do you know, what next, records). A long account can produce many questions. Prioritizing by importance is not built.
- **Correction content** is stored as the interviewee's correction sentence ("It was Tuesday, not Monday"). The engine does not produce a merged restatement, since that would put words in their mouth. A date in the correction's own words is recorded.
- **Next-hearing dates** are recorded as dated facts (with the question they answered), so they appear in the Timeline alongside past events.
- **Security:** see `SECURITY.md`. Not for real client data yet.

## Next recommended step
1. Soul/Michael review PR #1, especially the default section sets, the preflight wording, and the correction flow's "Which numbered item…" prompt.
2. Supply the two new (real) client workspaces' labels when ready. They stay outside the public repo.
3. Merge after review. Then choose between (a) an LLM conversation layer over this engine, with the engine staying the only thing that writes the record, and (b) prioritizing clarifying questions by importance to cut question volume.

# Handoff — Laylaw Interviewer, PR #1 repair pass

**Date:** 2026-09-28 (America/Los_Angeles)
**From:** Claude (Claude Code) → Soul / Michael
**Sources of truth:** *Laylaw Interviewer — Canonical Specification*; *Claude Code Handoff — Laylaw Interviewer*; the repair-pass instructions (2026-09-28).

## Repo, branch, commits
- **Repo:** https://github.com/dragondirty7-create/Laylaw_interviewer
- **Branch:** `feat/interviewer-core` → `main`. **PR:** https://github.com/dragondirty7-create/Laylaw_interviewer/pull/1 (not merged)
- **Code head commit:** `d119955`, the repair pass. The commit that adds this file changes only `HANDOFF.md`.
- **Previous head:** `b6faa7e` (pass 1).

## Tests
`python -m pytest -q`: **38 passed**, run locally on Python 3.11. Breakdown: `test_required.py` 18 (the 11 required tests, with test 2 run for 7 date phrasings, plus one hedging case), `test_repair_pass.py` 17, `test_extra.py` 3.
Mutation check: I disabled 14 new rules one at a time and **each change made a test fail**. The rules: correction keeps the original, control detection, save-later pending, criminal default, proposition split, location overwrite, witness typing, family default, candidate overwrite, intake-as-fact, strict item targeting, paraphrase refusal, research review gate, final-check correction.
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
| 3 | Criminal-defense path | **Complete, pending check against build notes** | Order: charges exactly as on paperwork → court / case number / next hearing → custody or release conditions → attorney or public defender status → procedural history → available records. An account of the events is only an optional section and is off by default. The notice says plainly that nothing is covered by attorney-client privilege. It uses the same engine. **The Build Notes doc was not visible to this account**, so the path follows the order in your repair instructions. It still needs checking against the build notes. |
| 4 | Intake / preflight | **Complete** | Neutral questions: immediate danger or urgent concern, upcoming hearing or deadline, what they need help with first, and for criminal matters custody and counsel status. Answers are stored as `IntakeItem` administrative metadata, separate from facts. An urgent-danger answer pauses the interview for safety. Preflight is on by default for `start_path`; direct `InterviewSession.start` doesn't use it. |
| 5 | Proposition splitting | **Complete** | The raw answer is always kept. Propositions are exact `[start, end)` slices of it, each with its own source, certainty, and date. The date comes only from the interviewee's own words in that slice. `record_proposition` accepts only a slice. A statement that isn't an exact slice (e.g. an LLM paraphrase) raises `ProvenanceError`. Splitting uses deterministic sentence boundaries. |
| 6 | Broader discrepancies | **Complete (detection limits noted)** | Location, people present, sequence, and "account" conflicts keep both recollections and ask the spec's neutral question. The engine never picks a version. Detection covers: the same fact re-answered, facts sharing an `event_key`, conflicting `record_sequence` calls, and `record_conflicting_account`. **It cannot detect contradictions in meaning between free-text answers**; that needs the future LLM layer and is flagged. |
| 7 | Supporting-source typing | **Complete** | The `SupportingSourceType` labels are document/file, email/text, court record, witness/person, and other. A witness is never stored as a document; it is labeled POTENTIAL WITNESS and sets WITNESS IDENTIFIED. The type carries through to provenance labels and the Evidence Follow-up list. |
| 8 | Adaptive paths | **Complete** | The 26 canonical family-law sections are preserved in `available_sections`. The default is a short neutral set of 7 with no allegation-type sections. `suggest_sections` works from the interviewee's own intake words and only suggests; nothing is added automatically. `add_section` and `remove_section` check against the canonical set. |
| 9 | Document-derived candidates | **Complete** | `propose_document_candidate` stores a candidate that is never merged into the recollection or the timeline. `respond_to_candidate` handles confirm, correct, or reject. Confirm and correct create a linked new version in the client's words; the original is kept. |
| 10 | Case packet after INTERVIEW | **Complete (interface only, by design)** | The 7 canonical outputs are unchanged. `laylaw.organize.export_for_organize` provides a versioned read-only snapshot, with rules for later stages. An `Organizer` protocol covers overview, timeline, document index, missing-info checklist, and questions for counsel. No ORGANIZE logic is built, and INTERVIEW still refuses the later stages. |
| 11 | Research Basis | **Complete** | Canonical template in `docs/RESEARCH_BASIS.md`, plus `research_basis.py`. `mark_applied` refuses unreviewed entries and single blog or advocacy sources. Conflicts are flagged and preserved. The engine never reads it. No research entries were added. |
| 12 | CI | **Complete; first run pending** | `.github/workflows/tests.yml` runs the full pytest suite on every push and PR (Python 3.10 and 3.12), plus a naming check. I will confirm the first run after pushing. |
| 13 | Synthetic-only data | **Complete** | Repo scan: no real names (including the spec's examples), no uploads, logs, screenshots, or snapshots, and no legacy project name. |
| 14 | Storage security documented | **Complete** | `SECURITY.md` and README: no encryption at rest, no authentication; directory isolation is not a multi-user security boundary; not production-ready. |

## Remaining deviations / known gaps
- **Criminal path vs Build Notes:** not yet checked against the build notes (the doc isn't shared with this account).
- **Classifiers are still keyword matching** (English only), including hedges, sources, controls, witness typing, safety, and the advocacy guard. They lean toward caution but will miss unusual phrasing. There is no conversational LLM layer yet.
- **Question volume:** every proposition gets the full set of follow-up questions (when, who, where, how do you know, what next, records). A long account can produce many questions. Prioritizing by importance is not built.
- **Correction content** is stored as the interviewee's correction sentence ("It was Tuesday, not Monday"). The engine does not produce a merged restatement, since that would put words in their mouth. A date in the correction's own words is recorded.
- **Next-hearing dates** are recorded as dated facts (with the question they answered), so they appear in the Timeline alongside past events.
- **Security:** see `SECURITY.md`. Not for real client data yet.

## Next recommended step
1. Share the Build Notes doc with rehearsal@eecmusic.org (or paste the criminal-defense section) so the criminal path can be checked against it.
2. Soul/Michael review PR #1, especially the default section sets, the preflight wording, and the correction flow's "Which numbered item…" prompt.
3. Merge after review. Then choose between (a) an LLM conversation layer over this engine, with the engine staying the only thing that writes the record, and (b) prioritizing clarifying questions by importance to cut question volume.

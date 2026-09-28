# Handoff — Laylaw Interviewer, implementation pass 1

**Date:** 2026-09-28 (America/Los_Angeles)
**From:** Claude (Claude Code) → Soul / Michael
**Source of truth:** *Laylaw Interviewer — Canonical Specification* + *Claude Code Handoff — Laylaw Interviewer* (Drive)

## Repo and branch
- **Path:** `/home/claude/laylaw` (a local git repo in Claude's cloud workspace)
- **Branch:** `feat/interviewer-core` (off an empty `main`)
- **Remote / PR:** none yet. No existing Laylaw repo was found locally, so Michael directed a fresh start. It needs pushing to a GitHub repo for a PR to exist.

## Files
- `laylaw/interviewer/models.py`, `classify.py`, `session.py`, `guard.py`, `outputs.py`, `workspace.py`, `paths.py`, `__init__.py`
- `tests/conftest.py`, `tests/test_required.py`, `tests/test_extra.py`
- `README.md`, `HANDOFF.md`, `pyproject.toml`, `.gitignore`

## What actually works (verified by executable tests)
- The interview flow: orientation text, then a free account per section, then one clarifying question at a time (when, who, where, how do you know, certainty split, what happened next), then the record-hook question, then a recap with the three end-of-section checks, then the four-question final check.
- Uncertainty is preserved. Hedges are kept verbatim. Date precision uses the spec's six labels, and hedged statements are never given an EXACT date.
- Source-of-knowledge tagging uses the seven spec labels. Secondhand accounts, including a child's reported statements, can't be relabeled as observation unless the adult says they witnessed the underlying event.
- Conflicting dates for the same event keep both recollections. The engine asks the spec's neutral clarifying question and flags `[UNRESOLVED DATE DISCREPANCY]` if the interviewee can't say which is closer.
- When a document is checked, the spec's three-part record (interviewee recollection, document content, consistency or difference) is written separately. The original recollection is never edited.
- Records show as "POTENTIAL SUPPORTING RECORD" until reviewed. Fact verification uses the spec's eight statuses, with no "verified".
- Requested outcomes go in a separate list and are refused as facts. Routine patterns and specific incidents are recorded separately.
- An INTERVIEW-mode guard blocks advocacy, strategy, and legal-analysis text, and requests for the later stages are refused.
- Interviews save after every write (atomic saves), can be interrupted, and resume with the spec's "I have us stopped at…" prompt, picking up at the same unanswered question.
- Transcript status uses the spec's five values. Reconstructed notes are labeled as not a transcript. Quotation marks appear only with a verbatim transcript or when the interviewee remembers the exact wording.
- Client workspaces are isolated: ID validation, a path-escape guard, and a client-ID check on every load and save. Uploads are hashed and tied to their client and session.
- Present-danger wording pauses the interview for a safety check, then returns to the same question. Starting an interview with a child is refused.
- The criminal-defense path runs on the same engine, with a notice stating plainly that nothing is covered by attorney-client privilege.

## Tests run
`python -m pytest -q`: **21 passed** (11 required, with test 2 run for 7 date phrasings, plus 1 extra hedging case and 3 extras).
Mutation check: key rules were disabled one at a time (secondhand guard, child rule, date overwrite, load isolation, approximate dates, corroboration label, interrupt save, mode guard), and each change made at least one test fail.

## Known gaps / deviations
- **The classifiers are English-only keyword matching, not an LLM.** They lean toward uncertain, but will miss unusual phrasings. A conversational LLM layer has not been built.
- Each free-account answer is recorded as one fact. Splitting a long narrative into separate propositions is not implemented.
- Discrepancy detection covers dates only (not people, places, or sequence).
- The spec's "Research Basis" file (methodology sources) is not implemented.
- There is no UI and no audio transcript capture. Storage is plain JSON files with no encryption at rest.
- The criminal-defense sections are my own neutral first draft; the Drive build notes weren't available to check them against.
- The present-danger detector is a keyword list; it is a backstop, not a substitute for human judgment.

## Next recommended step
Push to a GitHub repo and open a PR, then have Soul review the classifier word lists and the criminal-defense sections against the spec. After that, add the LLM conversation layer on top of this engine, keeping the engine as the source of truth for what gets recorded.

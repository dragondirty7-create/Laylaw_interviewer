# Brief A: lighter, smoother interview questions

**For:** Claude Code · **Written:** 2026-10-23 by Claude · **PR base:** `integrate/one-laylaw` (PR #14), or `main` once #14 is merged

## Why

Michael, 2026-10-23: the last interview "felt choppy". Two causes are confirmed in the engine:

1. **The "I'm done" loop.** `_NOTHING_MORE` in `laylaw/interviewer/session.py` is used with
   `fullmatch`. It accepts *"No."* and *"Nothing else."* but rejects natural answers such as
   *"No, that's all."*, *"No that is all"*, *"Nope, nothing else."* and *"That's everything."* Each of
   those is recorded as a new **fact**, which queues the whole follow-up set again. First found
   2026-09-29 (see `docs/handoffs/2026-09-29-pr3-secure-local-mode.md`) and never fixed.
2. **Too many follow-ups per fact.** `_queue_clarifications()` queues up to seven questions after
   every fact: *About when was this? / Who else was there? / Where did this happen? / How do you know
   that? / How sure are you? / What happened next? / Is there anything that might help document or
   date this?* Five facts in, it feels like an interrogation.

## Read first

`HANDOFF.md` (sections 3–4), `README.md` (controls, corrections, provenance), `laylaw/interviewer/session.py`
(`_queue_clarifications`, `_NOTHING_MORE`, `_NO_WORD`, the recap and final-check flow),
`laylaw/interviewer/paths.py` (section specs), and the existing tests in `tests/test_required.py` and
`tests/test_audit_repairs.py`. Those encode Soul's audit rules and must keep passing unchanged.

## Build

1. **End-of-answer phrases.** Accept common "that's all" forms as a whole answer: a leading
   no/nope/nah, an optional comma, then that's all / that's it / that is all / nothing else /
   that's everything / nothing more / I think that's it. Keep `fullmatch`. Anything with added content
   must still be recorded. *"No, then he left."* and *"No, he took the car."* are facts, not endings.
   Test both sides with a table of at least 15 phrases.
2. **Ask only what's missing and what matters for that kind of fact.**
   - Never ask for something the answer already gave (date, people, place, source). Today's checks
     mostly do this; keep them.
   - **Routine facts** ("usually", "every Tuesday"): no *Where did this happen?* or *What happened
     next?*. Keep *Was there a particular time that was different?*.
   - **Requests and outcomes:** no follow-ups (already the case).
   - **"Who else was there?"** only for events, not for states or routines.
   - **"How sure are you?"** only when the answer was hedged (already the case).
   - Put the questions in a fixed priority order: source first, because an unknown basis matters
     most, then date, then people, then place, then next.
   - Cap them at **three per fact** by default, set per section in `paths.py`. Anything not asked goes
     into **Open Questions**, so nothing is lost silently.
3. **Ask "anything to document this?" once per section, not once per fact.** Move the record hook to
   just before the end-of-section recap: *"Is there anything that might help document or date what
   you've told me in this section?"* Keep the per-fact link when the answer names a document.
4. **Leave alone:** the safety pause, the immediate-danger preflight, corrections that never
   overwrite, provenance (`log_answer` is the only way to enter the client's words),
   one-question-at-a-time, and open-ended wording that never suggests an answer.

## Done when

- A synthetic five-fact family-law transcript asks **at most 15 follow-up questions in total**
  (measure today's number first and put both in the PR), and no question repeats something already answered.
- Every "that's all" phrase in the table ends the follow-ups; every content phrase is recorded as a fact.
- Unasked follow-ups appear in Open Questions.
- `python -m pytest -q` and `LAYLAW_TEST_STORE=encrypted python -m pytest -q` both pass. All existing
  tests pass **without being edited**. If one must change, explain why in the PR for Soul.
- A mutation check: break the new phrase handling on purpose and a test goes red.
- Naming check is clean (CI).

## Deliver

- Branch `feat/lighter-questions`, **draft** PR to the base above. Title: "Lighter interview follow-ups + fix the 'No, that's all' loop".
- PR body: what changed, the before/after question count, test results, and anything left for Soul.
- Update `HANDOFF.md`: section 3 (mark what's fixed), section 4 (A done, link the PR), "Last updated".
- Synthetic data only. No merge, no deploy.

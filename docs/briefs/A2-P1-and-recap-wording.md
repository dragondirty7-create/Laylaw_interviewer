# Brief A2-next: Follow-up v2 P1, then the recap wording change

**For:** Claude Code · **Written:** 2026-10-25 by Claude (chat), for Michael · **Reviewer:** Soul

**Go-ahead:** Michael, 2026-10-25, after Soul's review of PR #16
([comment](https://github.com/dragondirty7-create/Laylaw_interviewer/pull/16#issuecomment-6405760424)).
Soul's six decisions are in `HANDOFF.md` §4 under A2. This brief turns them into two draft PRs.

**Full requirements:** the Drive doc *NEEDS CLAUDE CODE — Laylaw Brief A2: Follow-up v2 (2026-10-23)*
([link](https://docs.google.com/document/d/1UJyoDanjKK42xUW1xV1lDo6Tmq7Efuub_mlp4lz14po/edit)),
§4 (P1), §3 item 0.4, §5.4 (fixtures) and §6 (wording bank). Where this brief and the Drive doc
disagree, **this brief wins**, because it includes Soul's 2026-10-25 decisions.

## Ground rules

- **Two separate draft PRs, in this order:**
  1. **PR A2-P1**, stacked on PR #16 (branch `ccr-346c90bc-1umwms-a2`).
  2. **PR A2-wording**, stacked on PR A2-P1. Both touch `session.py`, so stacking avoids conflicts.
     Soul asked for the wording to be its own draft so it can be reviewed and reverted alone.
- Say in each PR description which branch it's stacked on. Rebase if #15 or #16 changes in review.
- **No merge, no deploy, synthetic data only, no case content anywhere.**
- **Feature B and P2 are out of scope.** B stays gated on #15's approval.
- **Changed test rule (Soul's decision 3):**
  - You may change **only** the tests needed to assert the new intended behaviour.
  - Each changed test must keep equivalent protection for provenance, certainty, one question at a
    time, neutral wording, corrections and safety.
  - **Never delete a test to get green.**
  - List every changed test in the PR as a table: file and test, old assertion, new assertion, and what
    still protects the old rule.
- **Verification bar (unchanged):**
  - full suite, plus the encrypted-store run;
  - a mutation check for each new invariant (break it, show the test fails, restore it);
  - the CI naming check;
  - before/after counts on `run_five_fact_transcript`.

## PR A2-P1: what to build

Follow Drive §4, with these changes from Soul:

1. **1.1 Free-recall opener.**
   - Open each section with: *"Tell me about [topic] in your own words — whatever comes to mind, in
     any order."*
   - Then run follow-ups grouped by event, in the person's order, finishing one event before the next.
   - The ordering tests that pin *"About when was this?"* first may now change, under the test rule above.
2. **Scope wording (Soul's decision 1).**
   - When it's unclear which events an explanation covers, ask: *"Which of those events does that
     explanation apply to?"* One question at a time.
   - A bare "Yes" or "No" stays unclear. Nothing is applied, and the event gets provenance unspecified
     plus an Open Questions entry.
   - Add test cases for:
     - partial scope ("just the first two");
     - ambiguous wording ("most of them", "I think so").
   - Neither case may apply a basis to an event the person didn't clearly name.
3. **"Huh?" outside follow-ups (Soul's decision 6, priority).**
   - At an opening prompt, recap or final check, "Huh?" / "What do you mean?" / "I'm confused" must
     **never** be stored as a fact, an addition or a correction.
   - First time: rephrase once. Second time: offer to skip or answer in their own words.
   - Log the outcome in the register.
4. **1.2 Deferred questions at recap.**
   - At most 2, in this priority order: unresolved provenance, then conflict, then certainty, then the
     rest.
   - Ask permission first. If the person declines, the questions go to Open Questions.
   - Never ask anything already answered, skipped, or answered "don't know".
5. **1.3 Fatigue and distress.**
   - Build it as specified in the Drive doc.
   - **Never drop a provenance, certainty or conflict check without an Open Questions entry** (Soul's
     decision 4).
6. **1.4 Patterns vs. single events, and 1.5 certainty asked once:** as specified in the Drive doc.
7. **"I don't know" stays visible (Soul's decision 2).** Check that an unknown answer shows on the fact
   record and in every output (organizer, exports). Add a test if any output drops it.
8. **Limits are provisional (Soul's decision 4).**
   - Keep 3 follow-ups per fact and 2 deferred questions at recap.
   - Add the Drive §5.4 fixtures: rambler, goes quiet, distressed / asks to stop, "don't know"
     repeater, many events in one breath.
   - Report in the PR, per fixture:
     - follow-up count;
     - which checks ended up in Open Questions;
     - any fact left without confirmed or explicitly unspecified provenance.
   - Don't tune the limits. Just report.

## PR A2-wording: what to build (Soul's decision 5)

1. **Recap question:**
   - Use *"What did I get wrong or leave out?"*
   - **Keep the separate "more certain than you intended" check.** It may be reworded, but it must stay.
2. **Record question:** *"Is there something else that might help document this?"*
3. **Final check:** use "something", not "anything". Follow the wording bank in Drive §6.
4. **Record question after the recap: optional.** If you move it, prove both of these with tests:
   - it's asked exactly once per section;
   - anything the person adds in reply still gets its own provenance question, or an Open Questions
     entry. Nothing gets stranded after the recap.
5. **Keep record-to-fact traceability, and keep corrections with their history.**
6. **Lint test:** ban *"Is that right?"*, *"Correct?"* and *"anything else"* in the recap and closing
   templates.

## Handback

- Each PR description must include:
  - the changed-tests table;
  - before/after counts;
  - fixture results;
  - mutation-check evidence;
  - anything skipped and why, as **NEEDS SOUL** decisions.
- Update `HANDOFF.md` §4 **after** each PR is verified, not before.
- Post a short comment on #16 linking each new PR.
- If usage runs low, leave a handoff in Drive → AI Agent Notes titled *NEEDS CLAUDE CODE — Laylaw
  A2-next (continued)* before stopping.

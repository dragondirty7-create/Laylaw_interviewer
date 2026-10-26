# Laylaw: status page

**This is the one place to check Laylaw's status.** Every agent (Soul, Claude, Codex/Forge, Gemini)
reads it before starting and updates it when they finish. The Drive *PROJECT INDEX — Laylaw* links
here instead of keeping its own copy. Older handoff notes are in [`docs/handoffs/`](docs/handoffs/)
and are history: nothing in them is an open task unless this page lists it.

**Last updated:** 2026-10-25 (America/Los_Angeles) by Claude Code: Soul's 2026-10-25 review of PR #16 recorded; the offered-skip logging fix is pushed.

## Ground rules (unchanged)

- **Synthetic data only.** Nothing in this repo is approved for real client data yet.
- **No merge, deploy or real-client use without Soul's review and Michael's OK.**
- **The Interviewer engine is the only writer of the factual record.** Other parts call it; they
  never edit facts themselves.
- **No case content** in code, tests, issues, PRs, commits, screenshots or logs.
- Golden rule: *do not make the case better; make the record better.*

## 1. Where the code is

`main` is still at `eaf01c8` (PR #1, 2026-09-28). Since then, work has been split across six open PRs.
The branch **`integrate/one-laylaw`** ([PR #14](https://github.com/dragondirty7-create/Laylaw_interviewer/pull/14), draft) combines all of them so there is one version to run, test and
review. Combined result: **218 tests pass**, and **217 pass + 1 skipped** when the engine suite is re-run
on the encrypted store. That is exactly the sum of the separate stacks (97 engine + 34 web + 87 local,
intake and supervision), so no test was lost. No Python file conflicted. Only the docs and config
files had to be combined.

| Part | Code | From | Soul's latest word |
|---|---|---|---|
| Interviewer engine | `laylaw/interviewer/`, `laylaw/organize/` | PR #1 (merged) | Merged; synthetic data only |
| Hosted web app (sign-in, encrypted per-client storage, uploads) | `laylaw/web/` | PR #5 | **2026-10-21: the primary path for Chelsea on her phone.** Harden it (section 2); no merge under that note |
| Secure local mode (one computer, encrypted vault) | `laylaw/secure/`, `laylaw/app/`, `laylaw/__main__.py`, `scripts/` | PR #3 | Awaiting security review. 2026-10-21: don't turn it into a second hosted app |
| Rapid Incident Intake | `laylaw/intake/`, `laylaw/app/intake_pages.py` | PR #11 | 2026-10-21: use it as the **design source** for the web app's phone screens |
| Rapid Supervision Intake | `laylaw/intake/supervision_*.py`, `flows.py` | PR #12 (draft) | 2026-10-17: received; **not approved for merge or real-client use** |
| Voice interview kit | `docs/VOICE_INTERVIEW_KIT.md` | PR #13 | Interim runbook; not reviewed yet |
| Docs refresh | (folded into this page) | PR #4 | Replaced by this page |

**Left out on purpose:** branch `claude/be-here-later-review-dzzomw`. It is a design review for *Be
Here Later*, a download manager, and has nothing to do with Laylaw. It should move to its own repo.

**How the PRs relate after this lands:** if Soul approves the integration PR, the PRs it contains can be
closed as merged-through-integration. If Soul wants parts held back (for example #12), those merges can
be reverted on the integration branch before it merges.

## 2. Web app: Soul's 2026-10-21 phone and durability list (PR #5)

| # | Item | Status |
|---|---|---|
| 1 | Tie draft autosave to the exact question; reject stale saves | **Done** in `e72f64b` (409 on a stale save, with phone/desktop conflict tests) |
| 2 | Make saving reliable when the page closes, and test real phone backgrounding | Open |
| 3 | Clear "Saving… / Saved / Offline, not saved" state with last-saved time and retry | Open |
| 4 | Port PR #11's phone controls (44px targets, progress, choice cards, Back / Save for later, review page, 320–390px checks) | Open |
| 5 | Cross-device concurrency tests | Partly done (draft conflicts in `e72f64b`); answer and question advance across devices still to test |
| 6 | Second sign-in factor (2FA) **before** any real client | Open |
| 7 | Phone smoke test on a deployed instance with synthetic data | Open (needs a host) |

## 3. Interview problems reported 2026-10-23 (Michael)

1. **The interviewer didn't know about Chelsea's filed documents.**
   - Uploads are stored per *interview* (`uploads/<interview id>/…`), not per case, so a new interview
     starts with none of them.
   - Nothing reads what a document says. Uploads are kept and fingerprinted, but no dates, orders or
     filings are pulled out to shape the questions.
   - A voice-kit session starts from a blank chat, and the kit gives it no summary of what is on file.
2. **The flow felt choppy.** *Fixed in step A (draft PR, branch `ccr-346c90bc-1umwms`), pending Soul's review.*
   - ~~After every fact, `_queue_clarifications` queues up to seven follow-ups.~~ Now at most three per
     fact by default (`SectionSpec.max_followups` in `paths.py`); source and certainty checks are always
     asked; the rest go to Open Questions. Routine facts and states skip "who else / where / what next";
     one answer split into several items is treated as one account; "anything to document this?" is asked
     once per section, before the recap.
   - ~~**Confirmed bug:** *"No, that's all."* / *"Nope, nothing else."* recorded as facts and restarted the
     follow-ups.~~ Fixed: 21 "that's all" forms end the follow-ups; 15 content forms (*"No, then he left."*)
     are still recorded. On the synthetic five-fact transcript: before, the loop never ended (294
     follow-ups in 300 turns); after, 14 follow-ups.
   - The voice kit adds a spoken recap, a "Is anything wrong or missing?" check and a full text
     checkpoint at the end of every section.

## 4. Next steps

Each one is its own PR from `main` (after this integration lands) or from `integrate/one-laylaw`.
Soul reviews each before the next starts. Ready-to-run Claude Code briefs are in
[`docs/briefs/`](docs/briefs/): open a Claude Code session on this repo and say *"Read
`docs/briefs/A-lighter-questions.md` and do it."*

- **A. Lighter, smoother questions** (engine). **Built; draft PR #15 awaiting Soul's review** (branch
  `ccr-346c90bc-1umwms`, base `integrate/one-laylaw`). Tests: `tests/test_lighter_questions.py`.
- **A2. Follow-up v2** (engine; brief in Drive → AI Agent Notes, "Laylaw Brief A2"). **P0 built; draft PR
  stacked on #15** (branch `ccr-346c90bc-1umwms-a2`). Tests: `tests/test_followup_v2.py`.
  - Built: one "How do you know about these?" per multi-event answer, a scope check in the person's own
    words, and no silent inheritance (0.1). "I don't know", "Skip", "I don't understand" (rephrase once,
    then offer to skip) (0.2). A per-session register so nothing is asked twice (0.3). A recap body made
    only of the person's words, plus a lint test (0.4).
  - Skipped (existing tests pin the wording): the new recap/record/closing question wording, and asking
    the record question after the recap. Listed in the PR for Soul.
  - **Soul, 2026-10-25 (product review on #16, not a full sign-off):** P0 direction conditionally
    accepted. One targeted fix: an offered skip was logged as "answered". **Fixed** (the answer is now
    settled before it's logged; covered by a save/resume test).
    1. Keep the conservative scope rule. In P1, ask "Which of those events does that explanation apply
       to?" when the scope is unclear, and add partial-scope and ambiguous-wording cases.
    2. "I don't know" is an explicit unknown answer and closes the question. It stays visible on the fact
       record and in outputs. "Skip" stays an open item.
    3. Free-recall opener: Claude may change only the tests needed to assert the new behavior, keeping
       equivalent protection for provenance, certainty, one question at a time, neutral wording,
       corrections and safety. No deleting tests to get green.
    4. Limits (3 per fact, 2 deferred at recap) are provisional. Assess them on synthetic transcripts
       before tuning. Never drop a source or certainty check without marking the gap.
    5. 0.4 wording: a separate draft may make the recap, record and closing questions more natural. Keep
       the "more certain than intended" check, record-to-fact traceability and corrections. If the record
       question moves after the recap, prove it's asked once and can't strand new additions.
    6. "Huh?" at an opening prompt, recap or final check is a P1 priority. Never store it as a fact or a
       correction.
  - Next: P1 as a new draft PR (and the 0.4 wording change as its own draft), when Michael gives the go-ahead.
- **B. Case-level document memory** (engine + web). Attach uploads and interviews to one case record.
  Start each interview from a short "what's on file" brief the client confirms or corrects, keeping
  where each fact came from (document or client) separate. Voice-kit checkpoints load into the same case.
- **C. Web app phone hardening.** Section 2, items 2–6, using PR #11's screens as the design source.
- **D. Decisions for Michael + Soul (not code):** where the app is hosted and who holds the key,
  privacy/legal review, and whether local mode (PR #3) stays as a separate option.

## 5. Real-client blockers (all still open)

1. Soul's review and merge of the code that will hold the data.
2. A host that fits `docs/DEPLOY.md`: HTTPS, an encrypted persistent disk, the key in a secret manager,
   separate encrypted backups, and one process. Vercel functions as-is do not fit.
3. A data-location decision and a privacy/legal review. Nothing here is covered by attorney-client privilege.
4. 2FA for the web app.
5. A synthetic-data smoke test on the deployed instance, in Chelsea's own browser and phone.
6. Final readiness sign-off (Soul + Michael).

## 6. Feature requests in the issue tracker (not started)

#6 Protective Order Violation Evidence Log · #7 Reclaim Act abusive-litigation pattern log ·
#8 Mediation Safety & Notice Check (AB 2789) · #9 Custody Safety Authority Screen (SB 1364) ·
#10 San Diego D-305 filing preflight. #2 (secure local mode) is implemented in PR #3, pending review.

## 7. Known limitations (unchanged)

- Classifiers are English keyword matching (sources, acknowledgements, danger, advocacy guard): cautious but brittle.
- No semantic contradiction detection between free-text answers.
- Hosted web app: whoever holds the master key and the disk can read all data (server-side encryption,
  not end-to-end); no key rotation tool; no retention or verified-deletion workflow.
- Local mode: export is disabled, so outputs are viewed on screen only.

## History

| Date | Note |
|---|---|
| 2026-10-15 | [PR #12 Rapid Supervision Intake](docs/handoffs/2026-10-15-pr12-rapid-supervision-intake.md) |
| 2026-10-08 | [PR #11 Rapid Incident Intake](docs/handoffs/2026-10-08-pr11-rapid-incident-intake.md) |
| 2026-09-30 | [State after PR #1 merged; #3 vs #5 comparison](docs/handoffs/2026-09-30-state-after-pr1-merge.md) |
| 2026-09-29 | [PR #5 web security layer](docs/handoffs/2026-09-29-pr5-web-security-layer.md) |
| 2026-09-29 | [PR #3 secure local mode](docs/handoffs/2026-09-29-pr3-secure-local-mode.md) |
| 2026-09-28 | [PR #1 interviewer core and audit repairs](docs/handoffs/2026-09-28-pr1-interviewer-core-audit-repairs.md) |

# Handoff — Laylaw Interviewer (current state)

**Refreshed:** 2026-09-29, updated 2026-09-30 (America/Los_Angeles), by Claude, verified against the repo.
This replaces the earlier pre-merge handoff and the pre-repair audit checklist. Both are
history now (see [History](#history)); **nothing in them is an open task.**

## 1. Where we are now

| | Verified value |
|---|---|
| Repo | https://github.com/dragondirty7-create/Laylaw_interviewer |
| `main` | `eaf01c8fbd96ad4232fdcbffad1f9d0b934270d0` (merge of PR #1, 2026-09-28) |
| Tests on `main` | **97 passed**, `python -m pytest -q` (Python 3.11 locally; CI runs 3.10 and 3.12) |
| CI on `main` | Green: https://github.com/dragondirty7-create/Laylaw_interviewer/actions/runs/36471658632 |
| Naming | "Laylaw" only; CI's legacy-name check passes |
| Open work | Two real-client security PRs, both open and **not merged**: PR #3 (local mode on Chelsea's own computer) and PR #5 (hosted web app). Pick one; see section 4 |

## 2. INTERVIEWER CORE STATUS: merged and working (synthetic data)

Each behavior below is covered by passing tests on `main`:

| Behavior | Evidence (tests) |
|---|---|
| Save/resume at the exact pending question | `test_required::test_01_*`, `test_repair_pass::test_save_and_finish_later_resumes_at_the_exact_pending_question`, `test_audit_repairs::test_4_binding_survives_interrupt_and_resume` |
| Provenance: facts only from exact slices of logged answers; paraphrase/generated text refused | `test_audit_repairs::test_1_*`, `test_repair_pass::test_mixed_source_free_narrative_is_separable_by_provenance` |
| Discrepancies preserved neutrally, bound to the right conflict, labeled by field | `test_required::test_04_*`, `test_repair_pass::test_non_date_discrepancies_preserve_both_recollections`, `test_audit_repairs::test_4_*`, `test_7_*` |
| Corrections keep the original, link versions; acks/additions never replace facts | `test_repair_pass::test_recap_correction_*`, `test_final_check_correction_*`, `test_audit_repairs::test_3_*` |
| Source of knowledge: secondhand stays secondhand; unknown stays UNKNOWN until explained | `test_required::test_03_*`, `test_06_*`, `test_audit_repairs::test_2_*` |
| Uncertain/approximate dates and hedges preserved | `test_required::test_02_*`, `test_02b_*`, `test_repair_pass::test_hedge_covers_the_date_of_the_same_statement` |
| Client workspace isolation | `test_required::test_10_two_client_workspaces_cannot_read_or_overwrite_each_other` |
| Multiple uploads stay with the right client and session | `test_required::test_11_*` |
| Family-law and criminal-defense paths (same engine and rules) | `test_extra::test_criminal_defense_path_uses_same_engine_and_rules`, `test_repair_pass::test_criminal_path_starts_with_paperwork_*`, `test_section_selection_*` |
| Immediate-danger preflight pauses safely | `test_audit_repairs::test_6_*`, `test_extra::test_present_danger_pauses_interview_and_returns_to_question` |
| No advocacy in INTERVIEW mode; client's own wording preserved | `test_required::test_09_*`, `test_audit_repairs::test_5_*` |
| Seven canonical outputs | `test_repair_pass::test_organize_interface_is_separate_and_interview_keeps_seven_outputs` |

The criminal-defense Build Notes alignment was resolved before the audit (commit `28a3c1c`). Don't redo it.

## 3. What changed from the old audit (all resolved, none regressed)

Soul's audit at `fdd7d449` listed seven items. All were repaired before PR #1 merged, each with
regression tests that fail on the audited code. All **57** of those tests pass on current `main`
(`python -m pytest -q tests/test_audit_repairs.py`).

| # | Historical item | Status on `main` | Repair commit | Tests |
|---|---|---|---|---|
| 1 | Acknowledgements/additions entering the correction flow | **Resolved** | `1103ad1` | `test_3_*` (20 cases) |
| 2 | A clarification resolving the wrong discrepancy | **Resolved** | `352ec58` | `test_4_*` (5 cases) |
| 3 | Attributed client wording tripping the advocacy guard | **Resolved** | `00aca9c` | `test_5_*` (2 cases) |
| 4 | Recording APIs bypassing provenance | **Resolved** | `52de607` | `test_1_*` (4 cases) |
| 5 | Unknown knowledge source becoming firsthand | **Resolved** | `63ec0d1` | `test_2_*` (10 cases) |
| 6 | Plain "Yes" to the danger question not pausing | **Resolved** (+ skip follow-up `10aad5c`) | `127a465` | `test_6_*` (11 cases) |
| 7 | Non-date discrepancies labeled as date conflicts | **Resolved** | `ae5d5b5` | `test_7_*` (5 cases) |

(The numbering above follows the audit's order. The test names and repair commits use the repair pass's own numbering, so the table maps each item to its repair.)

## 4. REAL-CLIENT DEPLOYMENT STATUS: blocked

**The interviewer core is merged and working on synthetic data. Real-client use is still blocked.**
On `main` today there is no encryption at rest, no authentication, no audit log and no deletion
workflow; storage is plaintext JSON for synthetic data only (see `SECURITY.md`).

Two open PRs each implement the missing security layer. **Neither counts until Soul reviews it and
it is merged.** They solve the same problem two ways, so one should be chosen before more work:

| | PR #3 `feat/secure-local-mode` | PR #5 `feat/real-client-security` |
|---|---|---|
| Where it runs | Chelsea's own computer, 127.0.0.1 only | A hosted HTTPS server |
| Protection | Encrypted vault (scrypt + OS keyring, AES-256-GCM), recovery codes, HMAC-chained audit log, deletion | Accounts + server sessions, lockout, per-client AES-256-GCM, private uploads, content-free logs |
| Tests / CI | 133 passing, green | 126 passing (+125/1 skipped on encrypted store), green on 3.10/3.12 |
| Still needed | Soul review; setup and dry run on her machine | Soul review; a host with an encrypted disk and secret manager (Vercel functions don't fit, `docs/DEPLOY.md`); data-location decision; second factor recommended; key rotation and retention workflow |
| Fits | One client, one computer | Several clients, any device |

**Recommendation:** for Chelsea alone, PR #3 is the shorter safe route: no server, no third-party
host holding case data, and she alone holds the passphrase. PR #5 is the route if Laylaw needs
more than one client or phone access. Decision: Michael + Soul.

## 5. Chelsea use path (smallest route to safe real use, via PR #3)

- [ ] **Choose the track** (section 4). If PR #5 instead, swap the setup steps below for
      `docs/DEPLOY.md` on that branch, plus a smoke test in her own browser and phone.
- [ ] **Security review.** Soul reviews PR #3. Fix findings; merge only on approval. Rebase it on
      `main` after this docs PR lands (both touch `HANDOFF.md`).
- [ ] **Engine usability fix (small).** "No, that's all." is recorded as content, so follow-ups repeat
      and the interview doesn't end (found while testing PR #3). One change to `_NOTHING_MORE` plus a
      regression test; Soul decides whether it rides with PR #3.
- [ ] **Her computer.** Her own OS account with a password, full-disk encryption (BitLocker/FileVault),
      auto screen lock; Python + `pip install ".[secure]"`; **Chelsea** runs `python -m laylaw init`
      (only she knows the passphrase), recovery code on paper; `python -m laylaw doctor` reports
      "Ready for real case data".
- [ ] **Synthetic-client dry run on that computer.** A full interview with a made-up client: launch,
      unlock, answer, save and exit, lock, resume, upload, finish, outputs, delete
      (`docs/LOCAL_MODE.md` in PR #3).
- [ ] **Isolation check on that computer.** Another OS account can't open the vault; a copied vault
      plus the passphrase won't open elsewhere; the app isn't reachable from another device;
      `verify-audit` passes and the log holds no case content.
- [ ] **Privacy/legal review.** Confidentiality and privilege expectations; the app states nothing
      is privileged.
- [ ] **Final readiness sign-off** (Soul + Michael) with the evidence above. Only then real case
      information.

## 6. Next recommended step

Merge this docs PR, pick the track, then Soul reviews that PR. The LLM conversation layer and
question-volume prioritization stay deferred.

## Known limitations (unchanged, not blockers for synthetic use)
- Classifiers are English keyword matching (sources, acknowledgements, danger, advocacy guard); cautious but brittle.
- Attribution is caller-declared (`log_answer` / `record_statement`); authentication must come from the app layer.
- Firsthand detection is conservative: some firsthand accounts stay UNKNOWN until "How do you know that?" is answered.
- No semantic contradiction detection between free-text answers; question volume can be high.

## History
- 2026-09-28: PR #1 opened (pass 1), repair pass, Build Notes alignment, Soul's audit at `fdd7d449`
  (seven items), audit repair pass, skip follow-up, Soul approval, merged as `eaf01c8`. The full
  pre-merge handoff text is in git history:
  https://github.com/dragondirty7-create/Laylaw_interviewer/blob/eaf01c8fbd96ad4232fdcbffad1f9d0b934270d0/HANDOFF.md
- 2026-09-29: Issue #2 implemented in PR #3 (open, awaiting review).

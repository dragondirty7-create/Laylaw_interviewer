# Handoff — Rapid Criminal & Supervision Intake (draft, stacked on PR #11)

**Date:** 2026-10-15 (America/Los_Angeles) · **From:** Claude → Soul / Michael
**Answers:** "NEEDS CLAUDE CODE — APPROVED IMPLEMENTATION HANDOFF — 2026-10-15 PDT" and its addenda in the Laylaw Build Notes.
**ACK LAYLAW RAPID SUPERVISION INTAKE 2026-10-15.** Synthetic data only. **Not merged, not deployed, no real-client use.**

## Base and dependency
- Branch `feat/rapid-supervision-intake`, based on PR #11 head `84cf0fc` (which stacks on PR #3). Needs #3 and #11 reviewed first; it reuses #11's intake engine, local app and #3's encrypted vault. No second vault.

## What changed
- **Engine:** the intake now has a `flow` (`housing` default, so #11 behaves exactly as before and old saves load); a `multi` (choose-all-that-apply) question kind; a per-step `default` choice.
- **New flow `supervision`** (`laylaw/intake/supervision_steps.py`): safety and adult check first; matter type defaults to *Not sure* (a skip is also treated as not sure); next required date with exact / approximate / unknown precision and who said it; who said treatment is required, how it was given (signed order / written condition / referral / verbal / proposal / not sure), the paper's exact words kept apart from what the person remembers, and whether it says residential or only treatment. Then, only where relevant: charges copied from paperwork (no account of conduct), supervision kind(s), assessment existence, nonresidential options discussed vs approved, feasibility factors, hold/warrant/hearing status. Under-18 stops the intake.
- **Outputs** (`supervision_outputs.py`): Rapid Situation Summary, Time-Sensitive Dates, Requirement Source Map, Nonresidential Options Comparison, Evidence & Orders Inventory, Chronology, Open Questions, reviewer topics (questions only). Every value is tagged CLIENT REPORTED / DOCUMENT STATES (as typed in) / OFFICIALLY VERIFIED / CONFLICT / UNKNOWN; Laylaw never sets OFFICIALLY VERIFIED. Conflicts are kept, never resolved. Laylaw's own wording passes the advocacy guard plus a conclusion-word list (eligible, exempt, waiver, violation, should, must…) or nothing renders.
- **App:** a second start card on the home page; checkboxes for multi questions; supervision review page with basis labels.

## Tests
- `python -m pytest -q`: **184 passed** (154 existing unchanged + 30 new in `tests/test_supervision_intake.py`, named by acceptance letter A–H).
- Mutation checks: upgrading "treatment" to "residential", dropping the Not-sure default, or tagging typed-in wording as officially verified each turn tests red.
- Rendered QA: `scripts/visual_qa_supervision.py` in Chromium 1194 at 390×844 and 1280×900, whole flow incl. upload: no horizontal scroll, no console errors, all packet sections present. Screenshots in `docs/screenshots/supervision/`.
- Naming check clean.

## Not done / blockers
- No legal-rule or eligibility engine (by design until Gemini's authority matrix is independently checked).
- Classifiers are not involved; conflict detection is keyword-based on residential wording only.
- Real-data gate unchanged: PR #3 security review and Michael's approval still required.

## Next
1. Soul reviews #3 → #11 → this draft PR, in that order.
2. Gemini research lands → decide whether any sourced, versioned rules layer is added (outside this intake).

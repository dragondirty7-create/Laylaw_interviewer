# Brief B: case-level document memory and a "what's on file" check

**For:** Claude Code · **Written:** 2026-10-23 by Claude · **PR base:** brief A's branch once Soul has reviewed it

## Why

Michael, 2026-10-23: in the last interview, Laylaw "had no memory of Chelsea's filed documents".
This is how the system was built, not a one-off:

- Uploads are stored per **interview** (`uploads/<interview id>/<record id>.enc` in
  `laylaw/web/secure_store.py`, and the same idea in `laylaw/secure/store.py`). A new interview on the
  same case starts with none of the earlier files.
- Nothing reads what a document says. The engine keeps and fingerprints files. `propose_document_candidate()`
  lets **a person** record a detail ("the order dated X says Y"), but those details live inside one
  interview, and `respond_to_candidate()` only creates a fact when the candidate is already tied to one.
- The voice kit (`docs/VOICE_INTERVIEW_KIT.md`) starts every session from a blank chat and gives it no summary of what's on file.

## Read first

`HANDOFF.md`, `SECURITY.md` (both web and local sections, especially isolation and "no route takes a
client id from the request"), `laylaw/interviewer/session.py` (records, `add_upload`,
`propose_document_candidate`, `respond_to_candidate`, `add_document_finding`, `summary_review`),
`laylaw/interviewer/workspace.py`, `laylaw/web/secure_store.py`, `laylaw/web/app.py`,
`laylaw/secure/store.py`, `laylaw/organize/interface.py`, and Soul's PR #5 review (2026-10-21) for
the rule that the engine is the only writer of the factual record.

## Build

1. **A case file inside each client workspace.** Add a `CaseFile` record: case id, case documents
   (`SupportingRecord`s), and case-level document details (`DocumentCandidate`s with `fact_id=None`).
   Store it encrypted the same way sessions are, in all three stores (plain, local vault, web). Keep
   every isolation guarantee: no client or case id from the request, the same 404 for "not yours" and
   "doesn't exist", and ciphertext bound to client, kind and id.
2. **Uploads belong to the case.** A file uploaded in any interview is stored at case level and linked
   to the interview it arrived in. Existing per-interview uploads load unchanged (migration on read, with a test).
3. **"What's on file" check at the start.** When an interview starts on a case that has documents or
   earlier interviews, the first section after orientation is **Confirm what's on file**:
   - For each recorded case detail, ask once: *"[Document label] shows [field] as '[value]'. Does that
     match what you know?"* This reuses the existing document-check wording.
   - Confirm or correct creates a new fact **in the client's own words**, with provenance showing both
     the document and the client. Allow a candidate with no `fact_id` to do this. "Not sure" and "skip"
     work as usual.
   - Facts already confirmed in an earlier interview on the same case are shown in a recap
     (*"From your last interview: …"*) for a yes/no/correct, not asked again from scratch.
   - Later sections skip follow-ups the case file already answers (for example, the date of a filed order).
4. **Entering document details.** For now a person enters them: an operator or reviewer action in the
   web app and an engine method. **Do not add automatic reading of real documents (OCR or an AI model).**
   That changes where client data goes and is a decision for Soul and Michael. Leave a clean interface
   (`DocumentReader` protocol) and a note in `HANDOFF.md`.
5. **Voice kit bridge.** A function and admin command that print a plain-text "What's on file" block
   for a case, to paste into the voice kit's opening. A matching section goes in `docs/VOICE_INTERVIEW_KIT.md`.
   A voice checkpoint can be loaded back into the same case through `log_answer`, so provenance holds.
   Document the steps; no automatic import.
6. **Outputs.** The Fact Table and Handoff Summary keep "what the client said", "what documents show"
   and "what's unknown" separate. Add the case documents to the ORGANIZE export (`document_index` input).

## Done when

- Synthetic case, two interviews. Files and details added in interview 1 are visible in interview 2.
  Interview 2 opens with the "what's on file" check and never re-asks a confirmed detail from scratch.
- A corrected document detail keeps both the document's version and the client's, linked; nothing is overwritten.
- Two-client isolation tests from PR #5 pass, plus new ones: client B can't see or guess client A's
  case documents; a case document copied into another workspace fails to decrypt.
- Old saved sessions with per-interview uploads still load (fixture test).
- Full suite and encrypted-store suite pass; existing tests unchanged, or any change explained for Soul.

## Deliver

- Branch `feat/case-document-memory`, **draft** PR. PR body: design, migration, isolation tests, open decisions (automatic reading).
- Update `HANDOFF.md` sections 3–5 and "Last updated".
- Synthetic data only. No merge, no deploy. No real documents, ever, in tests or screenshots.

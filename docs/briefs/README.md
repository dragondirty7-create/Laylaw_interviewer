# Claude Code briefs

Ready-to-run briefs for the next Laylaw steps. Each one is a single PR.

**How to use one:** open a Claude Code session on this repo and say:

> Read `docs/briefs/<file>` and do it.

The brief has everything the session needs. Run them in order. Soul reviews each PR before the next
one starts, because B builds on A, and C touches the same web screens B does.

| Brief | What | Size | Depends on |
|---|---|---|---|
| [A-lighter-questions.md](A-lighter-questions.md) | Fix the "No, that's all." loop; ask only the follow-ups that matter | Small–medium | PR #14 |
| [A2-P1-and-recap-wording.md](A2-P1-and-recap-wording.md) | Follow-up v2 P1 (free-recall opener, "Huh?" everywhere, fatigue, patterns), then the recap wording, as two drafts | Medium | PR #16 |
| [B-case-document-memory.md](B-case-document-memory.md) | Uploads and interviews share one case; start from a "what's on file" check | Medium–large | A |
| [C-web-phone-hardening.md](C-web-phone-hardening.md) | Soul's 2026-10-21 phone and durability list for the web app, including 2FA | Large | A (B helps) |

Rules for every brief (they repeat inside each one):

- Synthetic, fictional data only. Never put real case facts, names, filings or screenshots in code,
  tests, commits, PRs or logs.
- Open a **draft** PR. Never merge, deploy or promote. Soul reviews; Michael approves.
- Update `HANDOFF.md` (the status page) in the same PR.
- The Interviewer engine stays the only writer of the factual record.

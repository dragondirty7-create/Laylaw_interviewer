# Research Basis — Laylaw Interviewer

Sources that inform the interviewing methodology. This file is a record, not
configuration. The interview engine never reads it, so interview behavior
changes only when a person reviews an entry and makes a code change.

Rules (from the canonical spec):
- Give greater weight to peer-reviewed research, official courts, government sources, established professional interviewing guidance, recognized forensic interviewing research, and current jurisdiction-specific procedural authority.
- Do not change core interview behavior based on a single blog post or advocacy source.
- When research conflicts, preserve the disagreement and flag it for review.
- Do not change interviewing behavior based on unreviewed research.

Machine-readable entries can be kept with `laylaw.interviewer.research_basis.ResearchBasis`
(`save` / `load` as JSON). `mark_applied` refuses unreviewed or low-weight sources.

## Template (copy per source)

| Field | Value |
|---|---|
| TITLE | |
| AUTHOR / ORGANIZATION | |
| DATE | |
| LINK / SOURCE | |
| TYPE OF SOURCE | peer-reviewed research / official court / government source / professional interviewing guidance / forensic interviewing research / jurisdiction-specific procedural authority / blog / opinion / advocacy source / other |
| KEY FINDING | |
| HOW IT AFFECTS THE INTERVIEW PROTOCOL | |
| DATE REVIEWED | NOT YET REVIEWED |

## Entries

_None yet._ No research entries were added in this implementation pass. Adding
sources is a separate, reviewed task.

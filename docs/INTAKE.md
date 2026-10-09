# Rapid Incident Intake (MVP)

A small, private intake for writing down one urgent incident while it's fresh. It runs
inside the local app (PR #3): open Laylaw, then **Start an incident intake** on the home page.
Practise with made-up information only until Soul's review passes.

## How it works

- **One question at a time, two stages.** The essentials come first: danger, what happened,
  the day, who came in, notice, permission, and any files you already have. Then Laylaw asks
  whether to add more detail now or later. Every question can be answered "I'm not sure" or skipped.
- **Safety first.** If someone is in danger or still getting in, a neutral note says who can be
  contacted (911, the non-emergency line, a licensed lawyer). Laylaw doesn't decide for anyone.
- **Child details kept to a minimum.** Questions about a child appear only if a child was there:
  age range, a few words on what they were doing, and their own words *only* if they said
  something on their own. Each says why it's asked. The child's words are recorded once,
  exactly as written, and can't be replaced afterwards.
- **Files kept exactly as received.** Each file is stored encrypted with a SHA-256 fingerprint
  taken at upload. Notes, source and date are stored beside the file, never inside it. The
  packet page re-checks every fingerprint.
- **Neutral chronology.** Built from what was entered. Each row says what it rests on: *You said*,
  *File details (as entered)*, *Placed by Laylaw*, *Not known*, or *Two things differ* (both kept).
- **Referral packet.** Facts as given, chronology, evidence index, open questions, and a short list
  of topics for a licensed lawyer to evaluate. No conclusions, no damages, no criminal labels, no
  advice. Laylaw's own wording is checked against the Interviewer's advocacy guard and a list of
  conclusion words; if it ever fails, no packet is shown.
- **Separate matters.** Each intake is its own workspace (`matter-…`) and shares nothing with any
  interview or other intake. Deleting one removes its record and files only.

## Code

- `laylaw/intake/steps.py`: the questions, in order, with stages, conditions and "why we ask".
- `laylaw/intake/model.py`: answers, corrections (earlier answers kept), the child's words, evidence.
- `laylaw/intake/chronology.py`: chronology, conflicts, open questions, evidence inventory.
- `laylaw/intake/packet.py`: the referral packet and its neutrality checks.
- `laylaw/intake/service.py`: storage in the encrypted vault.
- `laylaw/app/intake_pages.py` and `/n/...` routes in `laylaw/app/server.py`: the screens.

## Not done (needs a decision)

- **Export.** The packet is shown on screen only, because PR #3 turns export off for encrypted
  data. A secure export (for example a password-protected file) is a decision for Soul.
- No real-data use until PR #3 and this PR are reviewed and merged.

Screenshots (phone width, synthetic data): `docs/screenshots/intake/`.

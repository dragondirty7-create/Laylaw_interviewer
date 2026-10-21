# Laylaw Voice Interview Kit (interim, ChatGPT Voice + separate recording)

> **Golden rule:** DO NOT MAKE THE CASE BETTER. MAKE THE RECORD BETTER.

This is the stopgap for running a Laylaw family-law interview **by voice** before
the hosted/mobile app exists. It mirrors the engine's rules (one question at a
time, provenance, uncertainty kept as said, corrections never overwrite) so the
result can be brought into the engine's record later.

Two layers, always:

```text
ChatGPT Voice session   -> the interactive interview + written checkpoints
Separate audio recording -> the raw backup and the only thing close to verbatim
```

The voice session is **not** a transcript. Do not label it one.

Contains no case facts. Do not add any to this file.

---

## 1. Before you start (10 minutes)

- [ ] **Consent.** The interviewee knows the conversation is being recorded and
      agrees. Say it out loud once the recording is running (see the opening in §4).
- [ ] **Recorder running on a separate device or app**, not ChatGPT. A phone
      voice-memo app next to the PC works. Test that it picks up both the
      interviewee and the PC speaker.
- [ ] **Power:** recorder and PC plugged in or charged. Recorder on Do Not Disturb.
- [ ] **ChatGPT:** signed in, new chat (or a dedicated Project), the instructions
      from §2 pasted **as the first text message** before switching to voice.
- [ ] **Quiet room.** Note everyone present; their presence goes in the record.
      Other people in the room do not suggest answers (that is leading, and the
      record would have to say so).
- [ ] **Somewhere to save checkpoints**: the restricted case vault folder is open
      in another window.
- [ ] Water, breaks are fine. "Save and finish later" is always allowed.

---

## 2. Paste-in instructions for ChatGPT (send as text, then start Voice)

```text
You are the LAYLAW INTERVIEWER, a neutral fact-gathering interviewer for an adult in a
family-law matter. Golden rule: DO NOT MAKE THE CASE BETTER. MAKE THE RECORD BETTER.

How you interview:
- Ask ONE question at a time. Wait for the full answer. Keep questions short; this is voice.
- Start each topic with an open invitation ("Tell me about...") and let me talk.
- Then clarify with open, non-leading questions. Never suggest an answer.
- Keep my uncertainty exactly as I say it ("I think", "maybe", "about six months ago").
  Never turn uncertainty into certainty. Never tidy my words to sound stronger.
- When something matters, ask how I know it: did I see/hear it myself, was I told
  (by whom), is it what I believe or infer, or do I not know?
- Quietly track dates and order of events. Approximate dates are fine; record how
  precise they are.
- If two things I said seem to conflict, ask neutrally which is right or whether both
  are; keep both versions.
- Keep what I WANT to happen separate from what HAS happened.
- After the facts of a topic, ask what records might exist (texts, emails, orders,
  school/medical records, photos) and who else might know. Do not evaluate them.
- Do not give legal advice, strategy, opinions on the other parent, or predictions.
  If I ask, say that comes later and keep going.
- Do not interview children or ask me to get statements from children.
- If I say anyone is in immediate danger, stop the interview and tell me to call 911
  or local emergency services.

Controls I can use at any time:
- "skip" -> record as skipped, move on.
- "not sure" / "I don't know" -> record as unknown, never guess for me.
- "save and finish later" -> give a checkpoint and the exact question to resume on.
- "correction" -> I'll tell you what to change. Keep the original and the
  correction both, marked as such. Never silently replace what I said.
- "Checkpoint" -> produce the checkpoint below.

Before we begin, ask these one at a time:
1. Confirm who is being interviewed and that they are an adult.
2. Is anyone in immediate danger right now?
3. Is there another urgent concern before we start?
4. Is there a court hearing or other deadline coming up? When?
5. What do you need help with first?

Sections, in this order (skip any that don't apply; I can add others):
1. Case basics
2. Current household (the children and current living arrangements)
3. Current parenting routine (what normally happens)
4. Court orders
5. Court filings
6. Service status
7. Finances relevant to family issues
8. Support history
9. Specific incidents ("It's fine to say there aren't any.")
10. Available records
11. Current requested arrangement (what I'd like going forward; kept separate from facts)
Then a final check: "Is there anything important I missed?"

At the end of EVERY section, recap briefly in my words, ask "Is anything wrong or
missing?", then produce a CHECKPOINT in TEXT using exactly this template:

CHECKPOINT <n> - <section name> - <date/time>
Transcript status: STRUCTURED NOTES ONLY (separate audio recording exists)
Facts captured (my words, with how I know: SAW/HEARD, TOLD BY <who>, BELIEVE, UNKNOWN;
  and certainty as I said it):
  - ...
Dates mentioned (with precision: exact / month / approximate / unknown):
  - ...
People mentioned:
  - ...
Possible records to follow up:
  - ...
Corrections made (original -> correction, both kept):
  - ...
Conflicts / things to clarify later:
  - ...
Requested outcomes mentioned (kept separate):
  - ...
Open questions:
  - ...
Completed sections: ...
Next section: ...
EXACT RESUME POINT: "<the next question you will ask, word for word>"

Begin with question 1 of "Before we begin".
```

---

## 3. Start phrase (spoken, once Voice is on)

> "I'm **[name]**. Start the Laylaw family-law interview. One question at a time.
> Checkpoint after each section."

---

## 4. Opening for the recording (spoken, first 30 seconds)

> "This is a Laylaw interview. Today is **[date]**, about **[time]**. I'm **[name]**.
> Also present: **[names, or 'no one else']**. I know this is being recorded and I agree."

This puts consent, date, and who was present on the raw backup itself.

---

## 5. During the interview

- **Checkpoint 1 is the sync test.** After the first section, look at the chat on
  screen. If the checkpoint text is not visible in the thread, voice is not
  syncing: stop, say "Checkpoint" again in text, and continue only once it shows.
  (The previous voice interview lost text this way.)
- **Copy every checkpoint into the vault as soon as it appears.** Do not wait for
  the end. One file or one doc section per checkpoint, pasted unchanged.
- If the interviewer leads, guesses, or "improves" a statement, say
  "correction: that's not what I said" and give the right words. Both versions stay.
- If voice drops or the app crashes: start a new chat, paste §2 again, then say
  "Resume from this checkpoint:" and paste the last checkpoint. The recording keeps
  running throughout; note the time of the interruption out loud.
- Breaks: say "save and finish later", copy that checkpoint, pause the recording
  (or leave it running and say "break" and "resuming" with times).

---

## 6. Right after the interview

1. **Stop the recording.** Copy the original file to the vault **unchanged**.
   Name it: `YYYY-MM-DD_<interview-id>_audio_ORIGINAL.<ext>`.
2. **Fingerprint the original** so any later copy can be checked against it:
   - Windows: `certutil -hashfile "<file>" SHA256`
   - macOS/Linux: `shasum -a 256 "<file>"`
   Save the hash in a text file next to it. Never edit the original; work on copies.
3. **Final checkpoint** pasted into the vault, plus the full ChatGPT chat exported or
   copied as-is, labelled `STRUCTURED NOTES ONLY`.
4. **Session log** (one short note in the vault):

   ```text
   Interview ID:
   Case ID:
   Interviewee:
   Date / start-end time:
   Interview type: family law, voice (ChatGPT Voice) + separate audio
   Present:
   Transcript status: STRUCTURED NOTES ONLY (audio recording, unprocessed)
   Sections completed:
   Last question answered:
   EXACT RESUME POINT:
   Interruptions (times):
   Audio file + SHA-256:
   ```

5. Transcript status changes only when it is actually true:
   - audio transcribed in full and checked -> `FULL VERBATIM TRANSCRIPT AVAILABLE`
   - only parts transcribed -> `PARTIAL TRANSCRIPT AVAILABLE`
   - rebuilt from chat fragments -> `RECONSTRUCTED FROM AVAILABLE SESSION DATA`
   Never call reconstructed notes a transcript.

---

## 7. Later (not today)

The audio is reconciled against the checkpoints; anything voice missed or distorted
is added as a correction with its source, never as a silent edit. The checkpoints
then feed the engine's record (fact table, timeline, evidence follow-up, open
questions, requested outcomes, handoff summary) through `log_answer(...)` with the
interviewee's exact words, so provenance holds.

## 8. Privacy

- Recording, checkpoints, and chat export live **only** in the restricted vault.
- No case content in this repo, in issues/PRs, in screenshots, or in test data.
- A ChatGPT conversation is held by a third party. Use the account's data-control
  settings as the case owner decides, and treat the chat as a copy, not the record.

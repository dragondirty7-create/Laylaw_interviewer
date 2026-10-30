# Laylaw interview day: one-page runbook (2026-10-30)

> Golden rule: make the record better, not the case better.

**Method today:** ChatGPT Voice runs the interview, a separate recorder keeps the raw audio, and checkpoints go into the private vault folder.
**Not today:** the Laylaw app is not cleared for real client information. Don't type Chelsea's facts into it.
Full detail: `docs/VOICE_INTERVIEW_KIT.md` on branch `integrate/one-laylaw`.
This page has no case facts. Don't add any.

## 10 minutes before
1. **Recorder**: use a phone voice-memo app, not ChatGPT. Do Not Disturb on, phone plugged in. Do a 10-second test that picks up both Chelsea and the PC speaker.
2. **Vault folder**: open the private folder where the checkpoints will go. It must not be a shared or synced team folder.
3. **ChatGPT**: open a new chat. Paste the instructions block from §2 of the voice kit as the **first text message**. Send these lines as a second text message (the kit doesn't cover them yet), then switch to Voice:
   ```text
   Also:
   - Be warm and patient. Short questions. Silence and pauses are fine; don't rush me.
   - "go back" -> return to the earlier topic I name; keep everything already recorded.
   - "that's all" / "no, that's all" / "nothing else" -> that topic is finished. Never ask it again.
   - Never re-ask something I've already answered. If you need more, say what you already have first.
   - If I use or you use a legal term, explain it in one plain-English sentence. No advice, no predictions.
   - If I'm upset, acknowledge it briefly and offer a break. Don't push.
   ```
4. **Room**: quiet, water within reach. Note who is present. Nobody else suggests answers.
5. **Breaks are always fine.** "Save and finish later" works any time.

## Start
- Start the recorder, then say: *"This is a Laylaw interview. Today is October 30, about [time]. I'm [name]. Also present: [names]. I know this is being recorded and I agree."*
- In Voice, say: *"Start the Laylaw family-law interview. One question at a time. Checkpoint after each section."*

## During
- **After section 1, look at the screen.** If the CHECKPOINT text isn't there, voice isn't syncing. Type "Checkpoint" and wait until it appears before going on.
- **Copy every checkpoint into the vault as soon as it appears.** One file per checkpoint, pasted unchanged.
- Chelsea can say any of these at any time: **"skip"**, **"I don't know"**, **"correction: …"**, **"go back to …"**, **"that's all"**, **"save and finish later"**.
- If the interviewer leads, guesses or "improves" an answer, say: *"Correction: that's not what I said."* Both versions stay in the record.
- If the same question comes back after "that's all", say: *"We already covered that. Next section."*
- Legal words: ask *"What does that mean in plain English?"* The interviewer explains and doesn't advise.

## If something fails
| Problem | Do this |
|---|---|
| Voice drops or the app crashes | **Keep the recorder running** and say the time out loud. Open a new chat, paste §2 again, say "Resume from this checkpoint:" and paste the last one. |
| Checkpoint text is missing | Type "Checkpoint". If it still doesn't show, the audio is the record. Write the time down and keep going. |
| ChatGPT is unavailable | Michael asks the questions himself from the section list in §2 of the kit, one at a time. The recorder is the record. |
| Recorder stops | Restart it right away and say the time and "recording resumed". |
| Anyone is in immediate danger | Stop the interview and call 911. |

## Right after
1. Stop the recorder. Copy the original file to the vault **unchanged**, named `2026-10-30_<interview-id>_audio_ORIGINAL.<ext>`.
2. Fingerprint it with `certutil -hashfile "<file>" SHA256` and save the hash in a text file next to it.
3. Paste the final checkpoint and the full chat into the vault, labelled **STRUCTURED NOTES ONLY**. It isn't a transcript.
4. Fill in the session log from §6 of the kit, including the exact resume point.
5. Don't put anything from the interview in GitHub, issues, PRs, screenshots or shared agent notes.

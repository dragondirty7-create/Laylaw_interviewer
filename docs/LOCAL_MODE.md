# Running Laylaw on one computer (hardened single-user local mode)

This is the reproducible setup and use walkthrough for Issue #2. Until Soul's
security review passes, practice with **made-up** information only.

## One-time setup (about 10 minutes)

Do this on the computer and OS account Chelsea will use. That account should
have a sign-in password, full-disk encryption (BitLocker on Windows, FileVault
on Mac) and automatic screen lock.

1. Install Python 3.10 or newer from python.org (Windows: tick "Add python.exe to PATH").
2. Get the code and install it with the secure extra:
   ```
   git clone https://github.com/dragondirty7-create/Laylaw_interviewer
   cd Laylaw_interviewer
   py -m pip install ".[secure]"        # Windows
   python3 -m pip install ".[secure]"   # Mac
   ```
3. **Chelsea** creates the vault, so only she knows the passphrase:
   ```
   py -m laylaw init          # Windows  (python3 -m laylaw init on Mac)
   ```
   * Choose a passphrase of 12+ characters. A short sentence works well.
   * Write the **recovery code** on paper and put it somewhere safe, away from
     the computer. Type its last group back when asked.
   * For a practice vault with fake data only, use `init --synthetic --vault <folder>`.
4. Check everything is in place:
   ```
   py -m laylaw doctor
   ```
   It should end with "Ready for real case data." If it lists a PROBLEM,
   Laylaw will refuse to open until it's fixed.

The vault lives in the per-user app data folder (Windows:
`%LOCALAPPDATA%\Laylaw\vault`; Mac: `~/Library/Application Support/Laylaw/vault`).

## Everyday use

1. Double-click **`scripts/Start Laylaw (Windows).bat`** (or
   **`Start Laylaw (Mac).command`**), or run `py -m laylaw run`. The browser opens
   Laylaw at `http://127.0.0.1:…`. It isn't reachable from any other computer.
2. Enter the passphrase and click **Unlock**.
3. **Start a new interview**: a workspace label for the client (for example
   `client-a`), a case reference, the interviewee's name, the interview type
   (family law or criminal defense), and confirm the interviewee is an adult.
4. Answer one question at a time. Each question has **Answer**, **Skip**,
   **Not sure**, and **Save and finish later**. If an answer suggests someone
   is in danger, ordinary questions pause until the safety check is answered.
5. **Save and finish later** saves and returns home. Next time, open the
   interview from the list, click **Continue**, and it picks up at the same
   question.
6. **Documents**: add files from the interview page; they're stored encrypted.
7. When the interview is complete, click **View the interview outputs**
   (Handoff summary, Fact table, Timeline, Evidence follow-up, Open questions,
   Requested outcomes, Interview record). They're on screen only; export is off.
   Printing or saving the page makes an unencrypted copy.
8. **Lock** hides everything until the passphrase is entered again. **Lock and
   close** stops Laylaw. It also locks itself after 15 idle minutes.

To delete an interview: open it, choose **Delete this interview**, type DELETE.
To delete a whole client workspace: `py -m laylaw delete-workspace --client client-a`.

## When something goes wrong

| Situation | What to do |
|---|---|
| Forgot the passphrase, or new/reinstalled computer | `py -m laylaw recover` with the recovery code, then choose a new passphrase |
| Want a new passphrase | `py -m laylaw change-passphrase` |
| Laylaw refuses to start and lists problems | Run `py -m laylaw doctor`; fix what it lists. Don't work around it. |
| "The audit log failed verification" | Stop and tell Michael. After review: `py -m laylaw audit-archive` |
| "An encrypted file failed its integrity check" | Stop and tell Michael. Nothing was changed. |

## Developer checks

```
python -m pip install ".[test]"
python -m pytest -q
```
`tests/test_local_app.py` runs this whole walkthrough over HTTP against a
synthetic vault: launch, unlock, new interview, questions, save and exit,
lock, unlock, resume, upload, skip/not sure, finish, outputs, delete.

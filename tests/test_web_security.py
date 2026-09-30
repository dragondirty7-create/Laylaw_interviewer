"""Security and isolation tests for the Laylaw web layer.

ALL DATA IS SYNTHETIC AND FICTIONAL. Two invented clients:
  A: username "alex.fictional",  display name "Alex Fictional"
  B: username "blair.fictional", display name "Blair Fictional"
No real person's name, case facts, messages or documents appear here.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from io import BytesIO
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("cryptography")

from laylaw.web import accounts as acc_mod                          # noqa: E402
from laylaw.web.accounts import Accounts, PasswordPolicyError       # noqa: E402
from laylaw.web.app import create_app                               # noqa: E402
from laylaw.web.crypto import KeyError_, generate_master_key         # noqa: E402
from laylaw.web.secure_store import EncryptedStore, new_client_id    # noqa: E402
from laylaw.interviewer import WorkspaceIsolationError               # noqa: E402

BASE = "https://laylaw.test"
PW_A = "alex-fictional-passphrase-1"
PW_B = "blair-fictional-passphrase-2"
SENTINEL = "ZEBRA-SENTINEL-7731"          # appears only in synthetic answers / files / drafts


class Clock:
    def __init__(self):
        self.t = 1_900_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    monkeypatch.setattr(acc_mod, "SCRYPT_N", 2 ** 12)   # keep the suite fast; production uses 2**15


@pytest.fixture
def env(tmp_path):
    key = generate_master_key()
    clock = Clock()
    app = create_app({"DATA_DIR": str(tmp_path / "data"), "MASTER_KEY": key, "CLOCK": clock})
    ext = app.extensions["laylaw"]
    ids = {}
    for user, pw, name in (("alex.fictional", PW_A, "Alex Fictional"),
                           ("blair.fictional", PW_B, "Blair Fictional")):
        cid = new_client_id()
        ext["accounts"].create_user(user, pw, cid)
        ext["store"].workspace(cid).save_profile({"display_name": name, "case_id": "CASE-FICTIONAL"})
        ids[user] = cid
    return {"app": app, "store": ext["store"], "accounts": ext["accounts"], "clock": clock, "ids": ids,
            "data": tmp_path / "data", "key": key}


def browser(env):
    return env["app"].test_client(use_cookies=True)


def _field(html: str, name: str) -> str:
    m = re.search(rf'name="{name}" value="([^"]*)"', html)
    assert m, f"no {name} field"
    return m.group(1)


def login(c, username, password):
    r = c.get("/login", base_url=BASE)
    pre = _field(r.get_data(as_text=True), "pre")
    return c.post("/login", data={"username": username, "password": password, "pre": pre}, base_url=BASE)


def page(c, path):
    return c.get(path, base_url=BASE)


def csrf_of(c):
    return _field(page(c, "/home").get_data(as_text=True), "csrf_token")


def start(c, path="family_law"):
    r = c.post("/interviews", data={"csrf_token": csrf_of(c), "path": path, "adult": "yes"}, base_url=BASE)
    assert r.status_code == 302
    return r.headers["Location"].rstrip("/").split("/")[-1]


def form_of(c, iid):
    html = page(c, f"/interviews/{iid}").get_data(as_text=True)
    return html, {"csrf_token": _field(html, "csrf_token"), "qtoken": _field(html, "qtoken")}


def answer(c, iid, text=None, action="answer"):
    _, f = form_of(c, iid)
    data = dict(f, action=action)
    if text is not None:
        data["answer"] = text
    return c.post(f"/interviews/{iid}/answer", data=data, base_url=BASE)


def upload(c, iid, files):
    html = page(c, f"/interviews/{iid}").get_data(as_text=True)
    data = {"csrf_token": _field(html, "csrf_token"),
            "files": [(BytesIO(content), name) for name, content in files]}
    return c.post(f"/interviews/{iid}/uploads", data=data, content_type="multipart/form-data", base_url=BASE)


def record_ids(c, iid):
    return re.findall(rf"/interviews/{iid}/uploads/(R-[0-9a-f]{{20}})", page(c, f"/interviews/{iid}").get_data(as_text=True))


def through_preflight(c, iid):
    """Answer the family-law preflight with fictional, neutral answers."""
    answer(c, iid, "Yes, that's right.")          # confirm workspace
    answer(c, iid, "No.")                         # immediate danger
    answer(c, iid, "No.")                         # other urgent concern
    answer(c, iid, "Not that I know of.")         # deadline
    answer(c, iid, "Organizing my paperwork.")    # help first


# ============================================================ authentication
def test_unauthenticated_requests_get_nothing(env):
    a = browser(env)
    login(a, "alex.fictional", PW_A)
    iid = start(a)
    anon = browser(env)
    for path in ("/home", f"/interviews/{iid}", f"/interviews/{iid}/uploads/R-" + "0" * 20):
        r = page(anon, path)
        assert r.status_code == 302 and r.headers["Location"].startswith("/login")
    r = anon.post(f"/interviews/{iid}/draft", json={"text": "x"}, base_url=BASE)
    assert r.status_code == 401
    for path in (f"/interviews/{iid}/answer", f"/interviews/{iid}/uploads", "/interviews", f"/interviews/{iid}/resume"):
        r = anon.post(path, data={"answer": "x"}, base_url=BASE)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_wrong_password_and_unknown_user_look_identical(env):
    c = browser(env)
    r1 = login(c, "alex.fictional", "wrong-password-xxxx")
    r2 = login(c, "nobody.fictional", "wrong-password-xxxx")
    assert r1.status_code == r2.status_code == 401
    strip = lambda r: re.sub(r'value="[^"]*"', "", r.get_data(as_text=True))  # noqa: E731
    assert strip(r1) == strip(r2)
    assert page(c, "/home").status_code == 302


def test_lockout_after_repeated_failures(env):
    c = browser(env)
    for _ in range(acc_mod.LOCKOUT_THRESHOLD):
        assert login(c, "alex.fictional", "wrong-password-xxxx").status_code == 401
    assert login(c, "alex.fictional", PW_A).status_code == 401          # locked even with the right password
    env["clock"].t += acc_mod.LOCKOUT_WINDOW + 1
    assert login(c, "alex.fictional", PW_A).status_code == 302


def test_login_requires_pre_token(env):
    c = browser(env)
    r = c.post("/login", data={"username": "alex.fictional", "password": PW_A, "pre": "forged"}, base_url=BASE)
    assert r.status_code == 403


def test_password_policy_and_no_public_signup(env):
    with pytest.raises(PasswordPolicyError):
        env["accounts"].create_user("short.fictional", "short", new_client_id())
    c = browser(env)
    assert page(c, "/signup").status_code == 404
    assert page(c, "/register").status_code == 404


def test_app_refuses_to_start_without_a_valid_key(tmp_path):
    for bad in ("", "not-base64!!", base64.urlsafe_b64encode(b"short").decode()):
        with pytest.raises(KeyError_):
            create_app({"DATA_DIR": str(tmp_path / "d"), "MASTER_KEY": bad})
    with pytest.raises(RuntimeError):
        create_app({"DATA_DIR": "", "MASTER_KEY": generate_master_key()})


def test_disabled_user_is_signed_out_immediately(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    assert page(c, "/home").status_code == 200
    env["accounts"].set_disabled("alex.fictional", True)
    assert page(c, "/home").status_code == 302
    assert login(c, "alex.fictional", PW_A).status_code == 401


def test_password_reset_signs_out_existing_sessions(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    env["accounts"].set_password("alex.fictional", "a-new-fictional-passphrase")
    assert page(c, "/home").status_code == 302


# ============================================================ session security
def test_cookie_flags(env):
    c = browser(env)
    r = login(c, "alex.fictional", PW_A)
    cookie = [h for h in r.headers.getlist("Set-Cookie") if h.startswith("__Host-laylaw=")][0]
    for flag in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
        assert flag in cookie
    assert "Domain=" not in cookie and "Expires=" not in cookie and "Max-Age" not in cookie  # session cookie


def test_session_id_rotates_on_each_sign_in(env):
    c = browser(env)
    t1 = login(c, "alex.fictional", PW_A).headers.getlist("Set-Cookie")
    c2 = browser(env)
    t2 = login(c2, "alex.fictional", PW_A).headers.getlist("Set-Cookie")
    tok = lambda hs: [h for h in hs if h.startswith("__Host-laylaw=")][0].split(";")[0]  # noqa: E731
    assert tok(t1) != tok(t2)


def test_logout_blocks_replayed_cookie(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    token = c.get_cookie("__Host-laylaw", domain="laylaw.test").value
    csrf = csrf_of(c)
    r = c.post("/logout", data={"csrf_token": csrf}, base_url=BASE)
    assert r.status_code == 302 and "signed_out" in r.headers["Location"]
    assert page(c, "/home").status_code == 302

    replay = browser(env)
    replay.set_cookie("__Host-laylaw", token, domain="laylaw.test")
    assert page(replay, "/home").status_code == 302
    assert page(replay, f"/interviews/{iid}").status_code == 302
    r = replay.post(f"/interviews/{iid}/draft", json={"text": "x"}, headers={"X-CSRF-Token": csrf}, base_url=BASE)
    assert r.status_code == 401
    r = replay.post(f"/interviews/{iid}/answer", data={"csrf_token": csrf, "answer": "x"}, base_url=BASE)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_idle_and_absolute_timeouts(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    env["clock"].t += acc_mod.IDLE_TIMEOUT - 5
    assert page(c, "/home").status_code == 200                 # activity refreshes the idle timer
    env["clock"].t += acc_mod.IDLE_TIMEOUT + 1
    r = page(c, "/home")
    assert r.status_code == 302 and "expired=1" in r.headers["Location"]
    login(c, "alex.fictional", PW_A)
    for _ in range(int(acc_mod.ABSOLUTE_TIMEOUT // (acc_mod.IDLE_TIMEOUT - 60)) + 1):
        env["clock"].t += acc_mod.IDLE_TIMEOUT - 60
        page(c, "/home")
    assert page(c, "/home").status_code == 302                 # absolute cap reached despite activity


def test_csrf_and_origin_are_enforced(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    _, f = form_of(c, iid)
    r = c.post(f"/interviews/{iid}/answer", data={"qtoken": f["qtoken"], "answer": "x"}, base_url=BASE)
    assert r.status_code == 403
    r = c.post(f"/interviews/{iid}/answer", data=dict(f, answer="x"), base_url=BASE,
               headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post(f"/interviews/{iid}/draft", json={"text": "x"}, base_url=BASE)
    assert r.status_code == 403
    assert c.post("/logout", base_url=BASE).status_code == 403  # logout without CSRF refused, session kept
    assert page(c, "/home").status_code == 200


def test_security_headers(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    r = page(c, "/home")
    h = r.headers
    assert "script-src 'self'" in h["Content-Security-Policy"] and "unsafe-inline" not in h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["Cache-Control"] == "no-store"
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
    assert h["Referrer-Policy"] == "no-referrer"
    assert "max-age=" in h["Strict-Transport-Security"]
    assert "<script>" not in r.get_data(as_text=True)          # no inline scripts


def test_no_browser_storage_of_sensitive_values():
    static = Path(__file__).resolve().parents[1] / "laylaw" / "web"
    code = "".join(p.read_text() for p in static.rglob("*") if p.suffix in (".js", ".html"))
    assert not re.search(r"(localStorage|sessionStorage|indexedDB|document\.cookie)\s*[.\[=]", code)


# ============================================================ two-client isolation
def test_two_client_isolation_end_to_end(env):
    a, b = browser(env), browser(env)
    assert login(a, "alex.fictional", PW_A).status_code == 302
    assert login(b, "blair.fictional", PW_B).status_code == 302
    ia, ib = start(a), start(b, "criminal_defense")
    through_preflight(a, ia)
    answer(a, ia, f"Alex's fictional account {SENTINEL}-A of a library exchange.")
    answer(b, ib, "Yes, that's right.")
    upload(a, ia, [("alex-fictional-notes.txt", f"alex file {SENTINEL}-A".encode()),
                   ("alex-fictional-photo.png", b"\x89PNG fictional")])
    upload(b, ib, [("blair-fictional-letter.pdf", f"%PDF blair file {SENTINEL}-B".encode())])
    ra, rb = record_ids(a, ia), record_ids(b, ib)
    assert len(ra) == 2 and len(rb) == 1

    # Each sees only their own interview, name and files.
    ha, hb = page(a, "/home").get_data(as_text=True), page(b, "/home").get_data(as_text=True)
    assert ia in ha and ib not in ha and "Alex Fictional" in ha and "Blair" not in ha
    assert ib in hb and ia not in hb and "Blair Fictional" in hb and "Alex" not in hb
    assert "blair-fictional-letter.pdf" not in page(a, f"/interviews/{ia}").get_data(as_text=True)

    nonexistent = "INT-" + "f" * 10
    for (me, mine, theirs, their_recs) in ((a, ia, ib, rb), (b, ib, ia, ra)):
        miss = page(me, f"/interviews/{nonexistent}")
        for path in (f"/interviews/{theirs}", f"/interviews/{theirs}/uploads/{their_recs[0]}",
                     f"/interviews/{mine}/uploads/{their_recs[0]}"):
            r = page(me, path)
            assert r.status_code == 404
            assert r.get_data() == miss.get_data()          # indistinguishable from "does not exist"
        csrf = csrf_of(me)
        _, f = form_of(me, mine)
        for path, data in ((f"/interviews/{theirs}/answer", dict(f, answer=f"{SENTINEL}-X")),
                           (f"/interviews/{theirs}/resume", {"csrf_token": csrf}),
                           (f"/interviews/{theirs}/uploads", {"csrf_token": csrf,
                                                             "files": [(BytesIO(b"x"), "x.txt")]})):
            r = me.post(path, data=data, base_url=BASE, content_type="multipart/form-data")
            assert r.status_code == 404
        r = me.post(f"/interviews/{theirs}/draft", json={"text": f"{SENTINEL}-X"},
                    headers={"X-CSRF-Token": csrf}, base_url=BASE)
        assert r.status_code == 404
        # Guessing: malformed and traversal-style ids are refused, not interpreted.
        for bad in ("..", "..%2F..%2Fclients", "INT-../../x", "%2e%2e", "INT-" + "0" * 10):
            assert page(me, f"/interviews/{bad}").status_code == 404

    # Nothing B attempted landed in A's interview, and vice versa.
    sa = env["store"].workspace(env["ids"]["alex.fictional"]).load_session(ia)
    sb = env["store"].workspace(env["ids"]["blair.fictional"]).load_session(ib)
    assert not any(f"{SENTINEL}-X" in (t.answer or "") for t in sa.turns + sb.turns)
    assert [r.id for r in sa.records] == ra and [r.id for r in sb.records] == rb
    assert all(r.client_id == env["ids"]["alex.fictional"] for r in sa.records)

    # Own downloads work, are private attachments, and match what was uploaded.
    r = page(a, f"/interviews/{ia}/uploads/{ra[0]}")
    assert r.status_code == 200 and r.get_data() == f"alex file {SENTINEL}-A".encode()
    assert r.headers["Content-Type"] == "application/octet-stream"
    assert r.headers["Content-Disposition"].startswith("attachment;")
    assert r.headers["Cache-Control"] == "no-store"


def test_each_client_resumes_correctly_through_the_ui(env):
    for user, pw in (("alex.fictional", PW_A), ("blair.fictional", PW_B)):
        c = browser(env)
        login(c, user, pw)
        iid = start(c)
        through_preflight(c, iid)
        answer(c, iid, f"A fictional account from {user} about an exchange at the park.")
        html, _ = form_of(c, iid)
        pending = re.search(r'class="question">(.*?)</label>', html, re.S).group(1)
        # Type a draft, then save-and-finish-later, then sign out.
        csrf = csrf_of(c)
        assert c.post(f"/interviews/{iid}/draft", json={"text": f"half-typed {user}"},
                      headers={"X-CSRF-Token": csrf}, base_url=BASE).get_json() == {"saved": True}
        r = answer(c, iid, text=f"half-typed {user}", action="later")   # textarea contents are posted too
        assert r.status_code == 302 and "m=saved" in r.headers["Location"]
        c.post("/logout", data={"csrf_token": csrf_of(c)}, base_url=BASE)

        c2 = browser(env)
        login(c2, user, pw)
        home = page(c2, "/home").get_data(as_text=True)
        assert iid in home and "Paused" in home
        r = page(c2, f"/interviews/{iid}")
        assert "Welcome back" in r.get_data(as_text=True) and "Shall we continue there?" in r.get_data(as_text=True)
        c2.post(f"/interviews/{iid}/resume", data={"csrf_token": csrf_of(c2)}, base_url=BASE)
        html, _ = form_of(c2, iid)
        assert re.search(r'class="question">(.*?)</label>', html, re.S).group(1) == pending
        assert f"half-typed {user}" in html                          # draft survived sign-out
        answer(c2, iid, "Just me.")
        s = env["store"].workspace(env["ids"][user]).load_session(iid)
        assert s.turns[-1].answer == "Just me." and s.is_continuation


def test_stale_page_cannot_answer_a_different_question(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    _, old = form_of(c, iid)
    answer(c, iid, "Yes, that's right.")                                   # question moves on
    r = c.post(f"/interviews/{iid}/answer", data=dict(old, action="answer", answer="No."), base_url=BASE)
    assert "m=stale" in r.headers["Location"]
    s = env["store"].workspace(env["ids"]["alex.fictional"]).load_session(iid)
    assert [t.answer for t in s.turns] == ["Yes, that's right."]


def test_skip_and_not_sure_through_the_ui(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    through_preflight(c, iid)
    answer(c, iid, action="not_sure")
    s = env["store"].workspace(env["ids"]["alex.fictional"]).load_session(iid)
    assert s.turns[-1].control == "not_sure" and not s.facts


def test_danger_answer_shows_safety_notice(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    answer(c, iid, "Yes, that's right.")
    answer(c, iid, "Yes")                                                   # immediate danger
    html = page(c, f"/interviews/{iid}").get_data(as_text=True)
    assert "call 911" in html and 'class="safety"' in html


def test_upload_rules(env):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    r = upload(c, iid, [("fine.txt", b"ok"), ("script.html", b"<script>alert(1)</script>"),
                        ("empty.pdf", b""), ("noext", b"x")])
    assert "m=up1-3" in r.headers["Location"]
    import laylaw.web.app as app_mod
    big = b"x" * (app_mod.MAX_FILE_BYTES + 1)
    r = upload(c, iid, [("big.pdf", big)])
    assert r.status_code in (302, 413)
    assert len(record_ids(c, iid)) == 1


# ============================================================ storage at rest
def _all_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def test_nothing_readable_at_rest(env):
    a = browser(env)
    login(a, "alex.fictional", PW_A)
    ia = start(a)
    through_preflight(a, ia)
    answer(a, ia, f"Fictional account {SENTINEL} with a unique phrase.")
    upload(a, ia, [(f"{SENTINEL}-name.txt", f"file body {SENTINEL}".encode())])
    a.post(f"/interviews/{ia}/draft", json={"text": f"draft {SENTINEL}"},
           headers={"X-CSRF-Token": csrf_of(a)}, base_url=BASE)
    blob = _all_bytes(env["data"])
    for secret in (SENTINEL, "Alex Fictional", "Blair Fictional", "CASE-FICTIONAL", "library", "exchange"):
        assert secret.encode() not in blob, secret
    names = " ".join(str(p) for p in env["data"].rglob("*"))
    assert SENTINEL not in names and ".txt" not in names and "alex" not in names.lower()
    for p in [env["data"], *env["data"].rglob("*")]:
        assert (p.stat().st_mode & 0o777) == (0o700 if p.is_dir() else 0o600), p
    assert (env["data"] / "accounts.sqlite3").stat().st_mode & 0o077 == 0


def test_ciphertext_is_bound_to_client_and_object(env, tmp_path):
    store = env["store"]
    a_id, b_id = env["ids"]["alex.fictional"], env["ids"]["blair.fictional"]
    wa, wb = store.workspace(a_id), store.workspace(b_id)
    from laylaw.interviewer import InterviewSession
    s = InterviewSession.start(wa, case_id="C-F", interviewee="Alex Fictional", interviewer="L",
                               purpose="t", sections=["Specific incidents"], interviewee_is_adult=True)
    src = wa.dir / "sessions" / f"{s.interview_id}.enc"
    # Copied into B's workspace: B's key cannot open it.
    dst = wb.dir / "sessions" / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    with pytest.raises(WorkspaceIsolationError):
        wb.load_session(s.interview_id)
    # Renamed to another id inside A: bound to the original id, refused.
    other = "INT-" + "a" * 10
    (wa.dir / "sessions" / f"{other}.enc").write_bytes(src.read_bytes())
    with pytest.raises(WorkspaceIsolationError):
        wa.load_session(other)
    # One flipped byte: refused.
    data = bytearray(src.read_bytes())
    data[-1] ^= 1
    src.write_bytes(bytes(data))
    with pytest.raises(WorkspaceIsolationError):
        wa.load_session(s.interview_id)
    # A different master key cannot read anything.
    wrong = EncryptedStore(store.root, base64.urlsafe_b64decode(generate_master_key()))
    rec = wa.store_upload(s.interview_id, "f.txt", b"fictional")
    with pytest.raises(WorkspaceIsolationError):
        wrong.workspace(a_id).read_upload(rec)
    # A record naming client A can't be read through B's handle.
    with pytest.raises(WorkspaceIsolationError):
        wb.read_upload(rec)


def test_invalid_client_ids_fail_closed(env):
    for bad in ("../x", "client-fictional-a", "c-" + "z" * 20, "", None):
        with pytest.raises(WorkspaceIsolationError):
            env["store"].workspace(bad)


# ============================================================ logging / privacy
def test_logs_never_contain_content_tokens_or_keys(env, caplog):
    caplog.set_level(logging.DEBUG)
    a = browser(env)
    login(a, "alex.fictional", "wrong-password-xxxx")
    login(a, "alex.fictional", PW_A)
    token = a.get_cookie("__Host-laylaw", domain="laylaw.test").value
    ia = start(a)
    through_preflight(a, ia)
    answer(a, ia, f"Account with {SENTINEL} and more.")
    upload(a, ia, [(f"{SENTINEL}.pdf", f"%PDF {SENTINEL}".encode())])
    rid = record_ids(a, ia)[0]
    page(a, f"/interviews/{ia}/uploads/{rid}")
    csrf = csrf_of(a)
    a.post(f"/interviews/{ia}/draft", json={"text": SENTINEL}, headers={"X-CSRF-Token": csrf}, base_url=BASE)
    b = browser(env)
    login(b, "blair.fictional", PW_B)
    page(b, f"/interviews/{ia}/uploads/{rid}")                               # denied attempt gets logged
    b.post(f"/interviews/{ia}/answer", data={"csrf_token": "bad", "answer": SENTINEL}, base_url=BASE)
    a.post("/logout", data={"csrf_token": csrf}, base_url=BASE)
    text = caplog.text + "\n".join(str(r.args) for r in caplog.records)
    for s in (SENTINEL, PW_A, PW_B, token, csrf, env["key"], "Alex Fictional"):
        assert s not in text
    # The audit table records events and opaque ids only.
    rows = env["accounts"]._q("SELECT * FROM audit")
    flat = repr(rows)
    assert "login" in flat and "upload_stored" in flat
    for s in (SENTINEL, "Alex Fictional", "alex.fictional", PW_A):
        assert s not in flat


def test_server_errors_are_generic_and_do_not_log_messages(env, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    from laylaw.interviewer.session import InterviewSession

    def boom(self, text, **tags):
        raise ValueError(f"engine failure mentioning {SENTINEL}")
    monkeypatch.setattr(InterviewSession, "answer", boom)
    r = answer(c, iid, "Yes, that's right.")
    assert r.status_code == 500 and SENTINEL not in r.get_data(as_text=True)
    assert "Traceback" not in caplog.text and SENTINEL not in caplog.text
    assert "server_error type=ValueError" in caplog.text


def test_large_uploads_never_touch_disk_unencrypted(env, monkeypatch):
    import tempfile
    made = []
    real = tempfile.SpooledTemporaryFile
    monkeypatch.setattr(tempfile, "TemporaryFile", lambda *a, **k: made.append(1) or real(*a, **k))
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", lambda *a, **k: made.append(1) or real(*a, **k))
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    body = (SENTINEL.encode() + b"-") * 200_000                            # ~4 MB, well over the 500 KB spool size
    r = upload(c, iid, [("large-fictional.pdf", body)])
    assert "m=up1-0" in r.headers["Location"] and not made
    rid = record_ids(c, iid)[0]
    assert page(c, f"/interviews/{iid}/uploads/{rid}").get_data() == body


def test_unconfirmed_workspace_blocks_until_operator_confirms(env, monkeypatch, capsys):
    c = browser(env)
    login(c, "alex.fictional", PW_A)
    iid = start(c)
    answer(c, iid, "No, that's not me.")
    html = page(c, f"/interviews/{iid}").get_data(as_text=True)
    assert "Paused for now" in html and 'name="qtoken"' not in html
    from laylaw.web import admin
    monkeypatch.setenv("LAYLAW_DATA_DIR", str(env["data"]))
    monkeypatch.setenv("LAYLAW_MASTER_KEY", env["key"])
    assert admin.main(["confirm-workspace", "alex.fictional", iid]) == 0
    html = page(c, f"/interviews/{iid}").get_data(as_text=True)
    assert 'name="qtoken"' in html and "immediate danger" in html
    # The operator command is scoped by username: B's name can't reach A's interview.
    with pytest.raises(SystemExit):
        admin.main(["confirm-workspace", "blair.fictional", iid])

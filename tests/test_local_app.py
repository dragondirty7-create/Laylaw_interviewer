"""End-to-end: Chelsea's workflow through the local app, over real HTTP on 127.0.0.1.

Launch -> access gate -> new interview -> one question at a time -> save and exit ->
lock -> unlock -> resume -> upload -> finish -> outputs -> delete. Plus the app's
network and request protections. ALL DATA IS SYNTHETIC AND FICTIONAL.
"""
import html
import http.client
import json
import re
import threading
import uuid

import pytest

from laylaw.app.server import LaylawApp, launch_url, make_server
from laylaw.secure.audit import AuditLog
from laylaw.secure.secrets_store import MemorySecretStore
from laylaw.secure.vault import audit_key_for, init_vault

PASS = "fictional passphrase 42"


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None

    def req(self, method, path, form=None, *, host=None, origin="same", body=None, ctype=None, cookie=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if cookie and self.cookie:
            headers["Cookie"] = self.cookie
        if origin == "same":
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
        elif origin:
            headers["Origin"] = origin
        if form is not None:
            body = "&".join(f"{k}={_q(v)}" for k, v in form.items()).encode()
            ctype = "application/x-www-form-urlencoded"
        if body is not None:
            headers["Content-Type"] = ctype
            headers["Content-Length"] = str(len(body))
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        headers = dict(resp.getheaders())
        conn.close()
        if "Set-Cookie" in headers:
            self.cookie = headers["Set-Cookie"].split(";")[0]
        return resp.status, headers, text


def _q(v):
    from urllib.parse import quote_plus
    return quote_plus(str(v))


def question_of(page):
    m = re.search(r"<p class=q>(.*?)</p>", page, re.S)
    return html.unescape(m.group(1)) if m else None


@pytest.fixture
def running(tmp_path):
    ss = MemorySecretStore()
    root = tmp_path / "vault"
    v, _ = init_vault(root, PASS, secret_store=ss, mode="synthetic", kdf_n=2 ** 12)
    v.lock()
    clock = [0.0]
    app = LaylawApp(root, ss, clock=lambda: clock[0])
    server = make_server(app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield app, Client(app.port), root, ss, clock
    server.shutdown()
    server.server_close()


def launch_and_unlock(app, c):
    status, headers, _ = c.req("GET", launch_url(app).split(str(app.port), 1)[1])
    assert status == 303 and "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    status, _, _ = c.req("POST", "/unlock", {"csrf": app.csrf, "passphrase": PASS})
    assert status == 303


def test_chelsea_can_run_a_whole_interview(running):
    app, c, root, ss, _clock = running
    launch_and_unlock(app, c)

    status, headers, page = c.req("GET", "/")
    assert status == 200 and "Start a new interview" in page
    assert "SYNTHETIC DATA ONLY" in page
    assert headers["Cache-Control"].startswith("no-store")
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "<script" not in page.lower()

    status, headers, _ = c.req("POST", "/new", {"csrf": app.csrf, "client_id": "client-fictional-a",
                                                "case_id": "CASE-FICTIONAL-777", "interviewee": "Jordan Avery",
                                                "path_name": "family_law", "adult": "yes"})
    assert status == 303
    interview = headers["Location"]
    assert re.fullmatch(r"/i/client-fictional-a/INT-[0-9a-f]+", interview)

    # One question at a time, in the engine's order.
    status, _, page = c.req("GET", interview)
    assert "Jordan Avery (case CASE-FICTIONAL-777)" in question_of(page)
    for answer in ["Yes", "No", "No", "No", "Help with the parenting schedule"]:
        c.req("POST", f"{interview}/answer", {"csrf": app.csrf, "action": "answer", "answer": answer})
    _, _, page = c.req("GET", interview)
    first_topic_q = question_of(page)
    assert first_topic_q and "danger" not in first_topic_q
    c.req("POST", f"{interview}/answer", {"csrf": app.csrf, "action": "answer",
                                          "answer": "Pip lives with me during the week. Sam Rowe has weekends."})
    _, _, page = c.req("GET", interview)
    pending = question_of(page)

    # Save and exit, lock, come back.
    status, headers, _ = c.req("POST", f"{interview}/answer", {"csrf": app.csrf, "action": "save_later"})
    assert headers["Location"] == "/"
    _, _, page = c.req("GET", "/")
    assert "Saved for later" in page
    c.req("POST", "/lock", {"csrf": app.csrf})
    _, _, page = c.req("GET", interview)
    assert "Passphrase" in page and "Jordan" not in page  # locked: nothing about the case is shown
    c.req("POST", "/unlock", {"csrf": app.csrf, "passphrase": PASS})
    _, _, page = c.req("GET", interview)
    assert "Continue" in page and "Shall we continue" in question_of(page)
    c.req("POST", f"{interview}/resume", {"csrf": app.csrf})
    _, _, page = c.req("GET", interview)
    assert question_of(page) == pending

    # Upload through the encrypted path.
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"csrf\"\r\n\r\n{app.csrf}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"label\"\r\n\r\nFictional school calendar\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"calendar_avery.pdf\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n%PDF-1.4 SYNTHETIC-UPLOAD-BYTES\r\n--{boundary}--\r\n").encode()
    status, _, _ = c.req("POST", f"{interview}/upload", body=body, ctype=f"multipart/form-data; boundary={boundary}")
    assert status == 303
    _, _, page = c.req("GET", interview)
    assert "Fictional school calendar" in page and "stored encrypted" in page

    # Skip and Not sure work from the page.
    c.req("POST", f"{interview}/answer", {"csrf": app.csrf, "action": "skip"})
    c.req("POST", f"{interview}/answer", {"csrf": app.csrf, "action": "not_sure"})

    # Finish the interview.
    for _ in range(200):
        _, _, page = c.req("GET", interview)
        if "This interview is complete" in page:
            break
        c.req("POST", f"{interview}/answer", {"csrf": app.csrf, "action": "answer", "answer": "Nothing else."})
    else:
        pytest.fail("interview did not finish")

    status, _, page = c.req("GET", interview.replace("/i/", "/o/"))
    assert status == 200
    for heading in ("Handoff summary", "Fact table", "Timeline", "Evidence follow-up", "Open questions",
                    "Requested outcomes", "Interview record"):
        assert heading in page
    assert "Pip lives with me during the week" in page

    # Nothing readable on disk, and the audit trail is intact and content-free.
    for p in root.rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            for marker in (b"Jordan Avery", b"Sam Rowe", b"SYNTHETIC-UPLOAD-BYTES", b"calendar_avery",
                           b"parenting schedule", b"client-fictional-a"):
                assert marker not in data, (marker, p.name)
    log = AuditLog(root, audit_key_for(root, ss))
    n = log.verify()
    events = [json.loads(line)["event"] for line in (root / "audit.log").read_text().splitlines()]
    assert n == len(events)
    for ev in ("unlock_ok", "session_created", "session_saved_for_later", "locked", "session_open",
               "session_resumed", "upload_stored", "outputs_viewed"):
        assert ev in events, ev

    # Delete it.
    status, _, _ = c.req("POST", interview.replace("/i/", "/d/"), {"csrf": app.csrf, "confirm": "nope"})
    assert status == 303
    status, headers, _ = c.req("POST", interview.replace("/i/", "/d/"), {"csrf": app.csrf, "confirm": "DELETE"})
    assert headers["Location"] == "/"
    status, _, _ = c.req("GET", interview)
    assert status == 404
    assert list((root / "data").iterdir())  # workspace index remains; the interview's files are gone


def test_requests_without_the_launch_cookie_get_nothing(running):
    app, c, *_ = running
    assert c.req("GET", "/")[0] == 403
    assert c.req("POST", "/unlock", {"csrf": app.csrf, "passphrase": PASS})[0] == 403
    assert c.req("GET", "/start?t=wrong")[0] == 403
    launch_and_unlock(app, c)
    other = Client(app.port)
    assert other.req("GET", launch_url(app).split(str(app.port), 1)[1])[0] == 403  # launch link is single-use
    assert other.req("GET", "/")[0] == 403


def test_host_origin_and_csrf_checks(running):
    app, c, *_ = running
    launch_and_unlock(app, c)
    assert c.req("GET", "/", host="evil.example:80")[0] == 421  # DNS rebinding
    assert c.req("POST", "/lock", {"csrf": app.csrf}, origin="http://evil.example")[0] == 403
    assert c.req("POST", "/lock", {"csrf": app.csrf}, origin="null")[0] == 403
    assert c.req("POST", "/lock", {"csrf": "forged"})[0] == 403
    assert "Start a new interview" in c.req("GET", "/")[2]  # still unlocked: the forged requests did nothing


def test_wrong_passphrase_shows_error_and_stays_locked(running):
    app, c, *_ = running
    c.req("GET", launch_url(app).split(str(app.port), 1)[1])
    c.req("POST", "/unlock", {"csrf": app.csrf, "passphrase": "wrong"})
    page = c.req("GET", "/")[2]
    assert "didn" in page and "Passphrase" in page and app.store is None


def test_idle_lock(running):
    app, c, _root, _ss, clock = running
    launch_and_unlock(app, c)
    clock[0] += 16 * 60
    page = c.req("GET", "/")[2]
    assert "locked itself" in page and app.store is None


def test_only_loopback(tmp_path):
    ss = MemorySecretStore()
    v, _ = init_vault(tmp_path / "v", PASS, secret_store=ss, mode="synthetic", kdf_n=2 ** 12)
    v.lock()
    app = LaylawApp(tmp_path / "v", ss)
    for host in ("0.0.0.0", "192.168.1.20", "::"):
        with pytest.raises(ValueError):
            make_server(app, host=host)
    server = make_server(app)
    assert server.server_address[0] == "127.0.0.1"
    server.server_close()


def test_quit_locks_and_stops(running):
    app, c, *_ = running
    launch_and_unlock(app, c)
    status, _, page = c.req("POST", "/quit", {"csrf": app.csrf})
    assert status == 200 and "locked and closed" in page
    assert app.store is None and app.shutdown_requested


def test_referrer_policy_lets_browsers_send_a_real_origin(running):
    """Regression: with Referrer-Policy no-referrer, Chromium sends "Origin: null" on every form POST and
    the app refused all of them, including Unlock. Found by driving the app in Chromium on 2026-10-08."""
    app, c, *_ = running
    status, headers, _ = c.req("GET", launch_url(app).split(str(app.port), 1)[1])
    status, headers, _ = c.req("GET", "/")
    assert headers["Referrer-Policy"] == "same-origin"
    # A null Origin is still refused.
    status, _, _ = c.req("POST", "/unlock", {"csrf": app.csrf, "passphrase": PASS}, origin="null")
    assert status == 403

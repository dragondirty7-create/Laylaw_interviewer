"""The local Laylaw app: a small web page served only to this computer.

Security properties (see SECURITY.md for the full list and limits):
* Listens on 127.0.0.1 only. Any non-loopback address is refused.
* A one-time launch token (opened in the browser by the launcher) sets an
  HttpOnly, SameSite=Strict cookie. Requests without it get nothing, so other
  local accounts or web pages probing the port can't use the app.
* Host header must be this loopback address and port (DNS rebinding defense);
  POSTs need a per-launch CSRF token and a matching Origin when sent.
* No JavaScript. Strict Content-Security-Policy; every response is no-store so
  case text isn't written to the browser cache.
* The vault key lives only in this process, and only while unlocked. The app
  locks after 15 idle minutes, on "Lock", and on exit.
"""
from __future__ import annotations

import hmac
import re
import secrets
import threading
import time
import webbrowser
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..interviewer import outputs as outputs_mod
from ..interviewer.models import SessionStatus
from ..interviewer.paths import PATHS, start_path
from ..interviewer.workspace import WorkspaceIsolationError, _check_id
from ..secure.errors import AccessDenied, NotReadyForRealData, SecureStorageError, VaultError
from ..secure.mode import AccessGate
from ..secure.secrets_store import SecretStore
from ..secure.store import MAX_UPLOAD_BYTES, SecureStore
from ..secure.vault import read_header
from . import intake_pages, pages
from ..intake import service as intake_service
from ..intake.model import AnswerStatus, IntakeError
from ..intake.packet import PacketError
from ..intake.steps import STEP_BY_ID

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
IDLE_LOCK_S = 15 * 60
MAX_BODY = MAX_UPLOAD_BYTES + 1024 * 1024
COOKIE = "laylaw"
_NPATH = re.compile(r"^/n/(matter-[a-f0-9]{12})/(N-[a-f0-9]{12})(/[a-z_]+)?$")
_PATH = re.compile(r"^/(i|o|d)/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/([A-Za-z0-9][A-Za-z0-9_-]{0,63})(/[a-z_]+)?$")


class LaylawApp:
    def __init__(self, root: str | Path, secret_store: SecretStore, *, idle_lock_s: float = IDLE_LOCK_S,
                 clock=time.monotonic):
        self.root = Path(root).resolve()
        self.secret_store = secret_store
        self.header = read_header(self.root)
        self.gate = AccessGate(self.root, secret_store, clock=clock)
        self.clock = clock
        self.idle_lock_s = idle_lock_s
        self.store: SecureStore | None = None
        self.sessions: dict[tuple[str, str], object] = {}
        self.launch_token = secrets.token_urlsafe(32)
        self.cookie_value = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.launch_used = False
        self.last_activity = clock()
        self.port = 0
        self.lock = threading.RLock()
        self.flash: list[tuple[str, str]] = []
        self.shutdown_requested = False

    @property
    def banner(self) -> str:
        return "SYNTHETIC DATA ONLY: this vault is not set up for real case information." \
            if self.header.mode != "real" else ""

    # -- vault state -------------------------------------------------------
    def lock_vault(self, reason: str) -> None:
        if self.store is not None:
            self.store.audit.append("locked", detail={"reason": reason})
            self.store.vault.lock()
        self.store = None
        self.sessions.clear()

    def touch(self) -> None:
        now = self.clock()
        if self.store is not None and now - self.last_activity > self.idle_lock_s:
            self.lock_vault("idle")
            self.flash.append(("err", "Laylaw locked itself after 15 minutes without activity."))
        self.last_activity = now

    def session(self, cid: str, sid: str):
        key = (cid, sid)
        if key not in self.sessions:
            ws = self.store.existing_workspace(cid)
            self.sessions[key] = ws.load_session(sid)
        return self.sessions[key]

    def take_flash(self) -> list[tuple[str, str]]:
        msgs, self.flash = self.flash, []
        return msgs


class Handler(BaseHTTPRequestHandler):
    server_version = "Laylaw"
    sys_version = ""
    app: LaylawApp

    # never print request paths (they contain workspace labels) to the terminal
    def log_message(self, fmt, *args):  # noqa: D401
        return

    # -- responses ---------------------------------------------------------
    def _send(self, status: int, body: str = "", *, location: str | None = None,
              cookie: str | None = None) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                         "frame-ancestors 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # same-origin, not no-referrer: under no-referrer Chromium browsers send "Origin: null" on form
        # POSTs, which _origin_ok rightly refuses, so nothing could be submitted (not even Unlock).
        # same-origin still sends no referrer to any other site.
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _redirect(self, where: str) -> None:
        self._send(303, "", location=where)

    def _forbidden(self, text="Open Laylaw from its launcher on this computer.") -> None:
        self._send(403, pages.refused_page(text))

    # -- checks ------------------------------------------------------------
    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        return host in (f"127.0.0.1:{self.app.port}", f"localhost:{self.app.port}", f"[::1]:{self.app.port}")

    def _cookie_ok(self) -> bool:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        got = jar.get(COOKIE)
        return bool(got) and hmac.compare_digest(got.value, self.app.cookie_value)

    def _origin_ok(self) -> bool:
        # Browsers send Origin on form POSTs. A missing Origin (non-browser client) still needs the
        # cookie and CSRF token; a cross-site or "null" Origin is refused.
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin in (f"http://127.0.0.1:{self.app.port}", f"http://localhost:{self.app.port}",
                          f"http://[::1]:{self.app.port}")

    def _form(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return None
        raw = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            msg = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + ctype.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
            form: dict = {}
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                form[name] = {"filename": filename, "data": payload} if filename is not None else \
                    payload.decode("utf-8", "replace")
            return form
        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}

    # -- dispatch ----------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        app = self.app
        if not self._host_ok():
            return self._send(421, pages.refused_page("Wrong host."))
        url = urlsplit(self.path)
        with app.lock:
            if url.path == "/start":
                token = parse_qs(url.query).get("t", [""])[0]
                if app.launch_used or not hmac.compare_digest(token, app.launch_token):
                    return self._forbidden("This launch link has already been used. Start Laylaw again from "
                                           "its launcher.")
                app.launch_used = True
                return self._send(303, "", location="/",
                                  cookie=f"{COOKIE}={app.cookie_value}; HttpOnly; SameSite=Strict; Path=/")
            if not self._cookie_ok():
                return self._forbidden()
            app.touch()
            if app.store is None:
                return self._send(200, pages.unlock_page(app.csrf, banner=app.banner, messages=app.take_flash()))
            try:
                return self._get_unlocked(url.path)
            except (FileNotFoundError, WorkspaceIsolationError):
                return self._send(404, pages.refused_page("That interview isn't in this vault."))
            except SecureStorageError:
                return self._send(500, pages.refused_page("An encrypted file failed its integrity check. "
                                                          "Nothing was changed. Contact your administrator."))

    def do_POST(self):
        app = self.app
        if not self._host_ok():
            return self._send(421, pages.refused_page("Wrong host."))
        with app.lock:
            if not self._cookie_ok() or not self._origin_ok():
                return self._forbidden()
            form = self._form()
            if form is None:
                return self._send(413, pages.refused_page("That file is too large (limit 25 MB)."))
            if not hmac.compare_digest(str(form.get("csrf", "")), app.csrf):
                return self._forbidden("This form expired. Go back to the home page and try again.")
            app.touch()
            path = urlsplit(self.path).path
            if path == "/quit":
                app.lock_vault("closed")
                app.shutdown_requested = True
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return self._send(200, pages.closed_page())
            if path == "/lock":
                app.lock_vault("manual")
                return self._redirect("/")
            if path == "/unlock":
                try:
                    app.store = app.gate.open(str(form.get("passphrase", "")))
                except NotReadyForRealData as exc:
                    app.flash.append(("err", str(exc)))
                except (AccessDenied, VaultError) as exc:
                    app.flash.append(("err", str(exc)))
                return self._redirect("/")
            if app.store is None:
                return self._redirect("/")
            try:
                return self._post_unlocked(path, form)
            except (FileNotFoundError, WorkspaceIsolationError):
                return self._send(404, pages.refused_page("That interview isn't in this vault."))
            except SecureStorageError:
                return self._send(500, pages.refused_page("An encrypted file failed its integrity check. "
                                                          "Nothing was changed. Contact your administrator."))

    # -- unlocked pages ----------------------------------------------------
    def _meta(self, s) -> dict:
        return {"interviewee": s.interviewee, "case_id": s.case_id, "path": s.path_name}

    def _get_unlocked(self, path: str):
        app = self.app
        if path == "/":
            ws = [(cid, app.store.existing_workspace(cid).session_summaries()) for cid in app.store.list_clients()
                  if not cid.startswith(intake_service.MATTER_PREFIX)]
            extra = intake_pages.home_section(app.csrf, intake_service.list_matters(app.store))
            return self._send(200, pages.home_page(app.csrf, ws, banner=app.banner, messages=app.take_flash(),
                                                   extra=extra))
        if path.startswith("/n/"):
            return self._get_intake(path)
        m = _PATH.match(path)
        if not m or m.group(4):
            return self._send(404, pages.refused_page("Not found."))
        kind, cid, sid = m.group(1), m.group(2), m.group(3)
        s = app.session(cid, sid)
        if kind == "o":
            out = outputs_mod.all_outputs(s)
            app.store.audit.append("outputs_viewed", ws=app.store.ref(cid), session=app.store.ref(sid))
            return self._send(200, pages.outputs_page(app.csrf, cid, sid, self._meta(s), out, banner=app.banner,
                                                      messages=app.take_flash()))
        if kind == "d":
            return self._send(200, pages.delete_page(app.csrf, cid, sid, self._meta(s), banner=app.banner))
        return self._send(200, self._interview(cid, sid, s))

    def _interview(self, cid, sid, s) -> str:
        app = self.app
        ws = app.store.existing_workspace(cid)
        sizes = {rid: meta.get("size") for rid, meta in ws._index()["uploads"].items()}
        records = [{"label": r.label, "size": sizes.get(r.id, "?")} for r in s.records]
        notice = PATHS.get(s.path_name, {}).get("notice") if not s.turns else None
        if s.status == SessionStatus.PAUSED:
            state, question = "resume", s.resume_prompt()
        elif s.workspace_confirmed is False:
            state, question = "wrong_workspace", None
        else:
            question = s.next_question()
            if question is None:
                state = "done"
            elif s.status == SessionStatus.PAUSED_FOR_SAFETY:
                state = "safety"
            else:
                state = "ask"
        return pages.interview_page(app.csrf, cid, sid, meta=self._meta(s), question=question, state=state,
                                    notice=notice, records=records, banner=app.banner, messages=app.take_flash())

    # -- incident intake -----------------------------------------------------
    def _intake(self, path: str):
        m = _NPATH.match(path)
        if not m:
            raise FileNotFoundError("not an intake path")
        cid, mid, action = m.group(1), m.group(2), (m.group(3) or "")[1:]
        ws = self.app.store.existing_workspace(cid)
        try:
            return ws, intake_service.load(ws, mid), action
        except IntakeError as exc:
            raise WorkspaceIsolationError(str(exc)) from exc

    def _get_intake(self, path: str):
        app = self.app
        ws, intake, action = self._intake(path)
        kw = {"banner": app.banner, "messages": app.take_flash()}
        if action == "":
            sid = intake.editing or intake.current
            if sid is None:
                return self._send(200, intake_pages.review_page(app.csrf, intake, **kw))
            return self._send(200, intake_pages.step_page(app.csrf, intake, STEP_BY_ID[sid],
                                                          editing=intake.editing is not None, **kw))
        if action == "review":
            return self._send(200, intake_pages.review_page(app.csrf, intake, **kw))
        if action == "packet":
            try:
                html = intake_pages.packet_page(app.csrf, intake, integrity=intake_service.verify_evidence(ws, intake),
                                                **kw)
            except PacketError:
                return self._send(500, pages.refused_page("The packet could not be produced because Laylaw's own "
                                                          "wording failed a neutrality check. Nothing was shown."))
            app.store.audit.append("packet_viewed", ws=app.store.ref(ws.client_id),
                                   session=app.store.ref(intake.matter_id))
            return self._send(200, html)
        if action == "delete":
            return self._send(200, intake_pages.delete_page(app.csrf, intake, banner=app.banner))
        return self._send(404, pages.refused_page("Not found."))

    def _post_intake(self, path: str, form: dict):
        app = self.app
        ws, intake, action = self._intake(path)
        base = f"/n/{ws.client_id}/{intake.matter_id}"
        try:
            if action == "answer":
                choice = str(form.get("action", "answer"))
                step_id = str(form.get("step", ""))
                if choice == "later":
                    intake_service.save(ws, intake)
                    app.flash.append(("ok", "Saved. Open it from this page when you're ready to continue."))
                    return self._redirect("/")
                if choice == "back":
                    intake.go_back()
                elif choice == "cancel_edit":
                    intake.cancel_edit()
                    intake_service.save(ws, intake)
                    return self._redirect(f"{base}/review")
                else:
                    status = {"answer": AnswerStatus.ANSWERED, "done": AnswerStatus.ANSWERED,
                              "not_sure": AnswerStatus.NOT_SURE, "skip": AnswerStatus.SKIPPED}.get(choice)
                    if status is None:
                        return self._send(400, pages.refused_page("Unknown action."))
                    value = "done" if choice == "done" else str(form.get("value", ""))
                    was_editing = intake.editing == step_id
                    intake.respond(step_id, status, value)
                    if step_id == "stage_gate" and intake.value("stage_gate") == "later":
                        intake_service.save(ws, intake)
                        app.flash.append(("ok", "The essentials are saved. Open this intake again any time to "
                                                "add more detail."))
                        return self._redirect("/")
                    if was_editing and intake.current is None:
                        intake_service.save(ws, intake)
                        return self._redirect(f"{base}/review")
                intake_service.save(ws, intake)
                return self._redirect(base)
            if action == "edit":
                intake.edit(str(form.get("step", "")))
                intake_service.save(ws, intake)
                return self._redirect(base)
            if action == "evidence":
                back = f"{base}/review" if form.get("back") == "review" else base
                f = form.get("file")
                if not isinstance(f, dict) or not f.get("data"):
                    app.flash.append(("err", "Choose a file to add."))
                    return self._redirect(back)
                intake_service.add_evidence(ws, intake, filename=f.get("filename") or "file", data=f["data"],
                                            category=str(form.get("category", "")),
                                            source=str(form.get("source", "")),
                                            date_text=str(form.get("date_text", "")),
                                            notes=str(form.get("notes", "")))
                app.flash.append(("ok", "File added and stored encrypted. The original is kept unchanged."))
                return self._redirect(back)
            if action == "delete":
                if str(form.get("confirm", "")).strip() != "DELETE":
                    app.flash.append(("err", "Type DELETE to confirm."))
                    return self._redirect(f"{base}/delete")
                intake_service.delete_matter(app.store, ws.client_id)
                app.flash.append(("ok", "The intake and its files were deleted."))
                return self._redirect("/")
        except IntakeError as exc:
            app.flash.append(("err", str(exc)))
            return self._redirect(base)
        except ValueError as exc:  # upload size limit
            app.flash.append(("err", str(exc)))
            return self._redirect(base)
        return self._send(404, pages.refused_page("Not found."))

    def _post_unlocked(self, path: str, form: dict):
        app = self.app
        if path == "/intake/new":
            if form.get("adult") != "yes":
                app.flash.append(("err", "Confirm you're an adult filling this out."))
                return self._redirect("/")
            nickname = str(form.get("nickname", "")).strip()[:80]
            ws, intake = intake_service.new_matter(app.store, nickname, synthetic=app.header.mode != "real")
            return self._redirect(f"/n/{ws.client_id}/{intake.matter_id}")
        if path.startswith("/n/"):
            return self._post_intake(path, form)
        if path == "/new":
            try:
                cid = _check_id(str(form.get("client_id", "")).strip(), "workspace label")
            except WorkspaceIsolationError:
                app.flash.append(("err", "Use letters, numbers and dashes for the workspace label."))
                return self._redirect("/")
            path_name = str(form.get("path_name", "family_law"))
            if path_name not in PATHS or form.get("adult") != "yes":
                app.flash.append(("err", "Choose an interview type and confirm the interviewee is an adult."))
                return self._redirect("/")
            case_id = str(form.get("case_id", "")).strip()[:80]
            interviewee = str(form.get("interviewee", "")).strip()[:120]
            if not case_id or not interviewee:
                app.flash.append(("err", "Enter a case reference and the interviewee's name."))
                return self._redirect("/")
            ws = app.store.workspace(cid)
            s, _notice = start_path(path_name, ws, case_id=case_id, interviewee=interviewee,
                                    interviewer="Laylaw Interviewer", purpose="Client intake interview",
                                    interviewee_is_adult=True)
            app.sessions[(cid, s.interview_id)] = s
            return self._redirect(f"/i/{cid}/{s.interview_id}")

        m = _PATH.match(path)
        if not m or not m.group(4) and m.group(1) != "d":
            return self._send(404, pages.refused_page("Not found."))
        kind, cid, sid, action = m.group(1), m.group(2), m.group(3), (m.group(4) or "")[1:]
        s = app.session(cid, sid)
        back = f"/i/{cid}/{sid}"
        audit, ws_ref, s_ref = app.store.audit, app.store.ref(cid), app.store.ref(sid)

        if kind == "d":
            if str(form.get("confirm", "")).strip() != "DELETE":
                app.flash.append(("err", "Type DELETE to confirm."))
                return self._redirect(f"/d/{cid}/{sid}")
            app.store.existing_workspace(cid).delete_session(sid)
            app.sessions.pop((cid, sid), None)
            app.flash.append(("ok", "The interview and its documents were deleted."))
            return self._redirect("/")
        if kind != "i":
            return self._send(404, pages.refused_page("Not found."))
        if action == "answer":
            choice = form.get("action", "answer")
            if choice == "save_later":
                s.save_and_finish_later()
                audit.append("session_saved_for_later", ws=ws_ref, session=s_ref)
                app.sessions.pop((cid, sid), None)
                app.flash.append(("ok", "Saved. When you come back, you'll pick up at the same question."))
                return self._redirect("/")
            if choice == "skip":
                s.skip()
            elif choice == "not_sure":
                s.not_sure()
            else:
                text = str(form.get("answer", "")).strip()
                if not text:
                    app.flash.append(("err", "Type an answer, or choose Skip or Not sure."))
                    return self._redirect(back)
                if s.pending is None:
                    s.next_question()
                s.answer(text)
            return self._redirect(back)
        if action == "resume":
            s.resume()
            audit.append("session_resumed", ws=ws_ref, session=s_ref)
            return self._redirect(back)
        if action == "confirm":
            s.confirm_workspace()
            return self._redirect(back)
        if action == "upload":
            f = form.get("file")
            if not isinstance(f, dict) or not f.get("data"):
                app.flash.append(("err", "Choose a file to upload."))
                return self._redirect(back)
            label = str(form.get("label", "")).strip()[:120] or None
            s.add_upload(f.get("filename") or "upload", f["data"], label=label)
            app.flash.append(("ok", "Document stored (encrypted)."))
            return self._redirect(back)
        return self._send(404, pages.refused_page("Not found."))


def make_server(app: LaylawApp, host: str = "127.0.0.1", port: int = 0) -> HTTPServer:
    if host not in LOOPBACK:
        raise ValueError("Laylaw only listens on this computer (127.0.0.1); other addresses are refused")
    handler = type("LaylawHandler", (Handler,), {"app": app})
    server = HTTPServer((host if host != "localhost" else "127.0.0.1", port), handler)
    app.port = server.server_address[1]
    return server


def launch_url(app: LaylawApp) -> str:
    return f"http://127.0.0.1:{app.port}/start?t={app.launch_token}"


def run(root: str | Path, secret_store: SecretStore, *, port: int = 0, open_browser: bool = True) -> None:
    app = LaylawApp(root, secret_store)
    server = make_server(app, port=port)
    url = launch_url(app)
    audit = app.gate._audit()
    if audit is not None:
        audit.append("app_started", detail={"mode": app.header.mode})
    print("Laylaw is running on this computer only.")
    print("If your browser didn't open, paste this link into it (it works once):")
    print(url)
    print("Close Laylaw with the 'Lock and close' button, or press Ctrl+C here.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with app.lock:
            app.lock_vault("closed")
        server.server_close()
        if audit is not None:
            audit.append("app_stopped")

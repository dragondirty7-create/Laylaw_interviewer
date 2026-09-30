"""Laylaw web app: authenticated, per-client interview UI.

Security model (see SECURITY.md):
- Accounts are created by an operator with ``python -m laylaw.web.admin``; there is no sign-up.
- Sign-in creates a server-side session. The browser holds only an opaque random
  token in an HttpOnly, Secure, SameSite=Strict cookie. No case data, ids or
  tokens are placed in localStorage/sessionStorage.
- Every data access uses the client id from the server-side session row. No
  route accepts a client id from the request. Interview and upload ids that are
  not in the caller's own workspace get the same 404 as ids that don't exist.
- All state-changing requests need a CSRF token and a same-origin Origin header.
- Errors and logs name events and exception *types* only -- never answer text,
  filenames, document content, tokens, or keys.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
from functools import wraps
from pathlib import Path
from urllib.parse import quote, urlsplit

from io import BytesIO

from flask import (
    Flask, Request, Response, abort, g, jsonify, redirect, render_template, request, url_for,
)
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from laylaw.interviewer import SessionStatus, WorkspaceIsolationError, paths
from laylaw.interviewer.session import SAVED_FOR_LATER

from .accounts import Accounts
from .crypto import load_master_key
from .secure_store import EncryptedStore

log = logging.getLogger("laylaw.web")

INTERVIEW_ID_RE = re.compile(r"^INT-[0-9a-f]{10}$")
RECORD_ID_RE = re.compile(r"^R-[0-9a-f]{20}$")
MAX_ANSWER_CHARS = 20_000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES_PER_REQUEST = 20
ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "heic", "heif", "gif", "webp", "txt", "rtf", "doc", "docx",
    "odt", "csv", "xls", "xlsx", "eml", "msg", "mp3", "m4a", "wav", "mp4", "mov",
}
PATH_LABELS = {"family_law": "Family law", "criminal_defense": "Criminal defense"}


class InMemoryRequest(Request):
    """Uploaded files stay in memory. Werkzeug's default spools uploads over 500 KB to
    plaintext temp files on disk; for client documents that would defeat encryption at
    rest. The request size cap (MAX_CONTENT_LENGTH) bounds the memory used."""

    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return BytesIO()


class LaylawFlask(Flask):
    request_class = InMemoryRequest

    def log_exception(self, exc_info):  # never write exception messages/tracebacks (may hold data)
        etype = exc_info[0].__name__ if exc_info and exc_info[0] else "Exception"
        log.error("unhandled_error type=%s endpoint=%s", etype, request.endpoint)


def _config(overrides: dict | None) -> dict:
    env = os.environ
    cfg = {
        "DATA_DIR": env.get("LAYLAW_DATA_DIR", ""),
        "MASTER_KEY": env.get("LAYLAW_MASTER_KEY", ""),
        "COOKIE_SECURE": env.get("LAYLAW_COOKIE_SECURE", "1") != "0",
        "TRUST_PROXY": env.get("LAYLAW_TRUST_PROXY", "0") == "1",
    }
    cfg.update(overrides or {})
    if not cfg["DATA_DIR"]:
        raise RuntimeError("LAYLAW_DATA_DIR is not set; refusing to start")
    return cfg


def create_app(overrides: dict | None = None) -> Flask:
    cfg = _config(overrides)
    master = load_master_key(cfg["MASTER_KEY"])          # raises -> app does not start

    app = LaylawFlask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_FILE_BYTES * 5 + 1024 * 1024,
        SECRET_KEY=secrets.token_bytes(32),    # Flask's own cookie session is never used
        SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
        TEMPLATES_AUTO_RELOAD=False, PROPAGATE_EXCEPTIONS=False,
    )
    if cfg["TRUST_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    data_dir = Path(cfg["DATA_DIR"]).resolve()
    store = EncryptedStore(data_dir / "vault", master)
    accounts = Accounts(data_dir / "accounts.sqlite3", clock=cfg.get("CLOCK") or __import__("time").time)
    app.extensions["laylaw"] = {"store": store, "accounts": accounts}

    secure = cfg["COOKIE_SECURE"]
    cookie_name = "__Host-laylaw" if secure else "laylaw_session"
    pre_name = "__Host-laylaw-pre" if secure else "laylaw_pre"
    locks: dict[str, threading.Lock] = {}
    locks_guard = threading.Lock()

    def client_lock(client_id: str) -> threading.Lock:
        with locks_guard:
            return locks.setdefault(client_id, threading.Lock())

    # ------------------------------------------------------------- request hooks
    @app.before_request
    def _load_auth():
        g.auth = accounts.session(request.cookies.get(cookie_name))
        g.clear_cookie = bool(request.cookies.get(cookie_name)) and g.auth is None
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin != "null":
                o, h = urlsplit(origin), urlsplit(request.host_url)
                if (o.scheme, o.netloc) != (h.scheme, h.netloc):
                    log.warning("origin_rejected endpoint=%s", request.endpoint)
                    abort(403)
            elif origin == "null":
                abort(403)

    @app.after_request
    def _headers(resp: Response):
        h = resp.headers
        h["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if not request.path.startswith("/static/"):
            h["Cache-Control"] = "no-store"
            h["Pragma"] = "no-cache"
        if secure:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if getattr(g, "clear_cookie", False):
            resp.delete_cookie(cookie_name, path="/", secure=secure, httponly=True, samesite="Strict")
        return resp

    @app.context_processor
    def _ctx():
        return {"csrf": g.auth.csrf if getattr(g, "auth", None) else "", "signed_in": bool(getattr(g, "auth", None))}

    # ------------------------------------------------------------- helpers
    def login_required(api: bool = False):
        def deco(fn):
            @wraps(fn)
            def inner(*a, **kw):
                if g.auth is None:
                    if api:
                        return jsonify({"error": "not signed in"}), 401
                    return redirect(url_for("login", expired=1 if g.clear_cookie else None))
                g.ws = store.workspace(g.auth.client_id)
                return fn(*a, **kw)
            return inner
        return deco

    def check_csrf():
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if not g.auth or not hmac.compare_digest(sent.encode(), g.auth.csrf.encode()):
            log.warning("csrf_rejected endpoint=%s", request.endpoint)
            abort(403)

    def own_interview(iid: str):
        """Load an interview from the caller's own workspace, or 404. Never 403: a
        different client's id must look exactly like an id that doesn't exist."""
        if not isinstance(iid, str) or not INTERVIEW_ID_RE.match(iid) or not g.ws.has_session(iid):
            abort(404)
        try:
            return g.ws.load_session(iid)
        except (WorkspaceIsolationError, FileNotFoundError):
            log.warning("interview_access_denied")
            abort(404)

    def question_token(session) -> str:
        """Binds a submitted answer to the exact question on screen (stale tabs are refused)."""
        basis = f"{session.interview_id}|{len(session.turns)}|{session.pending.text if session.pending else ''}"
        return hmac.new(g.auth.csrf.encode(), basis.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def display_name() -> str:
        return g.ws.load_profile().get("display_name") or "there"

    def summarize(session) -> dict:
        return {
            "id": session.interview_id, "path": PATH_LABELS.get(session.path_name, session.path_name),
            "status": session.status.value, "section": session.current_section or "",
            "updated": session.last_updated[:16].replace("T", " "), "uploads": len(session.records),
        }

    # ------------------------------------------------------------- auth pages
    @app.get("/")
    def index():
        return redirect(url_for("home") if g.auth else url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            if g.auth:
                return redirect(url_for("home"))
            pre = secrets.token_urlsafe(24)
            resp = Response(render_template("login.html", pre=pre, expired=request.args.get("expired"),
                                            error=None))
            resp.set_cookie(pre_name, pre, max_age=900, secure=secure, httponly=True, samesite="Strict", path="/")
            return resp
        pre_cookie = request.cookies.get(pre_name, "")
        if not pre_cookie or not hmac.compare_digest(pre_cookie.encode(), request.form.get("pre", "").encode()):
            abort(403)
        result = accounts.authenticate(request.form.get("username", ""), request.form.get("password", ""),
                                       ip=request.remote_addr)
        if result is None:
            pre = secrets.token_urlsafe(24)
            resp = Response(render_template("login.html", pre=pre, expired=None,
                                            error="That username and password didn't work."), status=401)
            resp.set_cookie(pre_name, pre, max_age=900, secure=secure, httponly=True, samesite="Strict", path="/")
            return resp
        token, _ = result
        resp = redirect(url_for("home"))
        resp.set_cookie(cookie_name, token, secure=secure, httponly=True, samesite="Strict", path="/")
        resp.delete_cookie(pre_name, path="/", secure=secure, httponly=True, samesite="Strict")
        g.clear_cookie = False
        return resp

    @app.post("/logout")
    def logout():
        if g.auth:
            check_csrf()
            accounts.logout(g.auth)
        resp = redirect(url_for("login", signed_out=1))
        resp.delete_cookie(cookie_name, path="/", secure=secure, httponly=True, samesite="Strict")
        return resp

    # ------------------------------------------------------------- home
    @app.get("/home")
    @login_required()
    def home():
        items = []
        for iid in g.ws.list_sessions():
            try:
                items.append(summarize(g.ws.load_session(iid)))
            except (WorkspaceIsolationError, FileNotFoundError, KeyError, ValueError):
                log.warning("interview_unreadable")
        items.sort(key=lambda x: x["updated"], reverse=True)
        return render_template("home.html", name=display_name(), interviews=items, paths=PATH_LABELS,
                               notice=paths.CRIMINAL_DEFENSE_NOTICE, flash=request.args.get("m"))

    @app.post("/interviews")
    @login_required()
    def start_interview():
        check_csrf()
        path_name = request.form.get("path", "")
        if path_name not in PATH_LABELS:
            abort(400)
        if request.form.get("adult") != "yes":
            return render_template("message.html", title="We can't start this interview",
                                   body="Laylaw interviews adults only. Please confirm you are 18 or older."), 400
        profile = g.ws.load_profile()
        with client_lock(g.auth.client_id):
            session, _notice = paths.start_path(
                path_name, g.ws, case_id=profile.get("case_id") or "CASE-" + secrets.token_hex(4).upper(),
                interviewee=profile.get("display_name") or "the interviewee",
                interviewer="Laylaw Interviewer", purpose="Client intake interview",
                interviewee_is_adult=True)
        accounts.audit("interview_started", g.auth.user_id, g.auth.client_id, session.interview_id)
        return redirect(url_for("interview", iid=session.interview_id))

    # ------------------------------------------------------------- interview
    @app.get("/interviews/<iid>")
    @login_required()
    def interview(iid):
        with client_lock(g.auth.client_id):
            session = own_interview(iid)
            if session.status == SessionStatus.PAUSED and session.workspace_confirmed is not False:
                return render_template("resume.html", s=summarize(session), prompt=session.resume_prompt())
            cached = g.ws.load_prompt(iid) if session.workspace_confirmed is not False else None
            if session.pending is not None and cached and cached[0] == session.pending.text:
                question = cached[1]
            else:
                question = session.next_question()       # saves the pending question
                if question is not None and session.pending is not None:
                    g.ws.save_prompt(iid, session.pending.text, question)
            draft = g.ws.load_draft(iid)
            records = [{"id": r.id, "name": r.filename or r.label} for r in session.records]
            blocked = question is None and session.status != SessionStatus.CLOSED
            return render_template(
                "interview.html", s=summarize(session), question=question, draft=draft, records=records,
                qtoken=question_token(session) if question else "",
                safety=session.status == SessionStatus.PAUSED_FOR_SAFETY, blocked=blocked,
                done=session.status == SessionStatus.CLOSED, flash=request.args.get("m"),
                max_mb=MAX_FILE_BYTES // (1024 * 1024), exts=", ".join(sorted(ALLOWED_EXTENSIONS)))

    @app.post("/interviews/<iid>/resume")
    @login_required()
    def resume(iid):
        check_csrf()
        with client_lock(g.auth.client_id):
            session = own_interview(iid)
            session.resume()
        accounts.audit("interview_resumed", g.auth.user_id, g.auth.client_id, iid)
        return redirect(url_for("interview", iid=iid))

    @app.post("/interviews/<iid>/answer")
    @login_required()
    def answer(iid):
        check_csrf()
        action = request.form.get("action", "answer")
        with client_lock(g.auth.client_id):
            session = own_interview(iid)
            if session.pending is None or not hmac.compare_digest(
                    request.form.get("qtoken", "").encode(), question_token(session).encode()):
                return redirect(url_for("interview", iid=iid, m="stale"))
            msg = None
            if action == "skip":
                session.skip()
            elif action == "not_sure":
                session.not_sure()
            elif action == "later":
                # Keep whatever they had typed as the draft, so it is there when they come back.
                unsent = (request.form.get("answer") or "")[:MAX_ANSWER_CHARS]
                session.save_and_finish_later()
                if unsent.strip():
                    g.ws.save_draft(iid, unsent)
                g.ws.clear_prompt(iid)
                accounts.audit("interview_saved_for_later", g.auth.user_id, g.auth.client_id, iid)
                return redirect(url_for("home", m="saved"))
            elif action == "answer":
                text = (request.form.get("answer") or "").strip()
                if not text:
                    return redirect(url_for("interview", iid=iid, m="empty"))
                if len(text) > MAX_ANSWER_CHARS:
                    abort(413)
                result = session.answer(text)
                if result == SAVED_FOR_LATER:
                    msg = "later"
            else:
                abort(400)
            g.ws.clear_draft(iid)
            g.ws.clear_prompt(iid)
        accounts.audit("answer_saved", g.auth.user_id, g.auth.client_id, iid)
        if msg == "later":
            return redirect(url_for("home", m="saved"))
        return redirect(url_for("interview", iid=iid))

    @app.post("/interviews/<iid>/draft")
    @login_required(api=True)
    def save_draft(iid):
        check_csrf()
        if not INTERVIEW_ID_RE.match(iid) or not g.ws.has_session(iid):
            return jsonify({"error": "not found"}), 404
        body = request.get_json(silent=True) or {}
        text = body.get("text", "")
        if not isinstance(text, str) or len(text) > MAX_ANSWER_CHARS:
            return jsonify({"error": "invalid"}), 400
        if text.strip():
            g.ws.save_draft(iid, text)
        else:
            g.ws.clear_draft(iid)
        return jsonify({"saved": True})

    # ------------------------------------------------------------- uploads
    @app.post("/interviews/<iid>/uploads")
    @login_required()
    def upload(iid):
        check_csrf()
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            return redirect(url_for("interview", iid=iid, m="nofiles"))
        if len(files) > MAX_FILES_PER_REQUEST:
            abort(413)
        accepted, rejected = 0, 0
        with client_lock(g.auth.client_id):
            session = own_interview(iid)
            for f in files:
                name = f.filename or ""
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                data = f.read(MAX_FILE_BYTES + 1)
                if ext not in ALLOWED_EXTENSIONS or not data or len(data) > MAX_FILE_BYTES:
                    rejected += 1
                    continue
                rec = session.add_upload(name, data)
                accepted += 1
                accounts.audit("upload_stored", g.auth.user_id, g.auth.client_id, f"{iid}/{rec.id}")
        return redirect(url_for("interview", iid=iid, m=f"up{accepted}-{rejected}"))

    @app.get("/interviews/<iid>/uploads/<rid>")
    @login_required()
    def download(iid, rid):
        if not isinstance(rid, str) or not RECORD_ID_RE.match(rid):
            abort(404)
        with client_lock(g.auth.client_id):
            session = own_interview(iid)
            rec = next((r for r in session.records if r.id == rid), None)
            if rec is None:
                abort(404)
            try:
                data = g.ws.read_upload(rec)
            except (WorkspaceIsolationError, FileNotFoundError):
                log.warning("upload_access_denied")
                abort(404)
        accounts.audit("upload_downloaded", g.auth.user_id, g.auth.client_id, f"{iid}/{rid}")
        fname = rec.filename or "document"
        ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", fname)[:120] or "document"
        resp = Response(data, mimetype="application/octet-stream")
        resp.headers["Content-Disposition"] = (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}")
        resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return resp

    # ------------------------------------------------------------- errors
    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_e):
        return render_template("message.html", title="That was too large",
                               body=f"Each file can be up to {MAX_FILE_BYTES // (1024 * 1024)} MB. "
                                    "Try fewer files at once."), 413

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        titles = {400: "Something wasn't right with that request", 401: "Please sign in",
                  403: "That action wasn't allowed", 404: "Not found", 405: "Not allowed"}
        return render_template("message.html", title=titles.get(e.code, "Error"),
                               body="If this keeps happening, sign out and sign back in."), e.code

    @app.errorhandler(Exception)
    def server_error(e: Exception):
        log.error("server_error type=%s endpoint=%s", type(e).__name__, request.endpoint)
        return render_template("message.html", title="Something went wrong",
                               body="Nothing you already saved was lost. Please go back and try again."), 500

    return app

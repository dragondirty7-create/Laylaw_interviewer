"""Accounts, sign-in sessions, lockout and audit log (SQLite, stdlib only).

What this database holds: usernames, scrypt password hashes, the opaque client
id each account may access, hashed session tokens, failed-login timestamps, and
an audit trail of *events* (ids and event names only). It holds no case facts,
no display names, no filenames and no document content.

Authorization model: one account -> exactly one client workspace. The client id
used for every data access comes from the server-side session row, never from
the request.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .secure_store import CLIENT_ID_RE, _mkdir_private

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MIN_PASSWORD_LEN = 12
IDLE_TIMEOUT = 30 * 60            # seconds of inactivity before a session ends
ABSOLUTE_TIMEOUT = 12 * 60 * 60   # hard cap on a session's life
LOCKOUT_WINDOW = 15 * 60
LOCKOUT_THRESHOLD = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_hash TEXT NOT NULL,
  client_id TEXT NOT NULL UNIQUE,
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS web_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  csrf TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_failures (username TEXT NOT NULL, ip TEXT, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  ts REAL NOT NULL, event TEXT NOT NULL, user_id INTEGER, client_id TEXT, ref TEXT
);
"""


class PasswordPolicyError(ValueError):
    pass


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LEN:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                        maxmem=128 * 1024 * 1024, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r),
                              p=int(p), maxmem=128 * 1024 * 1024, dklen=len(dk) // 2)
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH: Optional[str] = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(16))
    return _DUMMY_HASH


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    user_id: int
    username: str
    client_id: str
    csrf: str
    token_hash: str


class Accounts:
    def __init__(self, db_path: str | os.PathLike, clock=time.time):
        self.path = Path(db_path)
        _mkdir_private(self.path.parent)
        self.clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(self.path) + suffix)
            if f.exists():
                os.chmod(f, 0o600)

    def _q(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def audit(self, event: str, user_id: Optional[int] = None, client_id: Optional[str] = None,
              ref: Optional[str] = None) -> None:
        """Audit rows carry event names and opaque ids only -- never content."""
        self._q("INSERT INTO audit VALUES (?,?,?,?,?)", (self.clock(), event, user_id, client_id, ref))

    # -- user admin (CLI only; there is no public sign-up) ----------------
    def create_user(self, username: str, password: str, client_id: str) -> int:
        if not CLIENT_ID_RE.match(client_id):
            raise ValueError("invalid client id")
        username = username.strip()
        if not username or len(username) > 128:
            raise ValueError("invalid username")
        pw = hash_password(password)
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO users(username, pw_hash, client_id, created_at) VALUES (?,?,?,?)",
                (username, pw, client_id, self.clock()))
            uid = cur.lastrowid
        self.audit("user_created", uid, client_id)
        return uid

    def set_password(self, username: str, password: str) -> None:
        pw = hash_password(password)
        rows = self._q("SELECT id, client_id FROM users WHERE username=?", (username,))
        if not rows:
            raise KeyError("no such user")
        self._q("UPDATE users SET pw_hash=? WHERE id=?", (pw, rows[0][0]))
        self.revoke_user_sessions(rows[0][0])
        self.audit("password_reset", rows[0][0], rows[0][1])

    def set_disabled(self, username: str, disabled: bool) -> None:
        rows = self._q("SELECT id, client_id FROM users WHERE username=?", (username,))
        if not rows:
            raise KeyError("no such user")
        self._q("UPDATE users SET disabled=? WHERE id=?", (1 if disabled else 0, rows[0][0]))
        if disabled:
            self.revoke_user_sessions(rows[0][0])
        self.audit("user_disabled" if disabled else "user_enabled", rows[0][0], rows[0][1])

    def revoke_user_sessions(self, user_id: int) -> None:
        self._q("DELETE FROM web_sessions WHERE user_id=?", (user_id,))

    def list_users(self) -> list[tuple]:
        return self._q("SELECT id, username, client_id, disabled FROM users ORDER BY id")

    # -- sign in ----------------------------------------------------------
    def _locked(self, username: str, ip: Optional[str]) -> bool:
        since = self.clock() - LOCKOUT_WINDOW
        n_user = self._q("SELECT COUNT(*) FROM login_failures WHERE username=? COLLATE NOCASE AND ts>?",
                         (username, since))[0][0]
        n_ip = self._q("SELECT COUNT(*) FROM login_failures WHERE ip=? AND ts>?", (ip, since))[0][0] if ip else 0
        return n_user >= LOCKOUT_THRESHOLD or n_ip >= LOCKOUT_THRESHOLD * 4

    def authenticate(self, username: str, password: str, ip: Optional[str] = None) -> Optional[tuple[str, AuthContext]]:
        """Returns (raw session token, context) or None. Same response for every failure."""
        username = (username or "").strip()[:128]
        if self._locked(username, ip):
            _ = verify_password(password or "", _dummy_hash())   # keep timing uniform
            self.audit("login_locked")
            return None
        rows = self._q("SELECT id, pw_hash, client_id, disabled FROM users WHERE username=?", (username,))
        ok = False
        if rows:
            ok = verify_password(password or "", rows[0][1]) and not rows[0][3]
        else:
            verify_password(password or "", _dummy_hash())
        if not ok:
            self._q("INSERT INTO login_failures VALUES (?,?,?)", (username, ip, self.clock()))
            self.audit("login_failed", rows[0][0] if rows else None)
            return None
        uid, _, client_id, _ = rows[0]
        self._q("DELETE FROM login_failures WHERE username=? COLLATE NOCASE", (username,))
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = self.clock()
        th = _token_hash(token)
        self._q("INSERT INTO web_sessions VALUES (?,?,?,?,?)", (th, uid, csrf, now, now))
        self.audit("login", uid, client_id)
        return token, AuthContext(uid, username, client_id, csrf, th)

    def session(self, token: Optional[str]) -> Optional[AuthContext]:
        """Validate a session token. Expired, revoked, or disabled -> None (and the row is removed)."""
        if not token or len(token) > 128:
            return None
        th = _token_hash(token)
        rows = self._q(
            "SELECT s.user_id, u.username, u.client_id, s.csrf, s.created_at, s.last_seen, u.disabled "
            "FROM web_sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", (th,))
        if not rows:
            return None
        uid, username, client_id, csrf, created, last_seen, disabled = rows[0]
        now = self.clock()
        if disabled or now - last_seen > IDLE_TIMEOUT or now - created > ABSOLUTE_TIMEOUT:
            self._q("DELETE FROM web_sessions WHERE token_hash=?", (th,))
            self.audit("session_expired", uid, client_id)
            return None
        if not CLIENT_ID_RE.match(client_id or ""):
            return None                                   # fail closed on a corrupt mapping
        self._q("UPDATE web_sessions SET last_seen=? WHERE token_hash=?", (now, th))
        return AuthContext(uid, username, client_id, csrf, th)

    def logout(self, ctx: AuthContext) -> None:
        self._q("DELETE FROM web_sessions WHERE token_hash=?", (ctx.token_hash,))
        self.audit("logout", ctx.user_id, ctx.client_id)

    def close(self) -> None:
        with self._lock:
            self._db.close()

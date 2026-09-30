"""Operator CLI. There is no public sign-up; accounts are created here.

    python -m laylaw.web.admin generate-key            # print a new LAYLAW_MASTER_KEY (store it in your secret manager)
    python -m laylaw.web.admin create-user USERNAME --display-name "First name"
    python -m laylaw.web.admin reset-password USERNAME
    python -m laylaw.web.admin disable-user USERNAME | enable-user USERNAME
    python -m laylaw.web.admin revoke-sessions USERNAME
    python -m laylaw.web.admin list-users
    python -m laylaw.web.admin confirm-workspace USERNAME INTERVIEW_ID   # after the client answered "no"/"not sure"

Passwords are read with getpass (never from argv, which lands in shell history).
LAYLAW_DATA_DIR and LAYLAW_MASTER_KEY must be set in the environment.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .accounts import Accounts, PasswordPolicyError
from .crypto import generate_master_key, load_master_key
from .secure_store import EncryptedStore, new_client_id


def _env():
    data = os.environ.get("LAYLAW_DATA_DIR")
    if not data:
        sys.exit("LAYLAW_DATA_DIR is not set")
    master = load_master_key(os.environ.get("LAYLAW_MASTER_KEY"))
    root = Path(data).resolve()
    return Accounts(root / "accounts.sqlite3"), EncryptedStore(root / "vault", master)


def _password() -> str:
    pw = getpass.getpass("New password (12+ characters): ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords did not match")
    return pw


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="laylaw.web.admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate-key")
    c = sub.add_parser("create-user")
    c.add_argument("username")
    c.add_argument("--display-name", required=True, help="how the interview addresses the person")
    c.add_argument("--case-id", default=None, help="optional case label (no real case numbers in logs)")
    for name in ("reset-password", "disable-user", "enable-user", "revoke-sessions"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("list-users")
    cw = sub.add_parser("confirm-workspace")
    cw.add_argument("username")
    cw.add_argument("interview_id")
    a = p.parse_args(argv)

    if a.cmd == "generate-key":
        print(generate_master_key())
        return 0
    accounts, store = _env()
    try:
        if a.cmd == "create-user":
            client_id = new_client_id()
            accounts.create_user(a.username, _password(), client_id)
            profile = {"display_name": a.display_name}
            if a.case_id:
                profile["case_id"] = a.case_id
            store.workspace(client_id).save_profile(profile)
            print(f"Created {a.username} -> workspace {client_id}")
        elif a.cmd == "reset-password":
            accounts.set_password(a.username, _password())
            print("Password reset; existing sessions signed out")
        elif a.cmd in ("disable-user", "enable-user"):
            accounts.set_disabled(a.username, a.cmd == "disable-user")
            print("Done")
        elif a.cmd == "revoke-sessions":
            uid = next((u[0] for u in accounts.list_users() if u[1].lower() == a.username.lower()), None)
            if uid is None:
                sys.exit("no such user")
            accounts.revoke_user_sessions(uid)
            print("Sessions revoked")
        elif a.cmd == "confirm-workspace":
            client_id = next((u[2] for u in accounts.list_users() if u[1].lower() == a.username.lower()), None)
            if client_id is None:
                sys.exit("no such user")
            ws = store.workspace(client_id)
            session = ws.load_session(a.interview_id)
            session.confirm_workspace()
            accounts.audit("workspace_confirmed_by_operator", None, client_id, a.interview_id)
            print("Workspace confirmed; the interview can continue")
        elif a.cmd == "list-users":
            for uid, username, client_id, disabled in accounts.list_users():
                print(f"{uid}\t{username}\t{client_id}\t{'disabled' if disabled else 'active'}")
    except PasswordPolicyError as e:
        sys.exit(str(e))
    except KeyError:
        sys.exit("no such user")
    except FileNotFoundError:
        sys.exit("no such interview for that user")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

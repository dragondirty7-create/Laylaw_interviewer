"""Command line for the hardened single-user local mode.

    python -m laylaw init                 create the encrypted vault (once, on Chelsea's computer)
    python -m laylaw run                  start the local app and open it in the browser
    python -m laylaw doctor               check that everything required for real data is in place
    python -m laylaw recover              use the recovery code (new computer / forgotten passphrase)
    python -m laylaw change-passphrase
    python -m laylaw verify-audit         check the audit log's integrity
    python -m laylaw audit-archive        move a reviewed audit log aside and start a new one
    python -m laylaw delete-workspace --client LABEL

The vault folder defaults to the OS's per-user app data folder; set LAYLAW_VAULT
or pass --vault to use another location.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


def default_vault_dir() -> Path:
    if os.environ.get("LAYLAW_VAULT"):
        return Path(os.environ["LAYLAW_VAULT"])
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Laylaw" / "vault"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Laylaw" / "vault"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "laylaw" / "vault"


def _secret_store():
    from .secure.secrets_store import default_secret_store
    return default_secret_store()


def _new_passphrase(prompt: str = "Choose a passphrase (12+ characters): ") -> str:
    while True:
        first = getpass.getpass(prompt)
        if first != getpass.getpass("Type it again: "):
            print("Those didn't match. Try again.")
            continue
        return first


def cmd_init(args) -> int:
    from .secure.audit import AuditLog
    from .secure.vault import init_vault

    store = _secret_store()
    mode = "synthetic" if args.synthetic else "real"
    if mode == "real" and not store.is_os_protected:
        print(f"Can't create a real-data vault: the operating system credential store isn't available "
              f"(found: {store.name}). Nothing was created.")
        return 2
    print(f"Creating a {'SYNTHETIC (test data only)' if args.synthetic else 'real-data'} vault at {args.vault}")
    vault, code = init_vault(args.vault, _new_passphrase(), secret_store=store, mode=mode)
    AuditLog(args.vault, vault.meta()["audit_key"]).append("vault_created", detail={"mode": mode})
    vault.lock()
    print("\nRECOVERY CODE. Write this down on paper and keep it somewhere safe, away from this computer:\n")
    print("    " + code + "\n")
    print("It's the only way back in if the passphrase is forgotten or this computer is replaced.")
    print("Without the passphrase-and-this-computer, or this code, the interviews can't be recovered by anyone.")
    last = code.split("-")[-1]
    while input("To confirm you've saved it, type the LAST group of the code: ").strip().upper() != last:
        print("That doesn't match the last group. Check what you wrote down.")
    print("Vault ready. Start Laylaw with:  python -m laylaw run")
    return 0


def cmd_doctor(args) -> int:
    from .secure.mode import check_readiness

    r = check_readiness(args.vault, _secret_store())
    print(f"Vault: {args.vault}\nMode: {r.mode}")
    for p in r.problems:
        print(f"  PROBLEM: {p}")
    for w in r.warnings:
        print(f"  note: {w}")
    print("Ready for real case data." if r.ok and r.mode == "real" else
          "Ready (synthetic vault: test data only)." if r.ok else "NOT ready. Laylaw will refuse to open this vault.")
    return 0 if r.ok else 2


def cmd_run(args) -> int:
    from .app.server import run
    from .secure.mode import check_readiness

    store = _secret_store()
    r = check_readiness(args.vault, store)
    if not r.ok:
        print("Laylaw won't start because something required for protecting case data is missing:")
        for p in r.problems:
            print(f"  - {p}")
        return 2
    run(args.vault, store, port=args.port, open_browser=not args.no_browser)
    return 0


def _audit_log(args):
    from .secure.audit import AuditLog
    from .secure.vault import audit_key_for
    return AuditLog(args.vault, audit_key_for(args.vault, _secret_store()))


def cmd_recover(args) -> int:
    from .secure.errors import AccessDenied
    from .secure.vault import recover

    code = getpass.getpass("Recovery code: ")
    store = _secret_store()
    try:
        vault = recover(args.vault, code, _new_passphrase("Choose a NEW passphrase (12+ characters): "),
                        secret_store=store)
    except AccessDenied as exc:
        try:
            _audit_log(args).append("recovery_failed")
        except Exception:
            pass
        print(exc)
        return 2
    _audit_log(args).append("recovery_used")
    vault.lock()
    print("Recovered. The new passphrase and this computer now open the vault; the recovery code still works.")
    return 0


def cmd_change_passphrase(args) -> int:
    from .secure.errors import AccessDenied
    from .secure.vault import unlock

    store = _secret_store()
    old = getpass.getpass("Current passphrase: ")
    try:
        vault = unlock(args.vault, old, secret_store=store)
        vault.change_passphrase(old, _new_passphrase("New passphrase (12+ characters): "))
    except AccessDenied as exc:
        _audit_log(args).append("unlock_failed", detail={"attempt": 1})
        print(exc)
        return 2
    _audit_log(args).append("passphrase_changed")
    vault.lock()
    print("Passphrase changed.")
    return 0


def cmd_verify_audit(args) -> int:
    from .secure.errors import AuditTamperError

    try:
        n = _audit_log(args).verify()
    except AuditTamperError as exc:
        print(f"AUDIT LOG FAILED VERIFICATION: {exc}")
        return 2
    print(f"Audit log verified: {n} entries, chain intact.")
    return 0


def _open(args):
    from .secure.mode import AccessGate
    return AccessGate(args.vault, _secret_store()).open(getpass.getpass("Passphrase: "))


def cmd_audit_archive(args) -> int:
    from .secure.audit import AuditLog
    from .secure.vault import unlock

    store = _secret_store()
    vault = unlock(args.vault, getpass.getpass("Passphrase: "), secret_store=store)  # proves authority
    dest = AuditLog(args.vault, vault.meta()["audit_key"]).archive()
    vault.lock()
    print(f"Audit log moved to {dest} for review; a new log has started.")
    return 0


def cmd_delete_workspace(args) -> int:
    store = _open(args)
    try:
        if input(f"Permanently delete workspace '{args.client}' and all its interviews and documents? "
                 f"Type DELETE: ").strip() != "DELETE":
            print("Nothing deleted.")
            return 1
        counts = store.delete_workspace(args.client)
        print(f"Deleted {counts['sessions']} interview(s) and {counts['uploads']} document(s).")
    finally:
        store.vault.lock()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="laylaw", description="Laylaw Interviewer: single-user secure local mode")
    p.add_argument("--vault", type=Path, default=default_vault_dir(), help="vault folder")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create the encrypted vault")
    s.add_argument("--synthetic", action="store_true", help="test/demo vault (relaxed checks, synthetic data only)")
    s.set_defaults(func=cmd_init)
    s = sub.add_parser("run", help="start the local app")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_run)
    for name, func in (("doctor", cmd_doctor), ("recover", cmd_recover), ("change-passphrase", cmd_change_passphrase),
                       ("verify-audit", cmd_verify_audit), ("audit-archive", cmd_audit_archive)):
        sub.add_parser(name).set_defaults(func=func)
    s = sub.add_parser("delete-workspace")
    s.add_argument("--client", required=True)
    s.set_defaults(func=cmd_delete_workspace)
    args = p.parse_args(argv)
    args.vault = args.vault.expanduser().resolve()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

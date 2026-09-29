"""Issue #2: encryption at rest, access gate, isolation, uploads, deletion, audit, real-data gate.

ALL DATA IS SYNTHETIC AND FICTIONAL.
"""
import json
import os
import stat

import pytest

from laylaw.interviewer import WorkspaceStore
from laylaw.interviewer.paths import start_path
from laylaw.interviewer.workspace import WorkspaceIsolationError
from laylaw.secure.audit import AuditLog
from laylaw.secure.errors import (AccessDenied, AuditTamperError, NotReadyForRealData, RealDataModeError,
                                  SecureStorageError)
from laylaw.secure.mode import AccessGate, check_readiness
from laylaw.secure.secrets_store import MemorySecretStore
from laylaw.secure.vault import MIN_REAL_SCRYPT_N, audit_key_for, init_vault, recover, unlock

PASS = "fictional passphrase 42"
MARKERS = [b"Jordan Avery", b"CASE-FICTIONAL-777", b"client-fictional-a", b"blue sedan", b"SYNTHETIC-UPLOAD-BYTES",
           b"custody_order_avery.pdf", b"Sam Rowe"]


class FakeOSStore(MemorySecretStore):
    """Stands in for the OS credential store in tests of the real-data gate."""
    name = "fake-os-store"
    is_os_protected = True


@pytest.fixture
def secrets_():
    return MemorySecretStore()


@pytest.fixture
def vault_dir(tmp_path, secrets_):
    root = tmp_path / "vault"
    v, code = init_vault(root, PASS, secret_store=secrets_, mode="synthetic", kdf_n=2 ** 12)
    AuditLog(root, v.meta()["audit_key"]).append("vault_created", detail={"mode": "synthetic"})
    v.lock()
    secrets_.recovery_code = code  # kept for the recovery test
    return root


@pytest.fixture
def store(vault_dir, secrets_):
    return AccessGate(vault_dir, secrets_).open(PASS)


def run_interview(ws, interviewee="Jordan Avery"):
    s, _ = start_path("family_law", ws, case_id="CASE-FICTIONAL-777", interviewee=interviewee,
                      interviewer="Laylaw Interviewer", purpose="synthetic", interviewee_is_adult=True)
    for answer in ["Yes", "No", "No", "No", "Help with the parenting schedule"]:
        s.next_question()
        s.answer(answer)
    s.next_question()
    s.answer("Last spring Sam Rowe picked up Pip in a blue sedan and was two hours late.")
    return s


def all_disk_bytes(root):
    for p in root.rglob("*"):
        if p.is_file():
            yield p, p.read_bytes()


# ------------------------------------------------------------------ at rest
def test_data_is_unreadable_at_rest(vault_dir, store):
    ws = store.workspace("client-fictional-a")
    s = run_interview(ws)
    s.add_upload("custody_order_avery.pdf", b"SYNTHETIC-UPLOAD-BYTES " * 50)
    for path, data in all_disk_bytes(vault_dir):
        for marker in MARKERS:
            assert marker not in data, f"{marker!r} readable in {path.name}"
            assert marker.decode() not in str(path), f"{marker!r} visible in a file name"
    data_files = list((vault_dir / "data").iterdir())
    assert data_files and all(p.read_bytes()[:4] == b"LLE1" for p in data_files)


def test_correct_passphrase_loads_and_resumes(vault_dir, secrets_, store):
    s = run_interview(store.workspace("client-fictional-a"))
    s.next_question()
    s.save_and_finish_later()
    pending = s.pending.text
    store.vault.lock()

    reopened = AccessGate(vault_dir, secrets_).open(PASS)
    s2 = reopened.workspace("client-fictional-a").load_session(s.interview_id)
    assert s2.to_dict()["facts"] == s.to_dict()["facts"]
    assert s2.pending.text == pending
    s2.resume()
    assert s2.next_question() == pending


def test_wrong_passphrase_fails_closed(vault_dir, secrets_):
    with pytest.raises(AccessDenied):
        AccessGate(vault_dir, secrets_).open("not the passphrase")


def test_missing_device_secret_fails_closed(vault_dir, secrets_):
    header_id = json.loads((vault_dir / "vault.json").read_text())["vault_id"]
    secrets_.delete(header_id)
    with pytest.raises(NotReadyForRealData):
        AccessGate(vault_dir, secrets_).open(PASS)
    with pytest.raises(AccessDenied):
        unlock(vault_dir, PASS, secret_store=secrets_)


def test_copied_folder_plus_passphrase_is_not_enough(vault_dir, secrets_, tmp_path):
    other_computer = MemorySecretStore()  # same files, different OS account / machine
    with pytest.raises(AccessDenied):
        unlock(vault_dir, PASS, secret_store=other_computer)


def test_locked_vault_refuses_access(store):
    ws = store.workspace("client-fictional-a")
    s = run_interview(ws)
    store.vault.lock()
    with pytest.raises(AccessDenied):
        ws.load_session(s.interview_id)


def test_repeated_failures_lock_out(vault_dir, secrets_):
    t = [1000.0]
    gate = AccessGate(vault_dir, secrets_, clock=lambda: t[0])
    for _ in range(AccessGate.MAX_FAILURES):
        with pytest.raises(AccessDenied):
            gate.open("wrong")
    with pytest.raises(AccessDenied, match="Too many"):
        gate.open(PASS)
    t[0] += AccessGate.LOCKOUT_S + 1
    assert gate.open(PASS) is not None


# ------------------------------------------------------------------ integrity
def test_tampered_file_fails_authentication(vault_dir, store):
    ws = store.workspace("client-fictional-a")
    s = run_interview(ws)
    path = store.vault.physical_path(f"ws/client-fictional-a/session/{s.interview_id}")
    blob = bytearray(path.read_bytes())
    blob[-5] ^= 0x01
    path.write_bytes(bytes(blob))
    with pytest.raises(SecureStorageError):
        ws.load_session(s.interview_id)


def test_swapped_file_between_workspaces_fails(store):
    a = store.workspace("client-fictional-a")
    b = store.workspace("client-fictional-b")
    sa = run_interview(a)
    sb = run_interview(b, interviewee="Casey Lin")
    pa = store.vault.physical_path(f"ws/client-fictional-a/session/{sa.interview_id}")
    pb = store.vault.physical_path(f"ws/client-fictional-b/session/{sb.interview_id}")
    pb.write_bytes(pa.read_bytes())  # try to plant A's session under B's name
    with pytest.raises(SecureStorageError):
        b.load_session(sb.interview_id)


# ------------------------------------------------------------------ isolation
def test_workspace_isolation_holds(store):
    a = store.workspace("client-fictional-a")
    b = store.workspace("client-fictional-b")
    sa = run_interview(a)
    with pytest.raises(FileNotFoundError):
        b.load_session(sa.interview_id)
    assert b.list_sessions() == []
    sa.workspace = b
    with pytest.raises(WorkspaceIsolationError):
        b.save_session(sa)
    rec = run_interview(a).add_upload("a.txt", b"SYNTHETIC-UPLOAD-BYTES")
    with pytest.raises(WorkspaceIsolationError):
        b.read_upload(rec)
    for bad in ("../client-fictional-a", "a/b", ""):
        with pytest.raises(WorkspaceIsolationError):
            store.workspace(bad)


# ------------------------------------------------------------------ uploads
def test_uploads_are_encrypted_and_round_trip(vault_dir, store):
    ws = store.workspace("client-fictional-a")
    s = run_interview(ws)
    payload = b"SYNTHETIC-UPLOAD-BYTES %PDF-1.4 fictional" * 100
    rec = s.add_upload("custody_order_avery.pdf", payload, label="Fictional order")
    assert rec.stored_path.startswith("vault:") and "custody" not in rec.stored_path
    assert ws.read_upload(rec) == payload
    for path, data in all_disk_bytes(vault_dir):
        assert payload[:30] not in data


# ------------------------------------------------------------------ deletion
def test_delete_session_removes_accessible_copy(vault_dir, store):
    ws = store.workspace("client-fictional-a")
    s = run_interview(ws)
    rec = s.add_upload("a.pdf", b"SYNTHETIC-UPLOAD-BYTES")
    keep = run_interview(ws, interviewee="Casey Lin")
    session_file = store.vault.physical_path(f"ws/client-fictional-a/session/{s.interview_id}")
    upload_file = store.vault.physical_path(f"ws/client-fictional-a/upload/{rec.id}")
    assert session_file.exists() and upload_file.exists()

    counts = ws.delete_session(s.interview_id)

    assert counts == {"uploads": 1}
    assert not session_file.exists() and not upload_file.exists()
    assert s.interview_id not in ws.list_sessions()
    with pytest.raises(FileNotFoundError):
        ws.load_session(s.interview_id)
    with pytest.raises(FileNotFoundError):
        ws.read_upload(rec)
    assert ws.load_session(keep.interview_id).interviewee == "Casey Lin"  # other interviews untouched


def test_delete_workspace(store):
    ws = store.workspace("client-fictional-a")
    run_interview(ws).add_upload("a.pdf", b"x")
    run_interview(ws)
    before = len(list((store.root / "data").iterdir()))
    counts = store.delete_workspace("client-fictional-a")
    assert counts == {"sessions": 2, "uploads": 1}
    assert "client-fictional-a" not in store.list_clients()
    assert len(list((store.root / "data").iterdir())) < before
    with pytest.raises(FileNotFoundError):
        store.existing_workspace("client-fictional-a")


# ------------------------------------------------------------------ audit
def test_audit_events_without_case_content(vault_dir, secrets_, store):
    ws = store.workspace("client-fictional-a")
    s = run_interview(ws)
    rec = s.add_upload("custody_order_avery.pdf", b"SYNTHETIC-UPLOAD-BYTES")
    ws.read_upload(rec)
    with pytest.raises(AccessDenied):
        AccessGate(vault_dir, secrets_).open("wrong")
    ws.delete_session(s.interview_id)
    with pytest.raises(RealDataModeError):
        store.export()

    log = (vault_dir / "audit.log").read_text()
    events = [json.loads(line)["event"] for line in log.splitlines()]
    for ev in ("vault_created", "unlock_ok", "session_created", "upload_stored", "upload_read",
               "unlock_failed", "session_deleted", "export_refused"):
        assert ev in events, ev
    for marker in MARKERS + [s.interview_id.encode()]:
        assert marker.decode() not in log
    assert AuditLog(vault_dir, audit_key_for(vault_dir, secrets_)).verify() == len(events)


def test_audit_refuses_content_in_details(vault_dir, secrets_):
    log = AuditLog(vault_dir, audit_key_for(vault_dir, secrets_))
    with pytest.raises(ValueError):
        log.append("session_save", detail={"note": "Sam Rowe was late"})
    with pytest.raises(ValueError):
        log.append("made_up_event")


@pytest.mark.parametrize("attack", ["edit", "delete_middle", "truncate", "remove_log"])
def test_audit_tampering_is_detected_and_blocks_real_use(vault_dir, secrets_, store, attack):
    run_interview(store.workspace("client-fictional-a"))
    path = vault_dir / "audit.log"
    lines = path.read_text().splitlines()
    if attack == "edit":
        entry = json.loads(lines[1])
        entry["event"] = "locked"
        lines[1] = json.dumps(entry, sort_keys=True)
        path.write_text("\n".join(lines) + "\n")
    elif attack == "delete_middle":
        path.write_text("\n".join(lines[:1] + lines[2:]) + "\n")
    elif attack == "truncate":
        path.write_text("\n".join(lines[:-1]) + "\n")
    else:
        path.unlink()
    with pytest.raises(AuditTamperError):
        AuditLog(vault_dir, audit_key_for(vault_dir, secrets_)).verify()
    assert not check_readiness(vault_dir, secrets_).ok
    with pytest.raises(NotReadyForRealData):
        AccessGate(vault_dir, secrets_).open(PASS)


# ------------------------------------------------------------------ recovery
def test_recovery_code_restores_access(vault_dir, secrets_, store):
    s = run_interview(store.workspace("client-fictional-a"))
    store.vault.lock()
    new_computer = MemorySecretStore()
    with pytest.raises(AccessDenied):
        recover(vault_dir, "LLRC-AAAA-AAAA", "new fictional passphrase", secret_store=new_computer)
    vault = recover(vault_dir, secrets_.recovery_code, "new fictional passphrase", secret_store=new_computer)
    vault.lock()
    reopened = AccessGate(vault_dir, new_computer).open("new fictional passphrase")
    assert reopened.workspace("client-fictional-a").load_session(s.interview_id).interviewee == "Jordan Avery"
    with pytest.raises(AccessDenied):
        unlock(vault_dir, PASS, secret_store=new_computer)


def test_change_passphrase(vault_dir, secrets_):
    v = unlock(vault_dir, PASS, secret_store=secrets_)
    with pytest.raises(AccessDenied):
        v.change_passphrase("wrong old", "another fictional passphrase")
    v.change_passphrase(PASS, "another fictional passphrase")
    with pytest.raises(AccessDenied):
        unlock(vault_dir, PASS, secret_store=secrets_)
    assert unlock(vault_dir, "another fictional passphrase", secret_store=secrets_)


# ------------------------------------------------------------------ real-data mode gate
@pytest.fixture
def real_vault(tmp_path):
    ss = FakeOSStore()
    root = tmp_path / "real"
    v, _ = init_vault(root, PASS, secret_store=ss, mode="real", kdf_n=MIN_REAL_SCRYPT_N)
    v.lock()
    return root, ss


def test_real_vault_opens_when_everything_is_in_place(real_vault):
    root, ss = real_vault
    r = check_readiness(root, ss)
    assert r.ok, r.problems
    assert AccessGate(root, ss).open(PASS).vault.mode == "real"


def test_real_mode_refuses_insecure_secret_store(real_vault):
    root, ss = real_vault
    plain = MemorySecretStore()
    plain._data = dict(ss._data)  # same secret, but not in an OS-protected store
    with pytest.raises(NotReadyForRealData, match="credential store"):
        AccessGate(root, plain).open(PASS)


def test_real_mode_refuses_weak_kdf(tmp_path):
    ss = FakeOSStore()
    v, _ = init_vault(tmp_path / "weak", PASS, secret_store=ss, mode="real", kdf_n=2 ** 12)
    v.lock()
    with pytest.raises(NotReadyForRealData, match="stretching"):
        AccessGate(tmp_path / "weak", ss).open(PASS)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission check")
def test_real_mode_refuses_shared_folder_permissions(real_vault):
    root, ss = real_vault
    os.chmod(root, 0o755)
    with pytest.raises(NotReadyForRealData, match="other accounts"):
        AccessGate(root, ss).open(PASS)
    os.chmod(root, 0o700)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert AccessGate(root, ss).open(PASS)


def test_real_mode_refuses_plaintext_files_in_vault(real_vault):
    root, ss = real_vault
    (root / "data" / "notes.txt").write_text("fictional plaintext")
    with pytest.raises(NotReadyForRealData, match="not encrypted"):
        AccessGate(root, ss).open(PASS)


def test_real_vault_requires_long_passphrase(tmp_path):
    with pytest.raises(Exception, match="at least"):
        init_vault(tmp_path / "v", "short", secret_store=FakeOSStore(), mode="real", kdf_n=MIN_REAL_SCRYPT_N)


def test_plaintext_store_refused_in_real_mode(tmp_path, monkeypatch, real_vault):
    root, _ = real_vault
    with pytest.raises(RealDataModeError):
        WorkspaceStore(root)  # never write plaintext into a vault folder
    monkeypatch.setenv("LAYLAW_MODE", "real")
    with pytest.raises(RealDataModeError):
        WorkspaceStore(tmp_path / "plain")


def test_init_refuses_non_empty_or_existing(tmp_path, vault_dir):
    with pytest.raises(Exception):
        init_vault(vault_dir, PASS, secret_store=MemorySecretStore(), mode="synthetic", kdf_n=2 ** 12)
    other = tmp_path / "busy"
    other.mkdir()
    (other / "something").write_text("x")
    with pytest.raises(Exception, match="not empty"):
        init_vault(other, PASS, secret_store=MemorySecretStore(), mode="synthetic", kdf_n=2 ** 12)

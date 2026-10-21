"""Shared fixtures. ALL DATA IS SYNTHETIC AND FICTIONAL.

No real person's case facts appear anywhere in this test suite. Names such as
"Jordan Avery", "Sam Rowe", "Casey Lin" and child "Pip" are invented.
"""
import os

import pytest

from laylaw.interviewer import InterviewSession, WorkspaceStore


class _EncryptedShim:
    """Runs the engine suite on the web layer's encrypted store (LAYLAW_TEST_STORE=encrypted).
    The suite's readable fictional client ids are mapped to valid opaque ids."""

    def __init__(self, root):
        import base64
        import hashlib

        from laylaw.web.crypto import generate_master_key
        from laylaw.web.secure_store import EncryptedStore
        self._store = EncryptedStore(root, base64.urlsafe_b64decode(generate_master_key()))
        self._hash = hashlib.sha256
        self._issued = set()

    def workspace(self, client_id):
        from laylaw.interviewer.workspace import _check_id
        if client_id in self._issued:               # a workspace's own (already opaque) id
            return self._store.workspace(client_id)
        _check_id(client_id, "client id")           # same validation as the plain store
        opaque = "c-" + self._hash(client_id.encode()).hexdigest()[:20]
        self._issued.add(opaque)
        return self._store.workspace(opaque)


@pytest.fixture
def store(tmp_path):
    if os.environ.get("LAYLAW_TEST_STORE") == "encrypted":
        return _EncryptedShim(tmp_path / "laylaw-enc")
    return WorkspaceStore(tmp_path / "laylaw-data")


@pytest.fixture
def ws(store):
    return store.workspace("client-fictional-a")


def new_session(ws, sections=("Specific incidents",), interviewee="Jordan Avery"):
    return InterviewSession.start(
        ws, case_id="CASE-FICTIONAL-001", interviewee=interviewee, interviewer="Laylaw Interviewer",
        purpose="Synthetic test interview", sections=list(sections), interviewee_is_adult=True)


@pytest.fixture
def session(ws):
    return new_session(ws)


def pytest_collection_modifyitems(config, items):
    # Under the encrypted store, a planted plaintext "<id>.json" is never read at all (the store only
    # opens authenticated "<id>.enc" objects), so this one layout-specific step does not apply. The
    # encrypted equivalent -- ciphertext copied between clients or renamed is refused -- is
    # test_web_security.py::test_ciphertext_is_bound_to_client_and_object.
    if os.environ.get("LAYLAW_TEST_STORE") != "encrypted":
        return
    for item in items:
        if item.name == "test_10_two_client_workspaces_cannot_read_or_overwrite_each_other":
            item.add_marker(pytest.mark.skip(reason="plaintext-layout forgery step; see test_web_security"))

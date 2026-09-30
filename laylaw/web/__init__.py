"""Laylaw web layer: authenticated, encrypted, per-client interview app.

The interview engine (``laylaw.interviewer``) is unchanged and stays stdlib-only.
This package adds the parts needed before real client data: accounts,
server-side sessions, encrypted storage, private uploads, and the UI.
Requires ``pip install -e .[web]`` (Flask, cryptography, waitress).
"""

"""Authenticated encryption for client data at rest.

- One master key, supplied only through the environment (``LAYLAW_MASTER_KEY``),
  never from source control or the data directory.
- Each client gets its own key, derived from the master key with HKDF and the
  client id. Client A's key cannot decrypt client B's objects.
- Every object is sealed with AES-256-GCM. The associated data binds the
  ciphertext to (client, kind, object id), so an object copied into another
  client's directory, or renamed to another id, fails to decrypt instead of
  being read as someone else's record.
"""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"LLE1"
_NONCE = 12
_SALT = b"laylaw-client-key-v1"


class KeyError_(RuntimeError):
    """The master key is missing or malformed. The app refuses to start."""


class DecryptionError(PermissionError):
    """Ciphertext did not authenticate for this client / object. Treated as access denied."""


def generate_master_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def load_master_key(value: str | None) -> bytes:
    if not value:
        raise KeyError_("LAYLAW_MASTER_KEY is not set; refusing to start without an encryption key")
    try:
        raw = base64.urlsafe_b64decode(value.strip().encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise KeyError_("LAYLAW_MASTER_KEY is not valid base64") from None
    if len(raw) != 32:
        raise KeyError_("LAYLAW_MASTER_KEY must decode to exactly 32 bytes")
    return raw


class ClientCipher:
    def __init__(self, master_key: bytes, client_id: str):
        self.client_id = client_id
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=_SALT,
                   info=b"client:" + client_id.encode("ascii")).derive(master_key)
        self._aead = AESGCM(key)

    def _aad(self, kind: str, object_id: str) -> bytes:
        return f"laylaw/v1|{self.client_id}|{kind}|{object_id}".encode("ascii")

    def seal(self, kind: str, object_id: str, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE)
        return MAGIC + nonce + self._aead.encrypt(nonce, plaintext, self._aad(kind, object_id))

    def open(self, kind: str, object_id: str, blob: bytes) -> bytes:
        if len(blob) < len(MAGIC) + _NONCE + 16 or not blob.startswith(MAGIC):
            raise DecryptionError("not a Laylaw encrypted object")
        nonce = blob[len(MAGIC):len(MAGIC) + _NONCE]
        try:
            return self._aead.decrypt(nonce, blob[len(MAGIC) + _NONCE:], self._aad(kind, object_id))
        except InvalidTag:
            raise DecryptionError("object does not authenticate for this client") from None

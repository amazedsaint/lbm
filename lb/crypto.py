from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from .keys import b64e, b64d


class CryptoError(Exception):
    pass


def hkdf_sha256(ikm: bytes, *, salt: bytes, info: bytes, length: int) -> bytes:
    hk = HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info)
    return hk.derive(ikm)


def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    if len(key) != 32:
        raise CryptoError("AEAD key must be 32 bytes")
    if len(nonce) != 12:
        raise CryptoError("AEAD nonce must be 12 bytes")
    return ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)


def aead_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    if len(key) != 32:
        raise CryptoError("AEAD key must be 32 bytes")
    if len(nonce) != 12:
        raise CryptoError("AEAD nonce must be 12 bytes")
    return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)


def seal_to_x25519(recipient_pub: X25519PublicKey, plaintext: bytes, *, context: bytes) -> dict:
    """Sealed box for small payloads.

    Generates an ephemeral X25519 key, derives a shared secret with recipient_pub,
    derives an AEAD key using HKDF, and encrypts plaintext.

    Returns a JSON-serializable dict {epk, nonce, ct}.
    """
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(recipient_pub)
    salt = os.urandom(32)
    key = hkdf_sha256(shared, salt=salt, info=context, length=32)
    nonce = os.urandom(12)
    ct = aead_encrypt(key, nonce, plaintext, aad=context)
    return {
        "epk": b64e(eph.public_key().public_bytes_raw()),
        "salt": b64e(salt),
        "nonce": b64e(nonce),
        "ct": b64e(ct),
    }


def open_from_x25519(recipient_priv: X25519PrivateKey, sealed: dict, *, context: bytes) -> bytes:
    try:
        epk = X25519PublicKey.from_public_bytes(b64d(sealed["epk"]))
        salt = b64d(sealed["salt"])
        nonce = b64d(sealed["nonce"])
        ct = b64d(sealed["ct"])
    except Exception as e:
        raise CryptoError(f"invalid sealed box: {e}")

    shared = recipient_priv.exchange(epk)
    key = hkdf_sha256(shared, salt=salt, info=context, length=32)
    return aead_decrypt(key, nonce, ct, aad=context)


def encrypt_package(plaintext: bytes, *, key: bytes | None = None, aad: bytes = b"") -> Tuple[bytes, bytes]:
    """Encrypts a package with a random symmetric key and returns (envelope_json_bytes, key)."""
    if key is None:
        key = os.urandom(32)
    nonce = os.urandom(12)
    ct = aead_encrypt(key, nonce, plaintext, aad=aad)
    import json
    env = {
        "v": 1,
        "cipher": "chacha20poly1305",
        "nonce": b64e(nonce),
        "ct": b64e(ct),
        "aad": b64e(aad),
    }
    return json.dumps(env, sort_keys=True, separators=(",", ":")).encode("utf-8"), key


def decrypt_package(envelope_bytes: bytes, *, key: bytes, aad: bytes | None = None) -> bytes:
    import json
    try:
        env = json.loads(envelope_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise CryptoError(f"invalid envelope format: {e}")
    if env.get("cipher") != "chacha20poly1305":
        raise CryptoError("unsupported cipher")
    nonce = b64d(env["nonce"])
    ct = b64d(env["ct"])
    env_aad = b64d(env.get("aad", "")) if env.get("aad") is not None else b""
    if aad is None:
        aad = env_aad
    return aead_decrypt(key, nonce, ct, aad=aad)

from __future__ import annotations

import base64
import logging
import os
import sys
from dataclasses import dataclass
from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

logger = logging.getLogger("lb.keys")


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


@dataclass(frozen=True)
class NodeKeys:
    sign_priv: Ed25519PrivateKey
    sign_pub: Ed25519PublicKey
    enc_priv: X25519PrivateKey
    enc_pub: X25519PublicKey

    @property
    def sign_pub_b64(self) -> str:
        return b64e(self.sign_pub.public_bytes(Encoding.Raw, PublicFormat.Raw))

    @property
    def enc_pub_b64(self) -> str:
        return b64e(self.enc_pub.public_bytes(Encoding.Raw, PublicFormat.Raw))


def gen_node_keys() -> NodeKeys:
    sp = Ed25519PrivateKey.generate()
    ep = X25519PrivateKey.generate()
    return NodeKeys(
        sign_priv=sp,
        sign_pub=sp.public_key(),
        enc_priv=ep,
        enc_pub=ep.public_key(),
    )


def sign_detached(priv: Ed25519PrivateKey, msg: bytes) -> bytes:
    return priv.sign(msg)


def verify_detached(pub: Ed25519PublicKey, msg: bytes, sig: bytes) -> bool:
    try:
        pub.verify(sig, msg)
        return True
    except Exception:
        return False


def load_sign_priv_raw(raw: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_enc_priv_raw(raw: bytes) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(raw)


def load_sign_pub_raw(raw: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(raw)


def load_enc_pub_raw(raw: bytes) -> X25519PublicKey:
    return X25519PublicKey.from_public_bytes(raw)


def dump_sign_priv_raw(priv: Ed25519PrivateKey) -> bytes:
    return priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def dump_enc_priv_raw(priv: X25519PrivateKey) -> bytes:
    return priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def dump_sign_pub_raw(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(Encoding.Raw, PublicFormat.Raw)


def dump_enc_pub_raw(pub: X25519PublicKey) -> bytes:
    return pub.public_bytes(Encoding.Raw, PublicFormat.Raw)


def ensure_mode_600(path: str) -> None:
    """Best-effort POSIX permission hardening.

    Attempts to set file permissions to 0600 (owner read/write only).
    On Windows or when permission change fails, logs a warning.
    """
    # Skip on Windows - chmod doesn't work the same way
    if sys.platform == "win32":
        logger.debug(f"Skipping chmod on Windows for {path}")
        return

    try:
        os.chmod(path, 0o600)
    except OSError as e:
        logger.warning(f"Could not set permissions on {path}: {e}")

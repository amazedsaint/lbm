from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from .canonical import canonical_json, sha256_hex
from .crypto import hkdf_sha256, aead_encrypt, aead_decrypt, CryptoError
from .keys import NodeKeys, b64e, b64d, verify_detached, sign_detached, load_sign_pub_raw

from .wire import read_frame, write_frame


PROTO = "lb-p2p-v1"

# Maximum clock drift allowed for handshake timestamps (5 minutes)
HANDSHAKE_MAX_CLOCK_DRIFT_MS = 5 * 60 * 1000


class HandshakeError(Exception):
    pass


def _validate_handshake_timestamp(ts: int, max_drift_ms: int = HANDSHAKE_MAX_CLOCK_DRIFT_MS) -> None:
    """Validate handshake timestamp is within acceptable bounds.

    Args:
        ts: Timestamp in milliseconds
        max_drift_ms: Maximum allowed clock drift in ms

    Raises:
        HandshakeError: If timestamp is invalid or too far from current time
    """
    if not isinstance(ts, int):
        raise HandshakeError("invalid timestamp format")

    now_ms = int(time.time() * 1000)

    # Reject timestamps too far in the future
    if ts > now_ms + max_drift_ms:
        raise HandshakeError(f"timestamp too far in future ({ts} > {now_ms + max_drift_ms})")

    # Reject timestamps too far in the past (prevent replay attacks)
    if ts < now_ms - max_drift_ms:
        raise HandshakeError(f"timestamp too old ({ts} < {now_ms - max_drift_ms})")


@dataclass
class SecureSession:
    self_sign_pub: str
    self_enc_pub: str
    peer_sign_pub: str
    peer_enc_pub: str
    send_key: bytes
    recv_key: bytes
    nonce_prefix_send: bytes
    nonce_prefix_recv: bytes
    send_ctr: int = 0
    recv_ctr: int = 0

    def seal(self, obj: Dict[str, Any]) -> bytes:
        pt = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ctr = self.send_ctr
        self.send_ctr += 1
        nonce = self.nonce_prefix_send + ctr.to_bytes(8, "big")
        aad = (PROTO + "|").encode("utf-8") + ctr.to_bytes(8, "big")
        ct = aead_encrypt(self.send_key, nonce, pt, aad=aad)
        env = {"ctr": ctr, "ct": b64e(ct)}
        return json.dumps(env, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def open(self, env_bytes: bytes) -> Dict[str, Any]:
        env = json.loads(env_bytes.decode("utf-8"))
        ctr = env.get("ctr")
        if not isinstance(ctr, int):
            raise CryptoError("missing ctr")
        if ctr != self.recv_ctr:
            raise CryptoError(f"unexpected ctr {ctr} (expected {self.recv_ctr})")
        self.recv_ctr += 1
        ct = b64d(env.get("ct", ""))
        nonce = self.nonce_prefix_recv + ctr.to_bytes(8, "big")
        aad = (PROTO + "|").encode("utf-8") + ctr.to_bytes(8, "big")
        pt = aead_decrypt(self.recv_key, nonce, ct, aad=aad)
        return json.loads(pt.decode("utf-8"))


def _sign_json(keys: NodeKeys, msg: Dict[str, Any]) -> Dict[str, Any]:
    m = dict(msg)
    sig = sign_detached(keys.sign_priv, canonical_json(m).encode("utf-8"))
    m["sig"] = b64e(sig)
    return m


def _verify_signed(msg: Dict[str, Any]) -> Tuple[str, str]:
    """Returns (sign_pub_b64, enc_pub_b64) if signature valid."""
    sig_b64 = msg.get("sig")
    if not isinstance(sig_b64, str):
        raise HandshakeError("missing sig")
    sign_pub_b64 = msg.get("sign_pub")
    enc_pub_b64 = msg.get("enc_pub")
    if not isinstance(sign_pub_b64, str) or not isinstance(enc_pub_b64, str):
        raise HandshakeError("missing sign_pub/enc_pub")
    try:
        pub = load_sign_pub_raw(b64d(sign_pub_b64))
    except Exception as e:
        raise HandshakeError(f"bad sign_pub: {e}")
    body = dict(msg)
    body.pop("sig", None)
    ok = verify_detached(pub, canonical_json(body).encode("utf-8"), b64d(sig_b64))
    if not ok:
        raise HandshakeError("bad signature")
    return sign_pub_b64, enc_pub_b64


async def client_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, keys: NodeKeys) -> SecureSession:
    eph = X25519PrivateKey.generate()
    hello = {
        "type": "hello",
        "v": PROTO,
        "sign_pub": keys.sign_pub_b64,
        "enc_pub": keys.enc_pub_b64,
        "eph_pub": b64e(eph.public_key().public_bytes_raw()),
        "nonce": b64e(os.urandom(32)),
        "ts": int(time.time() * 1000),
    }
    hello = _sign_json(keys, hello)
    await write_frame(writer, json.dumps(hello, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    wel_bytes = await read_frame(reader)
    welcome = json.loads(wel_bytes.decode("utf-8"))
    if welcome.get("type") != "welcome" or welcome.get("v") != PROTO:
        raise HandshakeError("bad welcome")
    peer_sign_pub, peer_enc_pub = _verify_signed(welcome)

    # Validate server timestamp to prevent replay attacks
    _validate_handshake_timestamp(welcome.get("ts", 0))

    # validate binding to hello
    hh = welcome.get("hello_hash")
    if not isinstance(hh, str) or hh != sha256_hex(json.dumps(hello, sort_keys=True, separators=(",", ":")).encode("utf-8")):
        raise HandshakeError("hello_hash mismatch")

    try:
        peer_eph = X25519PublicKey.from_public_bytes(b64d(welcome["eph_pub"]))
    except Exception as e:
        raise HandshakeError(f"bad server eph_pub: {e}")

    shared = eph.exchange(peer_eph)
    transcript = json.dumps(hello, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"|" + wel_bytes
    th = bytes.fromhex(sha256_hex(transcript))
    km = hkdf_sha256(shared, salt=th, info=PROTO.encode("utf-8"), length=64)

    # client sends first half, receives second half
    send_key = km[:32]
    recv_key = km[32:]
    prefix_c2s = th[:4]
    prefix_s2c = th[4:8]

    return SecureSession(
        self_sign_pub=keys.sign_pub_b64,
        self_enc_pub=keys.enc_pub_b64,
        peer_sign_pub=peer_sign_pub,
        peer_enc_pub=peer_enc_pub,
        send_key=send_key,
        recv_key=recv_key,
        nonce_prefix_send=prefix_c2s,
        nonce_prefix_recv=prefix_s2c,
    )


async def server_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, keys: NodeKeys) -> SecureSession:
    hel_bytes = await read_frame(reader)
    hello = json.loads(hel_bytes.decode("utf-8"))
    if hello.get("type") != "hello" or hello.get("v") != PROTO:
        raise HandshakeError("bad hello")
    peer_sign_pub, peer_enc_pub = _verify_signed(hello)

    # Validate client timestamp to prevent replay attacks
    _validate_handshake_timestamp(hello.get("ts", 0))

    eph = X25519PrivateKey.generate()
    welcome = {
        "type": "welcome",
        "v": PROTO,
        "sign_pub": keys.sign_pub_b64,
        "enc_pub": keys.enc_pub_b64,
        "eph_pub": b64e(eph.public_key().public_bytes_raw()),
        "nonce": b64e(os.urandom(32)),
        "ts": int(time.time() * 1000),
        "hello_hash": sha256_hex(hel_bytes),
    }
    welcome = _sign_json(keys, welcome)
    wel_bytes = json.dumps(welcome, sort_keys=True, separators=(",", ":")).encode("utf-8")
    await write_frame(writer, wel_bytes)

    try:
        peer_eph = X25519PublicKey.from_public_bytes(b64d(hello["eph_pub"]))
    except Exception as e:
        raise HandshakeError(f"bad client eph_pub: {e}")

    shared = eph.exchange(peer_eph)
    transcript = hel_bytes + b"|" + wel_bytes
    th = bytes.fromhex(sha256_hex(transcript))
    km = hkdf_sha256(shared, salt=th, info=PROTO.encode("utf-8"), length=64)

    # server receives first half, sends second half
    recv_key = km[:32]
    send_key = km[32:]
    prefix_c2s = th[:4]
    prefix_s2c = th[4:8]

    return SecureSession(
        self_sign_pub=keys.sign_pub_b64,
        self_enc_pub=keys.enc_pub_b64,
        peer_sign_pub=peer_sign_pub,
        peer_enc_pub=peer_enc_pub,
        send_key=send_key,
        recv_key=recv_key,
        nonce_prefix_send=prefix_s2c,
        nonce_prefix_recv=prefix_c2s,
    )

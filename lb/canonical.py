from __future__ import annotations

import json
import hashlib
from typing import Any


def canonical_json(obj: Any) -> str:
    """Canonical JSON for hashing/signing.

    - UTF-8
    - sorted keys
    - no whitespace
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(obj: Any) -> str:
    return sha256_hex(canonical_json(obj).encode("utf-8"))


def hash_bytes(data: bytes) -> str:
    return sha256_hex(data)

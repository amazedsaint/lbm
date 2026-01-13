from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .canonical import sha256_hex
from .fs import ensure_dir, atomic_write_bytes, atomic_write_json, read_json
from .logging_config import get_node_logger

logger = get_node_logger()


@dataclass
class CasMeta:
    visibility: str  # "public" or "group:<gid>"
    kind: str        # e.g. "claim", "experience", "package"
    group_id: Optional[str] = None
    created_ms: Optional[int] = None
    size: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "visibility": self.visibility,
            "kind": self.kind,
            "group_id": self.group_id,
            "created_ms": self.created_ms,
            "size": self.size,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CasMeta":
        return CasMeta(
            visibility=str(d.get("visibility", "public")),
            kind=str(d.get("kind", "")),
            group_id=d.get("group_id"),
            created_ms=d.get("created_ms"),
            size=d.get("size"),
        )


class CASError(Exception):
    """Error in content-addressed store operations."""
    pass


# Maximum object size (100 MB default)
DEFAULT_MAX_OBJECT_SIZE = 100 * 1024 * 1024


class CAS:
    """Content-addressed store (sha256) with a tiny metadata index.

    Thread-safe with consistency validation on startup.
    """

    def __init__(self, root: Path, *, validate_on_startup: bool = True, max_object_size: int = DEFAULT_MAX_OBJECT_SIZE):
        self.root = Path(root)
        self.max_object_size = max_object_size
        ensure_dir(self.root)
        self.obj_dir = self.root / "objects"
        self.index_path = self.root / "index.json"
        ensure_dir(self.obj_dir)
        self._lock = threading.RLock()

        if self.index_path.exists():
            self.index: Dict[str, Dict[str, Any]] = read_json(self.index_path)
        else:
            self.index = {}

        if validate_on_startup:
            self._validate_index()

    def _obj_path(self, h: str) -> Path:
        return self.obj_dir / h[:2] / h[2:4] / h

    def _validate_index(self) -> Tuple[int, int, int]:
        """Validate index consistency with filesystem.

        Returns:
            Tuple of (valid_count, orphan_files_added, stale_entries_removed)
        """
        valid = 0
        orphans_added = 0
        stale_removed = 0

        with self._lock:
            # Check for stale index entries (in index but not on disk)
            stale_hashes = []
            for h in list(self.index.keys()):
                if not self._obj_path(h).exists():
                    logger.warning(f"CAS: removing stale index entry {h[:16]}... (file missing)")
                    stale_hashes.append(h)
                else:
                    valid += 1

            for h in stale_hashes:
                del self.index[h]
                stale_removed += 1

            # Check for orphan files (on disk but not in index)
            for prefix_dir in self.obj_dir.iterdir():
                if not prefix_dir.is_dir():
                    continue
                for subdir in prefix_dir.iterdir():
                    if not subdir.is_dir():
                        continue
                    for obj_file in subdir.iterdir():
                        h = obj_file.name
                        if h not in self.index:
                            # Verify the hash matches content
                            try:
                                data = obj_file.read_bytes()
                                actual_hash = sha256_hex(data)
                                if actual_hash == h:
                                    logger.info(f"CAS: adding orphan file to index {h[:16]}...")
                                    self.index[h] = CasMeta(
                                        visibility="public",
                                        kind="unknown",
                                        created_ms=int(obj_file.stat().st_mtime * 1000),
                                        size=len(data)
                                    ).to_dict()
                                    orphans_added += 1
                                else:
                                    logger.error(f"CAS: orphan file {h[:16]}... has wrong hash, removing")
                                    obj_file.unlink()
                            except Exception as e:
                                logger.error(f"CAS: error validating orphan {h[:16]}...: {e}")

            # Save index if modified
            if stale_removed > 0 or orphans_added > 0:
                self._save_index_unlocked()
                logger.info(f"CAS: index validated - valid={valid}, orphans_added={orphans_added}, stale_removed={stale_removed}")

        return (valid, orphans_added, stale_removed)

    def _save_index_unlocked(self) -> None:
        """Save index to disk with fsync. Must hold lock."""
        atomic_write_json(self.index_path, self.index)

    def has(self, h: str) -> bool:
        with self._lock:
            return self._obj_path(h).exists()

    def meta(self, h: str) -> Optional[CasMeta]:
        with self._lock:
            m = self.index.get(h)
            if not m:
                return None
            return CasMeta.from_dict(m)

    def put(self, data: bytes, meta: CasMeta) -> str:
        """Store data in CAS.

        Args:
            data: Data bytes to store
            meta: Metadata for the object

        Returns:
            SHA256 hash of the data

        Raises:
            CASError: If data exceeds max_object_size
        """
        if len(data) > self.max_object_size:
            raise CASError(f"Object too large: {len(data)} > {self.max_object_size} bytes")

        h = sha256_hex(data)
        with self._lock:
            p = self._obj_path(h)
            if not p.exists():
                ensure_dir(p.parent)
                atomic_write_bytes(p, data)
            # update index
            if meta.created_ms is None:
                meta.created_ms = int(time.time() * 1000)
            meta.size = len(data)
            self.index[h] = meta.to_dict()
            self._save_index_unlocked()
        return h

    def get(self, h: str) -> bytes:
        with self._lock:
            p = self._obj_path(h)
            if not p.exists():
                raise FileNotFoundError(h)
            return p.read_bytes()

    def put_json(self, obj: Any, meta: CasMeta) -> str:
        import json
        b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.put(b, meta)

    def get_json(self, h: str) -> Any:
        import json
        return json.loads(self.get(h).decode("utf-8"))

    def verify(self, h: str) -> bool:
        """Verify object integrity by checking hash."""
        with self._lock:
            try:
                data = self.get(h)
                return sha256_hex(data) == h
            except FileNotFoundError:
                return False

    def stats(self) -> Dict[str, Any]:
        """Get CAS statistics."""
        with self._lock:
            total_size = sum(m.get("size", 0) for m in self.index.values())
            by_kind: Dict[str, int] = {}
            for m in self.index.values():
                kind = m.get("kind", "unknown")
                by_kind[kind] = by_kind.get(kind, 0) + 1
            return {
                "object_count": len(self.index),
                "total_size_bytes": total_size,
                "by_kind": by_kind,
            }

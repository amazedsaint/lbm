"""Write-Ahead Log (WAL) for transactional durability.

Provides atomic multi-file operations to prevent split-brain state after crashes.
Operations are logged before execution, allowing recovery on startup.

Usage:
    wal = WriteAheadLog(data_dir / "wal")

    with wal.transaction() as tx:
        tx.write_json(chain_path, chain_data)
        tx.write_json(graph_path, graph_data)
        tx.write_json(wallet_path, wallet_data)
    # All writes committed atomically, or none

On startup:
    wal = WriteAheadLog(data_dir / "wal")
    wal.recover()  # Replays or rolls back incomplete transactions
"""
from __future__ import annotations

import json
import os
import time
import threading
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from .fs import atomic_write_json
from .logging_config import get_logger

logger = get_logger(__name__)


class WALError(Exception):
    """Write-ahead log error."""
    pass


@dataclass
class WALEntry:
    """Single WAL entry representing a file write operation."""
    tx_id: str
    seq: int
    operation: str  # "write", "delete"
    path: str
    backup_path: Optional[str] = None
    data_path: Optional[str] = None  # Path to staged data file
    timestamp_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "seq": self.seq,
            "operation": self.operation,
            "path": self.path,
            "backup_path": self.backup_path,
            "data_path": self.data_path,
            "timestamp_ms": self.timestamp_ms,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "WALEntry":
        return WALEntry(
            tx_id=d["tx_id"],
            seq=d["seq"],
            operation=d["operation"],
            path=d["path"],
            backup_path=d.get("backup_path"),
            data_path=d.get("data_path"),
            timestamp_ms=d.get("timestamp_ms", 0),
        )


@dataclass
class Transaction:
    """Represents an in-progress WAL transaction."""
    tx_id: str
    wal: "WriteAheadLog"
    entries: List[WALEntry] = field(default_factory=list)
    _seq: int = 0
    _committed: bool = False
    _rolled_back: bool = False

    def write_json(self, path: Path, data: Any) -> None:
        """Stage a JSON file write."""
        if self._committed or self._rolled_back:
            raise WALError("Transaction already finalized")

        path = Path(path)
        self._seq += 1

        # Create backup of existing file if it exists
        backup_path = None
        if path.exists():
            backup_path = str(self.wal.wal_dir / f"{self.tx_id}_{self._seq}.backup")
            shutil.copy2(path, backup_path)

        # Stage the new data
        data_path = str(self.wal.wal_dir / f"{self.tx_id}_{self._seq}.staged")
        atomic_write_json(Path(data_path), data)

        entry = WALEntry(
            tx_id=self.tx_id,
            seq=self._seq,
            operation="write",
            path=str(path),
            backup_path=backup_path,
            data_path=data_path,
            timestamp_ms=int(time.time() * 1000),
        )
        self.entries.append(entry)
        self.wal._write_entry(entry)

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Stage a binary file write."""
        if self._committed or self._rolled_back:
            raise WALError("Transaction already finalized")

        path = Path(path)
        self._seq += 1

        # Create backup of existing file if it exists
        backup_path = None
        if path.exists():
            backup_path = str(self.wal.wal_dir / f"{self.tx_id}_{self._seq}.backup")
            shutil.copy2(path, backup_path)

        # Stage the new data
        data_path = str(self.wal.wal_dir / f"{self.tx_id}_{self._seq}.staged")
        tmp_path = Path(data_path + ".tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(data_path)

        entry = WALEntry(
            tx_id=self.tx_id,
            seq=self._seq,
            operation="write",
            path=str(path),
            backup_path=backup_path,
            data_path=data_path,
            timestamp_ms=int(time.time() * 1000),
        )
        self.entries.append(entry)
        self.wal._write_entry(entry)

    def commit(self) -> None:
        """Commit all staged writes atomically."""
        if self._committed or self._rolled_back:
            raise WALError("Transaction already finalized")

        # Write commit marker
        self.wal._write_commit(self.tx_id)

        # Apply all staged writes
        for entry in self.entries:
            if entry.operation == "write" and entry.data_path:
                target = Path(entry.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry.data_path, target)

        # Clean up WAL entries and staged files
        self._cleanup()
        self._committed = True
        logger.debug(f"WAL transaction {self.tx_id} committed with {len(self.entries)} operations")

    def rollback(self) -> None:
        """Rollback all staged writes."""
        if self._committed or self._rolled_back:
            return

        # Restore backups
        for entry in reversed(self.entries):
            if entry.backup_path and Path(entry.backup_path).exists():
                shutil.copy2(entry.backup_path, entry.path)

        # Clean up
        self._cleanup()
        self._rolled_back = True
        logger.debug(f"WAL transaction {self.tx_id} rolled back")

    def _cleanup(self) -> None:
        """Clean up staged files and backups."""
        for entry in self.entries:
            if entry.backup_path:
                try:
                    Path(entry.backup_path).unlink(missing_ok=True)
                except Exception:
                    pass
            if entry.data_path:
                try:
                    Path(entry.data_path).unlink(missing_ok=True)
                except Exception:
                    pass

        # Remove WAL log entries for this transaction
        self.wal._remove_tx_entries(self.tx_id)


class WriteAheadLog:
    """Write-ahead log for atomic multi-file operations."""

    def __init__(self, wal_dir: Path):
        self.wal_dir = Path(wal_dir)
        self.wal_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.wal_dir / "wal.log"
        self._lock = threading.Lock()
        self._tx_counter = 0

    def _generate_tx_id(self) -> str:
        """Generate a unique transaction ID."""
        self._tx_counter += 1
        return f"tx_{int(time.time() * 1000)}_{self._tx_counter}"

    def _write_entry(self, entry: WALEntry) -> None:
        """Append an entry to the WAL log."""
        with self._lock:
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"type": "entry", **entry.to_dict()}) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def _write_commit(self, tx_id: str) -> None:
        """Write a commit marker for a transaction."""
        with self._lock:
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"type": "commit", "tx_id": tx_id, "timestamp_ms": int(time.time() * 1000)}) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def _remove_tx_entries(self, tx_id: str) -> None:
        """Remove all WAL entries for a transaction after commit/rollback."""
        with self._lock:
            if not self.log_path.exists():
                return

            # Read existing entries, filter out the completed transaction
            remaining = []
            with open(self.log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("tx_id") != tx_id:
                            remaining.append(line)
                    except json.JSONDecodeError:
                        continue

            # Rewrite the log
            if remaining:
                with open(self.log_path, "w") as f:
                    for line in remaining:
                        f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            else:
                self.log_path.unlink(missing_ok=True)

    @contextmanager
    def transaction(self):
        """Start a new transaction context.

        Usage:
            with wal.transaction() as tx:
                tx.write_json(path1, data1)
                tx.write_json(path2, data2)
            # Committed on successful exit, rolled back on exception
        """
        tx = Transaction(tx_id=self._generate_tx_id(), wal=self)
        try:
            yield tx
            tx.commit()
        except Exception:
            tx.rollback()
            raise

    def recover(self) -> int:
        """Recover from incomplete transactions on startup.

        Returns:
            Number of transactions recovered (rolled back or replayed)
        """
        if not self.log_path.exists():
            return 0

        # Parse WAL log
        entries_by_tx: Dict[str, List[WALEntry]] = {}
        committed_txs: set = set()

        with open(self.log_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("type") == "entry":
                        entry = WALEntry.from_dict(record)
                        if entry.tx_id not in entries_by_tx:
                            entries_by_tx[entry.tx_id] = []
                        entries_by_tx[entry.tx_id].append(entry)
                    elif record.get("type") == "commit":
                        committed_txs.add(record["tx_id"])
                except json.JSONDecodeError:
                    continue

        recovered = 0

        for tx_id, entries in entries_by_tx.items():
            if tx_id in committed_txs:
                # Transaction was committed but cleanup didn't finish
                # Replay the writes and clean up
                for entry in entries:
                    if entry.operation == "write" and entry.data_path:
                        if Path(entry.data_path).exists():
                            target = Path(entry.path)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(entry.data_path, target)
                logger.info(f"WAL: Replayed committed transaction {tx_id}")
            else:
                # Transaction was not committed - rollback
                for entry in reversed(entries):
                    if entry.backup_path and Path(entry.backup_path).exists():
                        shutil.copy2(entry.backup_path, entry.path)
                logger.info(f"WAL: Rolled back incomplete transaction {tx_id}")

            # Clean up staged/backup files
            for entry in entries:
                if entry.backup_path:
                    Path(entry.backup_path).unlink(missing_ok=True)
                if entry.data_path:
                    Path(entry.data_path).unlink(missing_ok=True)

            recovered += 1

        # Clear the WAL log
        self.log_path.unlink(missing_ok=True)

        # Clean up any orphaned staged files
        for f in self.wal_dir.glob("tx_*.staged"):
            f.unlink(missing_ok=True)
        for f in self.wal_dir.glob("tx_*.backup"):
            f.unlink(missing_ok=True)

        if recovered > 0:
            logger.info(f"WAL: Recovered {recovered} transactions on startup")

        return recovered

    def checkpoint(self) -> None:
        """Force a checkpoint - ensure all pending operations are durable."""
        with self._lock:
            if self.log_path.exists():
                with open(self.log_path, "a") as f:
                    f.flush()
                    os.fsync(f.fileno())

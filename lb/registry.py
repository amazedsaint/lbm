"""Peer registry and subscription management for Learning Battery Market.

Provides persistent storage for known peers and group subscriptions
with thread-safe operations and atomic writes.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fs import atomic_write_json, read_json
from .logging_config import get_logger

logger = get_logger("lb.registry")


def _now_ms() -> int:
    """Current time in milliseconds."""
    return int(time.time() * 1000)


@dataclass
class Peer:
    """Registered peer node."""
    host: str
    port: int
    node_id: str              # 12-char truncated hash of sign_pub
    sign_pub: str             # Ed25519 public key (base64)
    enc_pub: str              # X25519 public key (base64)
    alias: Optional[str]      # Human-friendly name
    last_seen_ms: int         # Last successful contact
    last_error: Optional[str] # Last error message if any
    added_ms: int             # When peer was added

    @property
    def key(self) -> str:
        """Unique key for this peer (host:port)."""
        return f"{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Peer":
        """Create Peer from dictionary."""
        return Peer(
            host=d["host"],
            port=d["port"],
            node_id=d["node_id"],
            sign_pub=d["sign_pub"],
            enc_pub=d["enc_pub"],
            alias=d.get("alias"),
            last_seen_ms=d.get("last_seen_ms", 0),
            last_error=d.get("last_error"),
            added_ms=d.get("added_ms", 0),
        )


@dataclass
class Subscription:
    """Group subscription with sync configuration."""
    group_id: str
    peer_host: str            # Primary sync peer host
    peer_port: int            # Primary sync peer port
    sync_interval_s: int      # Seconds between syncs (default 300 = 5 min)
    enabled: bool             # Pause/resume sync
    last_sync_ms: int         # Last successful sync timestamp
    last_error: Optional[str] # Last sync error message
    auto_subscribe: bool = False  # Auto-subscribe to dependent groups

    @property
    def peer_key(self) -> str:
        """Key for the sync peer."""
        return f"{self.peer_host}:{self.peer_port}"

    def is_due(self, now_ms: Optional[int] = None) -> bool:
        """Check if sync is due based on interval."""
        if not self.enabled:
            return False
        if now_ms is None:
            now_ms = _now_ms()
        interval_ms = self.sync_interval_s * 1000
        return (now_ms - self.last_sync_ms) >= interval_ms

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Subscription":
        """Create Subscription from dictionary."""
        return Subscription(
            group_id=d["group_id"],
            peer_host=d["peer_host"],
            peer_port=d["peer_port"],
            sync_interval_s=d.get("sync_interval_s", 300),
            enabled=d.get("enabled", True),
            last_sync_ms=d.get("last_sync_ms", 0),
            last_error=d.get("last_error"),
            auto_subscribe=d.get("auto_subscribe", False),
        )


class PeerRegistry:
    """Persistent peer registry with atomic writes.

    Manages:
    - Known peers (stored in peers.json)
    - Group subscriptions (stored in subscriptions.json)

    Thread-safe with RLock for concurrent access.
    """

    def __init__(self, data_dir: Path):
        """Initialize registry with data directory.

        Args:
            data_dir: Node data directory (peers.json and subscriptions.json stored here)
        """
        self.data_dir = Path(data_dir)
        self.peers_path = self.data_dir / "peers.json"
        self.subscriptions_path = self.data_dir / "subscriptions.json"
        self._peers: Dict[str, Peer] = {}           # keyed by "host:port"
        self._subscriptions: Dict[str, Subscription] = {}  # keyed by group_id
        self._lock = threading.RLock()
        self._load()

    # ========== Peer Management ==========

    def add_peer(self, peer: Peer) -> None:
        """Add or update a peer in the registry."""
        with self._lock:
            self._peers[peer.key] = peer
            self._save_peers()
            logger.info(f"Added peer {peer.key} (node_id={peer.node_id[:8]}...)")

    def remove_peer(self, key: str) -> bool:
        """Remove a peer by key (host:port). Returns True if removed."""
        with self._lock:
            if key in self._peers:
                del self._peers[key]
                self._save_peers()
                logger.info(f"Removed peer {key}")
                return True
            return False

    def get_peer(self, key: str) -> Optional[Peer]:
        """Get peer by key (host:port)."""
        with self._lock:
            return self._peers.get(key)

    def list_peers(self) -> List[Peer]:
        """List all registered peers."""
        with self._lock:
            return list(self._peers.values())

    def update_peer_status(
        self,
        key: str,
        last_seen_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update peer status after connection attempt."""
        with self._lock:
            peer = self._peers.get(key)
            if peer:
                if last_seen_ms is not None:
                    peer.last_seen_ms = last_seen_ms
                peer.last_error = error
                self._save_peers()

    # ========== Subscription Management ==========

    def subscribe(self, sub: Subscription) -> None:
        """Add or update a subscription."""
        with self._lock:
            self._subscriptions[sub.group_id] = sub
            self._save_subscriptions()
            logger.info(f"Subscribed to group {sub.group_id} from {sub.peer_key}")

    def unsubscribe(self, group_id: str) -> bool:
        """Remove a subscription. Returns True if removed."""
        with self._lock:
            if group_id in self._subscriptions:
                del self._subscriptions[group_id]
                self._save_subscriptions()
                logger.info(f"Unsubscribed from group {group_id}")
                return True
            return False

    def get_subscription(self, group_id: str) -> Optional[Subscription]:
        """Get subscription by group ID."""
        with self._lock:
            return self._subscriptions.get(group_id)

    def list_subscriptions(self) -> List[Subscription]:
        """List all subscriptions."""
        with self._lock:
            return list(self._subscriptions.values())

    def list_due_subscriptions(self, now_ms: Optional[int] = None) -> List[Subscription]:
        """List subscriptions that are due for sync."""
        if now_ms is None:
            now_ms = _now_ms()
        with self._lock:
            return [s for s in self._subscriptions.values() if s.is_due(now_ms)]

    def update_sync_status(
        self,
        group_id: str,
        last_sync_ms: int,
        error: Optional[str] = None,
    ) -> None:
        """Update subscription sync status."""
        with self._lock:
            sub = self._subscriptions.get(group_id)
            if sub:
                sub.last_sync_ms = last_sync_ms
                sub.last_error = error
                self._save_subscriptions()

    def set_sync_interval(self, group_id: str, interval_s: int) -> bool:
        """Set sync interval for a subscription. Returns True if found."""
        with self._lock:
            sub = self._subscriptions.get(group_id)
            if sub:
                sub.sync_interval_s = interval_s
                self._save_subscriptions()
                logger.info(f"Set sync interval for {group_id} to {interval_s}s")
                return True
            return False

    def set_enabled(self, group_id: str, enabled: bool) -> bool:
        """Enable/disable a subscription. Returns True if found."""
        with self._lock:
            sub = self._subscriptions.get(group_id)
            if sub:
                sub.enabled = enabled
                self._save_subscriptions()
                logger.info(f"Set enabled={enabled} for subscription {group_id}")
                return True
            return False

    # ========== Persistence ==========

    def _load(self) -> None:
        """Load peers and subscriptions from disk."""
        # Load peers
        if self.peers_path.exists():
            try:
                data = read_json(self.peers_path)
                for key, peer_dict in data.items():
                    self._peers[key] = Peer.from_dict(peer_dict)
                logger.debug(f"Loaded {len(self._peers)} peers from {self.peers_path}")
            except Exception as e:
                logger.warning(f"Failed to load peers: {e}")

        # Load subscriptions
        if self.subscriptions_path.exists():
            try:
                data = read_json(self.subscriptions_path)
                for gid, sub_dict in data.items():
                    self._subscriptions[gid] = Subscription.from_dict(sub_dict)
                logger.debug(f"Loaded {len(self._subscriptions)} subscriptions from {self.subscriptions_path}")
            except Exception as e:
                logger.warning(f"Failed to load subscriptions: {e}")

    def _save_peers(self) -> None:
        """Save peers to disk atomically."""
        data = {key: peer.to_dict() for key, peer in self._peers.items()}
        atomic_write_json(self.peers_path, data)

    def _save_subscriptions(self) -> None:
        """Save subscriptions to disk atomically."""
        data = {gid: sub.to_dict() for gid, sub in self._subscriptions.items()}
        atomic_write_json(self.subscriptions_path, data)

    # ========== Statistics ==========

    def stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            enabled_subs = [s for s in self._subscriptions.values() if s.enabled]
            return {
                "peer_count": len(self._peers),
                "subscription_count": len(self._subscriptions),
                "enabled_subscriptions": len(enabled_subs),
                "peers_with_errors": len([p for p in self._peers.values() if p.last_error]),
                "subs_with_errors": len([s for s in self._subscriptions.values() if s.last_error]),
            }

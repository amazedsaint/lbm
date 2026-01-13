"""Rate limiting for Learning Battery Market P2P and RPC.

Provides sliding window rate limiting for connections and requests.
Includes memory bounds to prevent DoS via key exhaustion.
"""
from __future__ import annotations

import time
import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import get_config
from .logging_config import get_p2p_logger

logger = get_p2p_logger()

# Memory bounds to prevent DoS
DEFAULT_MAX_TRACKED_KEYS = 10000  # Maximum unique keys to track
DEFAULT_MAX_TRACKED_IPS = 1000   # Maximum unique IPs for connection limiting


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    wait_seconds: float = 0.0
    reason: str = ""


class SlidingWindowRateLimiter:
    """Sliding window rate limiter with memory bounds.

    Tracks requests within a time window and limits to max_requests.
    Uses LRU eviction when max_keys is reached to prevent memory exhaustion.
    """

    def __init__(self, window_seconds: float, max_requests: int, *, max_keys: int = DEFAULT_MAX_TRACKED_KEYS):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.max_keys = max_keys
        # Use OrderedDict for LRU eviction - most recently used keys at end
        self._requests: OrderedDict[str, List[float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 60.0  # Auto-cleanup every 60 seconds

    async def check(self, key: str) -> RateLimitResult:
        """Check if a request is allowed for the given key.

        Args:
            key: Identifier (e.g., IP address, peer_id)

        Returns:
            RateLimitResult with allowed status and wait time if blocked
        """
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds

            # Periodic auto-cleanup to prevent memory buildup
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired_unlocked(now, cutoff)

            # Get or create entry, moving to end (most recently used)
            if key in self._requests:
                self._requests.move_to_end(key)
                timestamps = self._requests[key]
            else:
                # Check if we need to evict old entries
                if len(self._requests) >= self.max_keys:
                    self._evict_oldest_unlocked(cutoff)
                timestamps = []
                self._requests[key] = timestamps

            # Remove expired entries for this key
            timestamps[:] = [ts for ts in timestamps if ts > cutoff]

            if len(timestamps) >= self.max_requests:
                # Calculate wait time
                oldest = timestamps[0] if timestamps else now
                wait_seconds = oldest + self.window_seconds - now
                return RateLimitResult(
                    allowed=False,
                    wait_seconds=max(0, wait_seconds),
                    reason=f"rate limit exceeded: {len(timestamps)}/{self.max_requests} requests in {self.window_seconds}s"
                )

            # Allow and record
            timestamps.append(now)
            return RateLimitResult(allowed=True)

    def _evict_oldest_unlocked(self, cutoff: float) -> int:
        """Evict oldest entries to make room. Must hold lock."""
        evicted = 0
        # Evict up to 10% of max_keys or at least 1
        to_evict = max(1, self.max_keys // 10)

        keys_to_remove = []
        for key, timestamps in self._requests.items():
            if evicted >= to_evict:
                break
            # First try to remove completely expired keys
            active = [ts for ts in timestamps if ts > cutoff]
            if not active:
                keys_to_remove.append(key)
                evicted += 1

        # If we didn't find enough expired keys, evict LRU (oldest accessed)
        if evicted < to_evict:
            for key in self._requests.keys():
                if evicted >= to_evict:
                    break
                if key not in keys_to_remove:
                    keys_to_remove.append(key)
                    evicted += 1

        for key in keys_to_remove:
            del self._requests[key]

        if evicted > 0:
            logger.debug(f"Rate limiter evicted {evicted} keys (memory bounds)")

        return evicted

    def _cleanup_expired_unlocked(self, now: float, cutoff: float) -> int:
        """Remove all expired entries. Must hold lock."""
        self._last_cleanup = now
        removed = 0
        empty_keys = []

        for key, timestamps in self._requests.items():
            before = len(timestamps)
            timestamps[:] = [ts for ts in timestamps if ts > cutoff]
            removed += before - len(timestamps)
            if not timestamps:
                empty_keys.append(key)

        for key in empty_keys:
            del self._requests[key]

        return removed

    async def cleanup(self) -> int:
        """Remove expired entries from all keys. Returns count removed."""
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            return self._cleanup_expired_unlocked(now, cutoff)

    async def stats(self) -> Dict[str, int]:
        """Get rate limiter statistics."""
        async with self._lock:
            total_timestamps = sum(len(ts) for ts in self._requests.values())
            return {
                "tracked_keys": len(self._requests),
                "max_keys": self.max_keys,
                "total_timestamps": total_timestamps,
            }


class ConnectionLimiter:
    """Limits concurrent connections per IP address.

    Includes memory bounds to prevent tracking unlimited IPs.
    """

    def __init__(self, max_per_ip: int, *, max_ips: int = DEFAULT_MAX_TRACKED_IPS):
        self.max_per_ip = max_per_ip
        self.max_ips = max_ips
        self._connections: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, ip: str) -> bool:
        """Try to acquire a connection slot for the IP.

        Args:
            ip: IP address

        Returns:
            True if connection allowed, False if limit reached
        """
        async with self._lock:
            current = self._connections.get(ip, 0)
            if current >= self.max_per_ip:
                return False

            # Check memory bounds - only for new IPs
            if ip not in self._connections and len(self._connections) >= self.max_ips:
                # Evict IPs with 0 connections (shouldn't exist, but safety check)
                to_remove = [k for k, v in self._connections.items() if v <= 0]
                for k in to_remove:
                    del self._connections[k]

                # If still at limit, reject new IP
                if len(self._connections) >= self.max_ips:
                    logger.warning(f"Connection limiter at max IPs ({self.max_ips}), rejecting new IP {ip}")
                    return False

            self._connections[ip] = current + 1
            return True

    async def release(self, ip: str) -> None:
        """Release a connection slot for the IP. Safe to call multiple times."""
        async with self._lock:
            if ip in self._connections:
                self._connections[ip] -= 1
                if self._connections[ip] <= 0:
                    del self._connections[ip]

    async def get_count(self, ip: str) -> int:
        """Get current connection count for IP."""
        async with self._lock:
            return self._connections.get(ip, 0)

    async def stats(self) -> Dict[str, int]:
        """Get connection limiter statistics."""
        async with self._lock:
            total_connections = sum(self._connections.values())
            return {
                "tracked_ips": len(self._connections),
                "max_ips": self.max_ips,
                "total_connections": total_connections,
            }


@dataclass
class P2PRateLimiter:
    """Combined rate limiter for P2P operations."""

    # Connection limiting
    connection_limiter: ConnectionLimiter = field(default_factory=lambda: ConnectionLimiter(
        max_per_ip=get_config().p2p.max_connections_per_ip
    ))

    # Request rate limiting (per connection/peer)
    request_limiter: SlidingWindowRateLimiter = field(default_factory=lambda: SlidingWindowRateLimiter(
        window_seconds=60.0,
        max_requests=get_config().p2p.max_requests_per_minute
    ))

    async def check_connection(self, ip: str) -> RateLimitResult:
        """Check if a new connection is allowed from this IP."""
        if await self.connection_limiter.acquire(ip):
            return RateLimitResult(allowed=True)
        return RateLimitResult(
            allowed=False,
            reason=f"too many connections from {ip} (max {self.connection_limiter.max_per_ip})"
        )

    async def release_connection(self, ip: str) -> None:
        """Release a connection slot."""
        await self.connection_limiter.release(ip)

    async def check_request(self, peer_id: str) -> RateLimitResult:
        """Check if a request is allowed from this peer."""
        return await self.request_limiter.check(peer_id)

    async def cleanup(self) -> int:
        """Cleanup expired rate limit entries."""
        return await self.request_limiter.cleanup()


# Global rate limiter instance with thread-safe initialization
_rate_limiter: Optional[P2PRateLimiter] = None
_rate_limiter_lock = asyncio.Lock()
import threading
_rate_limiter_thread_lock = threading.Lock()


def get_rate_limiter() -> P2PRateLimiter:
    """Get the global rate limiter instance (thread-safe)."""
    global _rate_limiter
    if _rate_limiter is not None:
        return _rate_limiter
    # Thread-safe initialization
    with _rate_limiter_thread_lock:
        if _rate_limiter is None:
            _rate_limiter = P2PRateLimiter()
        return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter (thread-safe)."""
    global _rate_limiter
    with _rate_limiter_thread_lock:
        _rate_limiter = None

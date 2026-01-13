from __future__ import annotations

import asyncio
import struct
from typing import Optional

from .config import get_config

DEFAULT_MAX_FRAME_BYTES = 8 * 1024 * 1024  # 8MB (fallback if config not available)


def _get_max_frame_size() -> int:
    """Get max frame size from config, with fallback."""
    try:
        return get_config().p2p.max_frame_size_bytes
    except Exception:
        return DEFAULT_MAX_FRAME_BYTES


class WireError(Exception):
    pass


async def read_frame(reader: asyncio.StreamReader, *, max_bytes: Optional[int] = None) -> bytes:
    """Read a length-prefixed frame from the stream.

    Args:
        reader: Async stream reader
        max_bytes: Maximum allowed frame size (uses config if not specified)

    Returns:
        Frame payload bytes

    Raises:
        WireError: If frame exceeds max size
    """
    if max_bytes is None:
        max_bytes = _get_max_frame_size()

    hdr = await reader.readexactly(4)
    n = struct.unpack(">I", hdr)[0]
    if n > max_bytes:
        raise WireError(f"frame too large: {n} > {max_bytes}")
    return await reader.readexactly(n)


async def write_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    writer.write(struct.pack(">I", len(payload)) + payload)
    await writer.drain()

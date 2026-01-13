from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Union


class FSError(Exception):
    pass


def ensure_dir(p: Union[str, Path]) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)


def atomic_write_bytes(path: Union[str, Path], data: bytes) -> None:
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def atomic_write_text(path: Union[str, Path], text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: Union[str, Path], obj: Any, encoding: str = "utf-8") -> None:
    import json
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2), encoding=encoding)


def read_json(path: Union[str, Path]) -> Any:
    """Read and parse a JSON file.

    Args:
        path: Path to the JSON file

    Returns:
        Parsed JSON data (dict, list, or primitive)

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

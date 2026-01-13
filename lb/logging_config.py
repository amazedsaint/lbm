"""Logging configuration for Learning Battery Market.

Provides structured logging with configurable levels and formats.
Supports both console and file output with JSON formatting option.
"""
from __future__ import annotations

import logging
import logging.handlers
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


# Log levels
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL

# Default configuration
DEFAULT_LOG_LEVEL = os.environ.get("LB_LOG_LEVEL", "INFO").upper()
DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_DIR = os.environ.get("LB_LOG_DIR", "")


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ContextLogger(logging.LoggerAdapter):
    """Logger adapter that adds context to all log messages."""

    def __init__(self, logger: logging.Logger, context: Dict[str, Any]):
        super().__init__(logger, context)

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        # Add context to extra
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging(
    name: str = "lb",
    level: str = DEFAULT_LOG_LEVEL,
    log_file: Optional[str] = None,
    json_format: bool = False,
    console: bool = True,
) -> logging.Logger:
    """Configure and return a logger.

    Args:
        name: Logger name (typically module name)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file
        json_format: Use JSON formatting for logs
        console: Enable console output

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers if already configured
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Choose formatter
    if json_format:
        formatter = JsonFormatter(datefmt=DEFAULT_DATE_FORMAT)
    else:
        formatter = logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)

    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler
    if log_file or LOG_DIR:
        if log_file:
            file_path = Path(log_file)
        else:
            file_path = Path(LOG_DIR) / f"{name}.log"

        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Rotating file handler (10MB max, keep 5 backups)
        file_handler = logging.handlers.RotatingFileHandler(
            file_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger with the given name.

    Args:
        name: Logger name (use __name__ for module loggers)

    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # Set up with defaults if not configured
        setup_logging(name)
    return logger


def log_operation(
    logger: logging.Logger,
    operation: str,
    success: bool,
    duration_ms: Optional[float] = None,
    **kwargs: Any,
) -> None:
    """Log an operation result with timing and context.

    Args:
        logger: Logger instance
        operation: Operation name
        success: Whether operation succeeded
        duration_ms: Operation duration in milliseconds
        **kwargs: Additional context to log
    """
    level = INFO if success else ERROR
    status = "SUCCESS" if success else "FAILED"

    msg_parts = [f"{operation}: {status}"]
    if duration_ms is not None:
        msg_parts.append(f"({duration_ms:.2f}ms)")

    extra_data = {"operation": operation, "success": success, **kwargs}
    if duration_ms is not None:
        extra_data["duration_ms"] = duration_ms

    record = logger.makeRecord(
        logger.name,
        level,
        "",
        0,
        " ".join(msg_parts),
        (),
        None,
    )
    record.extra_data = extra_data
    logger.handle(record)


class Timer:
    """Context manager for timing operations."""

    def __init__(self):
        self.start_time: float = 0
        self.end_time: float = 0

    def __enter__(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        self.end_time = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


# Pre-configured loggers for main components
def get_node_logger() -> logging.Logger:
    return get_logger("lb.node")


def get_chain_logger() -> logging.Logger:
    return get_logger("lb.chain")


def get_p2p_logger() -> logging.Logger:
    return get_logger("lb.p2p")


def get_crypto_logger() -> logging.Logger:
    return get_logger("lb.crypto")


def get_mcp_logger() -> logging.Logger:
    return get_logger("lb.mcp")

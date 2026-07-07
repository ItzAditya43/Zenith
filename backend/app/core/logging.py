"""
Structured JSONL logging for Cortex.

Replaces bare print()/unstructured exception strings with one consistent
JSON-per-line format that downstream tooling (jq, Loki, vector, etc.) can
ingest cleanly. Routing decisions, attachment lifecycle events, and
backend boot events all flow through here.

Writes to:
  - stdout (always; what the developer / `docker logs` sees)
  - backend/data/cortex.log (rotated by size; historical record)

The level is read once at import time from `settings.get("log_level", "INFO")`
and from the LOG_LEVEL env var as an override.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# Lazy import: settings depends on the data dir existing, which logging
# shouldn't gate on.
_settings_singleton: Any | None = None


def _get_settings():
    global _settings_singleton
    if _settings_singleton is None:
        from app.core.config import settings as _s

        _settings_singleton = _s
    return _settings_singleton


_LOGGER: logging.Logger | None = None
_FILE_HANDLER: RotatingFileHandler | None = None


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            )
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        # Attach any extra=... context the caller passed in.
        for key, value in record.__dict__.items():
            if key in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "asctime",
                "taskName",
            ):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    """Idempotently set up the global JSONL logger."""
    global _LOGGER, _FILE_HANDLER
    if _LOGGER is not None:
        return _LOGGER

    level_name = os.environ.get("LOG_LEVEL") or "INFO"
    try:
        s = _get_settings()
        cfg_level = s.get("log_level", "INFO")
        if isinstance(cfg_level, str) and cfg_level.upper() in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            level_name = cfg_level.upper()
    except Exception:
        # Settings may not be loadable yet; fall back to env/defaults.
        pass

    level = getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger("cortex")
    logger.setLevel(level)
    logger.propagate = False  # don't double-log via uvicorn root

    # Clear any handlers a previous reload may have installed.
    for h in list(logger.handlers):
        logger.removeHandler(h)

    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(JsonFormatter())
    logger.addHandler(stream)

    # Best-effort file handler; never crash boot if the data dir is read-only.
    try:
        data_dir = Path(
            os.environ.get("CORTEX_DATA_DIR")
            or (_get_settings().get("data_dir") or "data")
        )
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "cortex.log"
        _FILE_HANDLER = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        _FILE_HANDLER.setFormatter(JsonFormatter())
        logger.addHandler(_FILE_HANDLER)
    except Exception as exc:  # noqa: BLE001
        logger.warning("log file handler unavailable", extra={"reason": str(exc)})

    _LOGGER = logger
    return logger


# Kwargs that stdlib `Logger._log` itself consumes from kwargs.
_STDLIB_RESERVED = {"args", "exc_info", "exc_text", "stack_info"}

# `LogRecord` attribute names that `makeRecord` refuses to overwrite via
# `extra=`. We auto-rename these (e.g. `name` -> `event_name`) so callers
# can still log a field called `name` and we don't silently drop it.
_LOGRECORD_COLLISIONS = {
    "name": "event_name",
    "message": "event_message",
    "asctime": "event_asctime",
    "args": "event_args",
}


class BoundLogger:
    """Thin shim that turns `log.info("evt", foo=1, bar="x")` into
    a structured `extra={"foo": 1, "bar": "x"}` automatically.

    The stdlib `Logger._log` rejects arbitrary kwargs; without this
    wrapper every call site has to remember `extra={...}`. With it the
    spec's "structured logging replaces bare print" goal is met without
    ceremony at every emit.

    The wrapped logger is the underlying stdlib logger, so any handler,
    level, or formatter configured on the root `cortex` logger still
    applies — only the call-site ergonomics change.
    """

    __slots__ = ("_log",)

    def __init__(self, inner: logging.Logger) -> None:
        self._log = inner

    def _emit(self, level: int, msg: object, *args, **kwargs) -> None:
        extra = kwargs.pop("extra", None) or {}
        # Harvest any leftover kwargs as structured context.
        for k, v in list(kwargs.items()):
            if k in _STDLIB_RESERVED:
                # Don't silently drop reserved kwargs; re-raise as a
                # programmer error so misuse is caught early.
                raise TypeError(
                    f"log call passed reserved stdlib kwarg {k!r}; "
                    f"use extra={{ {k!r}: ... }} or pick a different name"
                )
            # Auto-rename keys that would collide with LogRecord attrs
            # so the structured context isn't silently dropped.
            target_key = _LOGRECORD_COLLISIONS.get(k, k)
            extra.setdefault(target_key, v)
        self._log.log(level, msg, *args, extra=extra)

    def debug(self, msg: object, *args, **kwargs) -> None:
        self._emit(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: object, *args, **kwargs) -> None:
        self._emit(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: object, *args, **kwargs) -> None:
        self._emit(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: object, *args, **kwargs) -> None:
        self._emit(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg: object, *args, exc_info=True, **kwargs) -> None:
        self._emit(logging.ERROR, msg, *args, exc_info=exc_info, **kwargs)

    def critical(self, msg: object, *args, **kwargs) -> None:
        self._emit(logging.CRITICAL, msg, *args, **kwargs)

    # Pass-through attributes so `logger.name`, `logger.level`, etc. keep working.
    @property
    def name(self) -> str:
        return self._log.name

    @property
    def level(self) -> int:
        return self._log.level


def get_logger(name: str | None = None):
    """Return the configured JSONL logger, optionally namespaced.

    `name` is treated as a `__name__`-style dotted suffix and joined to
    the root "cortex" logger so different modules get distinct log
    records (`logger="cortex.api.upload"`, etc.) without re-running
    `configure_logging`. Returns a `BoundLogger` so callers can use
    `log.info("evt", foo=1)` without manually wrapping `extra=...`."""
    root = configure_logging()
    if name:
        return BoundLogger(root.getChild(name))
    return BoundLogger(root)

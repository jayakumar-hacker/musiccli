"""
MusiCLI - Logging Setup
========================
Configures a rotating file logger + an optional console logger.
Import `get_logger(__name__)` in every module.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from config import LOG_FILE, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT

_configured = False


def setup_logging(verbose: bool = False) -> None:
    """
    Call once at startup.  Subsequent calls are no-ops.

    Args:
        verbose: If True, also emit DEBUG logs to stderr.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("musicli")
    root.setLevel(logging.DEBUG)  # let handlers filter

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Rotating file handler ─────────────────────────────────────────────────
    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # ── Optional stderr handler (verbose / debug mode) ────────────────────────
    if verbose:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(fmt)
        root.addHandler(sh)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'musicli' namespace."""
    return logging.getLogger(f"musicli.{name}")

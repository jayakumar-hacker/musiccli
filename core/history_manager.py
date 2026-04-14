"""
MusiCLI – HistoryManager
=========================
Tracks every song played (with timestamp) and persists to disk as JSON.
Thread-safe via RLock.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import HISTORY_FILE, HISTORY_MAX_ENTRIES
from core.models import HistoryEntry, Track
from logger import get_logger

log = get_logger("history")


class HistoryManager:
    """
    Append-only history of played tracks.

    Newest entries are at the front.  The list is capped at
    HISTORY_MAX_ENTRIES to keep the file size bounded.
    """

    def __init__(self, history_file: Path = HISTORY_FILE) -> None:
        self._path    = history_file
        self._lock    = threading.RLock()
        self._entries: list[HistoryEntry] = []
        self._dirty   = False
        self._load()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, track: Track) -> None:
        """Prepend a HistoryEntry for *track* and flush to disk."""
        entry = HistoryEntry(track=track, played_at=time.time())
        with self._lock:
            self._entries.insert(0, entry)
            if len(self._entries) > HISTORY_MAX_ENTRIES:
                self._entries = self._entries[:HISTORY_MAX_ENTRIES]
            self._dirty = True
        self._flush()
        log.debug("History: recorded '%s'", track.title)

    def recent(self, n: int = 20) -> list[HistoryEntry]:
        """Return the *n* most recently played entries."""
        with self._lock:
            return list(self._entries[:n])

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._dirty = True
        self._flush()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8").strip()
                if not raw:
                    return
                self._entries = [HistoryEntry.from_dict(e) for e in json.loads(raw)]
                log.info("Loaded %d history entries", len(self._entries))
        except Exception as exc:
            log.warning("Could not load history: %s", exc)
            self._entries = []

    def _flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            data = [e.to_dict() for e in self._entries]
            try:
                self._path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=None),
                    encoding="utf-8",
                )
                self._dirty = False
            except Exception as exc:
                log.error("Failed to write history: %s", exc)

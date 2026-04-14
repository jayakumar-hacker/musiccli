"""
MusiCLI – QueueManager
========================
Thread-safe, ordered playback queue.

Responsibilities
-----------------
* Add / remove / reorder tracks
* Track the "current" position
* Signal the PlayerEngine when a preload should begin
* Notify listeners (via callback) when the queue changes

Does NOT touch yt-dlp or ffplay directly – pure data management.
"""

from __future__ import annotations

import threading
from copy import copy
from typing import Callable, Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.models import Track
from logger import get_logger

log = get_logger("queue")

_ChangeCallback = Callable[[], None]


class QueueManager:
    """
    Manages the ordered list of tracks to be played.

    The queue is a list of Track objects.  `_index` points to the track
    that is *currently playing* (or next to play if idle).

    Thread-safety: all mutations acquire `_lock`.
    """

    def __init__(self) -> None:
        self._lock:     threading.RLock         = threading.RLock()
        self._tracks:   list[Track]             = []
        self._index:    int                     = 0   # current position
        self._on_change: list[_ChangeCallback]  = []

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, cb: _ChangeCallback) -> None:
        """Register a callback invoked whenever the queue changes."""
        self._on_change.append(cb)

    def _notify(self) -> None:
        for cb in self._on_change:
            try:
                cb()
            except Exception as exc:
                log.warning("Queue change callback raised: %s", exc)

    # ── Mutations ─────────────────────────────────────────────────────────────

    def add(self, track: Track) -> None:
        """Append a track to the end of the queue."""
        with self._lock:
            self._tracks.append(track)
            log.debug("Queued: %s", track.title)
        self._notify()

    def add_next(self, track: Track) -> None:
        """Insert a track immediately after the current position (play next)."""
        with self._lock:
            insert_at = self._index + 1
            self._tracks.insert(insert_at, track)
            log.debug("Play-next: %s", track.title)
        self._notify()

    def remove(self, position: int) -> Optional[Track]:
        """
        Remove track at *1-based* queue position.
        Returns the removed track or None if out of range.
        """
        with self._lock:
            idx = position - 1
            if not (0 <= idx < len(self._tracks)):
                return None
            track = self._tracks.pop(idx)
            # Adjust current index if needed
            if idx < self._index:
                self._index = max(0, self._index - 1)
            elif idx == self._index:
                self._index = min(self._index, len(self._tracks) - 1)
            log.debug("Removed from queue: %s", track.title)
        self._notify()
        return track

    def move(self, from_pos: int, to_pos: int) -> bool:
        """
        Move a track from *from_pos* to *to_pos* (both 1-based).
        Returns True on success.
        """
        with self._lock:
            n = len(self._tracks)
            fi, ti = from_pos - 1, to_pos - 1
            if not (0 <= fi < n and 0 <= ti < n and fi != ti):
                return False
            track = self._tracks.pop(fi)
            self._tracks.insert(ti, track)
            # Keep _index pointing at the same track
            if self._index == fi:
                self._index = ti
            elif fi < self._index <= ti:
                self._index -= 1
            elif ti <= self._index < fi:
                self._index += 1
        self._notify()
        return True

    def clear(self) -> None:
        """Remove all tracks and reset position."""
        with self._lock:
            self._tracks.clear()
            self._index = 0
        self._notify()

    def shuffle(self) -> None:
        """Shuffle remaining tracks (after current)."""
        import random
        with self._lock:
            remaining = self._tracks[self._index + 1:]
            random.shuffle(remaining)
            self._tracks[self._index + 1:] = remaining
        self._notify()

    # ── Navigation ────────────────────────────────────────────────────────────

    def current(self) -> Optional[Track]:
        """Return the current track without advancing."""
        with self._lock:
            if 0 <= self._index < len(self._tracks):
                return self._tracks[self._index]
            return None

    def peek_next(self) -> Optional[Track]:
        """Return the next track without advancing the pointer."""
        with self._lock:
            ni = self._index + 1
            if ni < len(self._tracks):
                return self._tracks[ni]
            return None

    def advance(self) -> Optional[Track]:
        """
        Move to the next track and return it.
        Returns None if we're already at the end of the queue.
        """
        with self._lock:
            if self._index + 1 < len(self._tracks):
                self._index += 1
                track = self._tracks[self._index]
                log.debug("Queue advanced to: %s", track.title)
                self._notify()
                return track
            return None

    def go_to(self, position: int) -> Optional[Track]:
        """Jump to a 1-based queue position. Returns track or None."""
        with self._lock:
            idx = position - 1
            if 0 <= idx < len(self._tracks):
                self._index = idx
                self._notify()
                return self._tracks[idx]
            return None

    def go_back(self) -> Optional[Track]:
        """Move to the previous track."""
        with self._lock:
            if self._index > 0:
                self._index -= 1
                self._notify()
                return self._tracks[self._index]
            return None

    # ── Read-only helpers ──────────────────────────────────────────────────────

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return len(self._tracks) == 0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._tracks)

    @property
    def current_index(self) -> int:
        with self._lock:
            return self._index

    def list_tracks(self) -> list[tuple[int, Track, bool]]:
        """
        Return a snapshot: list of (1-based position, Track, is_current).
        Safe to iterate outside the lock.
        """
        with self._lock:
            return [
                (i + 1, copy(t), i == self._index)
                for i, t in enumerate(self._tracks)
            ]

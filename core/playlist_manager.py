"""
MusiCLI – PlaylistManager
==========================
Persistent storage of user playlists as individual JSON files.

Each playlist is a separate file: ~/.musicli/playlists/<name>.json
This avoids rewriting a monolithic file on every change.

Thread-safe via a per-playlist RLock (one lock per file path).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import PLAYLIST_DIR
from core.models import Playlist, Track
from logger import get_logger

log = get_logger("playlist")

_VALID_NAME = re.compile(r"^[\w\- ]{1,64}$")


class PlaylistManager:
    """
    CRUD operations for persistent playlists.

    Playlists are stored as JSON in PLAYLIST_DIR.
    Filenames are derived from the playlist name (lowercased, spaces→underscores).
    """

    def __init__(self, storage_dir: Path = PLAYLIST_DIR) -> None:
        self._dir   = storage_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._meta_lock = threading.Lock()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _path(self, name: str) -> Path:
        safe = name.strip().lower().replace(" ", "_")
        return self._dir / f"{safe}.json"

    def _lock_for(self, name: str) -> threading.RLock:
        key = name.strip().lower()
        with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _VALID_NAME.match(name):
            raise ValueError(
                f"Invalid playlist name '{name}'. "
                "Use letters, numbers, hyphens and spaces (max 64 chars)."
            )

    # ── Public API ─────────────────────────────────────────────────────────────

    def list_playlists(self) -> list[str]:
        """Return sorted list of playlist names."""
        return sorted(
            p.stem.replace("_", " ").title()
            for p in self._dir.glob("*.json")
        )

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def create(self, name: str) -> Playlist:
        """Create an empty playlist (raises ValueError if it already exists)."""
        self._validate_name(name)
        with self._lock_for(name):
            path = self._path(name)
            if path.exists():
                raise ValueError(f"Playlist '{name}' already exists.")
            pl = Playlist(name=name)
            self._write(path, pl)
            log.info("Created playlist '%s'", name)
            return pl

    def load(self, name: str) -> Optional[Playlist]:
        """Load a playlist by name, returning None if not found."""
        with self._lock_for(name):
            path = self._path(name)
            if not path.exists():
                return None
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                return Playlist.from_dict(raw)
            except Exception as exc:
                log.error("Failed to load playlist '%s': %s", name, exc)
                return None

    def save(self, playlist: Playlist) -> None:
        """Persist a playlist object to disk."""
        self._validate_name(playlist.name)
        with self._lock_for(playlist.name):
            self._write(self._path(playlist.name), playlist)

    def delete(self, name: str) -> bool:
        """Delete a playlist. Returns True if deleted, False if not found."""
        with self._lock_for(name):
            path = self._path(name)
            if not path.exists():
                return False
            path.unlink()
            log.info("Deleted playlist '%s'", name)
            return True

    def rename(self, old_name: str, new_name: str) -> None:
        """Rename a playlist."""
        self._validate_name(new_name)
        with self._lock_for(old_name), self._lock_for(new_name):
            old_path = self._path(old_name)
            new_path = self._path(new_name)
            if not old_path.exists():
                raise ValueError(f"Playlist '{old_name}' not found.")
            if new_path.exists():
                raise ValueError(f"Playlist '{new_name}' already exists.")
            pl = self.load(old_name)
            pl.name = new_name
            self._write(new_path, pl)
            old_path.unlink()
            log.info("Renamed playlist '%s' → '%s'", old_name, new_name)

    # ── Track operations ───────────────────────────────────────────────────────

    def add_track(self, playlist_name: str, track: Track) -> None:
        """Append a track to an existing playlist (creates playlist if needed)."""
        with self._lock_for(playlist_name):
            pl = self.load(playlist_name)
            if pl is None:
                pl = Playlist(name=playlist_name)
            # Avoid duplicates
            if any(t.video_id == track.video_id for t in pl.tracks):
                log.debug("Track already in '%s', skipping", playlist_name)
                return
            pl.tracks.append(track)
            self.save(pl)
            log.info("Added '%s' to '%s'", track.title, playlist_name)

    def remove_track(self, playlist_name: str, position: int) -> Optional[Track]:
        """Remove 1-based position from playlist. Returns removed Track or None."""
        with self._lock_for(playlist_name):
            pl = self.load(playlist_name)
            if pl is None:
                return None
            idx = position - 1
            if not (0 <= idx < len(pl.tracks)):
                return None
            track = pl.tracks.pop(idx)
            self.save(pl)
            log.info("Removed '%s' from '%s'", track.title, playlist_name)
            return track

    def load_into_queue(self, playlist_name: str, queue) -> int:
        """
        Load all tracks from *playlist_name* into *queue*.
        Returns number of tracks added.
        """
        pl = self.load(playlist_name)
        if not pl:
            return 0
        for track in pl.tracks:
            queue.add(track)
        log.info("Loaded %d tracks from '%s' into queue", len(pl.tracks), pl.name)
        return len(pl.tracks)

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _write(path: Path, playlist: Playlist) -> None:
        path.write_text(
            json.dumps(playlist.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

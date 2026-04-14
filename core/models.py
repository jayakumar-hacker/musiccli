"""
MusiCLI - Data Models
======================
Plain dataclasses shared across all modules.
No external dependencies — only stdlib.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class PlayerState(Enum):
    IDLE      = auto()
    LOADING   = auto()
    PLAYING   = auto()
    PAUSED    = auto()
    STOPPED   = auto()
    ERROR     = auto()


# ── Track ─────────────────────────────────────────────────────────────────────

@dataclass
class Track:
    """
    Represents a single audio track.

    `stream_url` is populated lazily by the PlayerEngine right before
    playback (or during preload) so that search results stay lightweight.
    """
    video_id:    str
    title:       str
    artist:      str          = ""
    duration:    int          = 0        # seconds; 0 = unknown
    thumbnail:   str          = ""       # URL
    webpage_url: str          = ""       # YouTube watch URL

    # Resolved at playback time – NOT persisted in playlists
    stream_url:  Optional[str] = field(default=None, repr=False)

    # ── Convenience ───────────────────────────────────────────────────────────

    @property
    def display_title(self) -> str:
        return f"{self.artist} – {self.title}" if self.artist else self.title

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "--:--"
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def to_dict(self) -> dict:
        return {
            "video_id":    self.video_id,
            "title":       self.title,
            "artist":      self.artist,
            "duration":    self.duration,
            "thumbnail":   self.thumbnail,
            "webpage_url": self.webpage_url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(
            video_id    = d.get("video_id", ""),
            title       = d.get("title", "Unknown"),
            artist      = d.get("artist", ""),
            duration    = d.get("duration", 0),
            thumbnail   = d.get("thumbnail", ""),
            webpage_url = d.get("webpage_url", ""),
        )

    def __hash__(self):
        return hash(self.video_id)

    def __eq__(self, other):
        if isinstance(other, Track):
            return self.video_id == other.video_id
        return NotImplemented


# ── HistoryEntry ──────────────────────────────────────────────────────────────

@dataclass
class HistoryEntry:
    track:      Track
    played_at:  float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "track":     self.track.to_dict(),
            "played_at": self.played_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        return cls(
            track     = Track.from_dict(d["track"]),
            played_at = d.get("played_at", 0.0),
        )


# ── Playlist ──────────────────────────────────────────────────────────────────

@dataclass
class Playlist:
    name:   str
    tracks: list[Track] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name":   self.name,
            "tracks": [t.to_dict() for t in self.tracks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Playlist":
        return cls(
            name   = d.get("name", "Unnamed"),
            tracks = [Track.from_dict(t) for t in d.get("tracks", [])],
        )

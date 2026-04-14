"""
MusiCLI – SearchService
========================
Wraps yt-dlp's ytsearch to deliver fast, cached YouTube search results.

Key design decisions
---------------------
* Runs yt-dlp in a *thread-pool executor* so the caller can use it from
  both plain threads AND asyncio without blocking the event loop.
* Uses CacheManager for two-tier (RAM + disk) caching.
* Strips unnecessary metadata via `extract_flat=True` for speed.
* Resolves only the fields we actually need (title, duration, etc.).
"""

from __future__ import annotations

import concurrent.futures
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from typing import Optional

import yt_dlp

from config import (
    SEARCH_MAX_RESULTS,
    YTDLP_BASE_OPTS,
    YTDLP_SEARCH_TIMEOUT,
)
from logger import get_logger
from core.models import Track
from core.cache_manager import CacheManager

log = get_logger("search")


def _extract_track(entry: dict) -> Optional[Track]:
    """Convert a raw yt-dlp entry dict into a Track, returning None on failure."""
    vid = entry.get("id") or entry.get("video_id")
    if not vid:
        return None
    title     = entry.get("title") or "Unknown Title"
    artist    = entry.get("uploader") or entry.get("channel") or ""
    duration  = int(entry.get("duration") or 0)
    thumbnail = (entry.get("thumbnails") or [{}])[-1].get("url", "") \
                if isinstance(entry.get("thumbnails"), list) \
                else entry.get("thumbnail", "")
    webpage   = entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
    return Track(
        video_id    = vid,
        title       = title,
        artist      = artist,
        duration    = duration,
        thumbnail   = thumbnail,
        webpage_url = webpage,
    )


def _do_search(query: str, max_results: int) -> list[Track]:
    """
    Blocking yt-dlp search.  Runs inside a thread-pool worker.
    Returns an empty list on any failure so callers stay simple.
    """
    opts = {
        **YTDLP_BASE_OPTS,
        "extract_flat":  "in_playlist",
        "socket_timeout": YTDLP_SEARCH_TIMEOUT,
        "playlist_items": f"1-{max_results}",
    }
    search_url = f"ytsearch{max_results}:{query}"
    tracks: list[Track] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            entries = info.get("entries") or []
            for entry in entries:
                track = _extract_track(entry)
                if track:
                    tracks.append(track)
        log.debug("Search '%s' → %d results", query, len(tracks))
    except Exception as exc:
        log.error("yt-dlp search error: %s", exc)
    return tracks


class SearchService:
    """
    High-level search service with caching.

    Example::

        svc = SearchService(cache)
        results: list[Track] = svc.search("Daft Punk Get Lucky")

    `search()` is a regular blocking call suitable for use in a thread.
    `search_async()` returns a Future for fire-and-forget patterns.
    """

    def __init__(
        self,
        cache:       Optional[CacheManager] = None,
        max_results: int = SEARCH_MAX_RESULTS,
    ) -> None:
        self._cache       = cache or CacheManager()
        self._max_results = max_results
        # Bounded pool: search is I/O-bound, 4 workers is plenty
        self._executor    = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="search"
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def search(self, query: str, *, force_refresh: bool = False) -> list[Track]:
        """
        Synchronous search.  Returns cached results when available.

        Args:
            query:         Human-readable search string.
            force_refresh: Bypass cache and re-query YouTube.

        Returns:
            Ordered list of Track objects (may be empty on failure).
        """
        if not query.strip():
            return []

        if not force_refresh:
            cached = self._cache.get(query)
            if cached is not None:
                log.info("Cache hit for '%s'", query)
                return [Track.from_dict(t) for t in cached]

        log.info("Querying YouTube for '%s'", query)
        tracks = _do_search(query, self._max_results)
        if tracks:
            self._cache.set(query, [t.to_dict() for t in tracks])
        return tracks

    def search_async(
        self,
        query:         str,
        force_refresh: bool = False,
    ) -> concurrent.futures.Future:
        """
        Non-blocking search.  Returns a Future[list[Track]].

        Usage::

            future = svc.search_async("Radiohead Creep")
            # ... do other work ...
            results = future.result(timeout=15)
        """
        return self._executor.submit(self.search, query, force_refresh=force_refresh)

    def resolve_stream_url(self, track: Track) -> Optional[str]:
        """
        Resolve the direct audio stream URL for a track.
        This is a *blocking* call; use in a background thread or preloader.
        """
        opts = {
            **YTDLP_BASE_OPTS,
            "extract_flat": False,          # need full info
            "format":       "bestaudio/best",
            "socket_timeout": 15,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    track.webpage_url or f"https://www.youtube.com/watch?v={track.video_id}",
                    download=False,
                )
                url = info.get("url")
                if url:
                    log.debug("Resolved stream for '%s'", track.title)
                return url
        except Exception as exc:
            log.error("Failed to resolve stream URL for %s: %s", track.video_id, exc)
            return None

    def resolve_stream_async(self, track: Track) -> concurrent.futures.Future:
        """Non-blocking stream URL resolution. Returns Future[Optional[str]]."""
        return self._executor.submit(self.resolve_stream_url, track)

    def shutdown(self) -> None:
        """Cleanly shut down the internal thread pool."""
        self._executor.shutdown(wait=False)

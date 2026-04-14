"""
MusiCLI – CacheManager
========================
Two-tier caching:
  1. In-process LRU (OrderedDict) for ultra-fast repeat hits this session.
  2. JSON disk cache with TTL for persistence across restarts.

Thread-safe via a single RLock.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    SEARCH_CACHE,
    SEARCH_CACHE_TTL_HOURS,
    SEARCH_CACHE_MAX_SIZE,
)
from logger import get_logger

log = get_logger("cache")

_TTL_SECONDS = SEARCH_CACHE_TTL_HOURS * 3600
_RAM_MAX     = 64          # keep the latest 64 queries in RAM


class CacheManager:
    """
    Manages search-result caching with in-memory LRU + persistent JSON storage.

    Usage::

        cache = CacheManager()
        results = cache.get("lofi hip hop")
        if results is None:
            results = expensive_search(...)
            cache.set("lofi hip hop", results)
    """

    def __init__(self, disk_path: Path = SEARCH_CACHE) -> None:
        self._lock      = RLock()
        self._ram:      OrderedDict[str, list] = OrderedDict()
        self._disk_path = disk_path
        self._disk:     dict[str, dict]        = {}   # {query: {ts, data}}
        self._dirty     = False
        self._load_disk()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, query: str) -> Optional[list]:
        """
        Return cached search results or *None* on miss / expiry.
        Moves hit to the front of the RAM cache (LRU).
        """
        key = self._normalise(query)
        with self._lock:
            # 1. RAM hit
            if key in self._ram:
                self._ram.move_to_end(key)
                log.debug("RAM cache hit: %s", key)
                return self._ram[key]
            # 2. Disk hit
            entry = self._disk.get(key)
            if entry and (time.time() - entry["ts"]) < _TTL_SECONDS:
                data = entry["data"]
                self._promote_to_ram(key, data)
                log.debug("Disk cache hit: %s", key)
                return data
            # 3. Miss (or expired)
            if key in self._disk:
                del self._disk[key]
                self._dirty = True
            return None

    def set(self, query: str, results: list) -> None:
        """Persist results to both RAM and disk caches."""
        key = self._normalise(query)
        with self._lock:
            self._promote_to_ram(key, results)
            self._disk[key] = {"ts": time.time(), "data": results}
            self._dirty = True
            self._evict_disk()
            self._flush_disk()

    def invalidate(self, query: str) -> None:
        """Remove a specific query from both caches."""
        key = self._normalise(query)
        with self._lock:
            self._ram.pop(key, None)
            if self._disk.pop(key, None):
                self._dirty = True
                self._flush_disk()

    def clear(self) -> None:
        """Wipe all cached data."""
        with self._lock:
            self._ram.clear()
            self._disk.clear()
            self._dirty = True
            self._flush_disk()
        log.info("Cache cleared")

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "ram_entries":  len(self._ram),
                "disk_entries": len(self._disk),
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _normalise(query: str) -> str:
        return query.strip().lower()

    def _promote_to_ram(self, key: str, data: list) -> None:
        """Insert into RAM LRU, evict oldest if over capacity."""
        self._ram[key] = data
        self._ram.move_to_end(key)
        while len(self._ram) > _RAM_MAX:
            self._ram.popitem(last=False)

    def _evict_disk(self) -> None:
        """Keep disk cache under SEARCH_CACHE_MAX_SIZE entries."""
        if len(self._disk) <= SEARCH_CACHE_MAX_SIZE:
            return
        # Sort by timestamp; drop the oldest
        sorted_keys = sorted(self._disk, key=lambda k: self._disk[k]["ts"])
        to_remove   = len(self._disk) - SEARCH_CACHE_MAX_SIZE
        for k in sorted_keys[:to_remove]:
            del self._disk[k]
        self._dirty = True

    def _load_disk(self) -> None:
        try:
            if self._disk_path.exists():
                raw = self._disk_path.read_text(encoding="utf-8").strip()
                if not raw:
                    return  # empty file – treat as fresh cache
                self._disk = json.loads(raw)
                log.info("Loaded %d cached queries from disk", len(self._disk))
        except Exception as exc:
            log.warning("Could not load search cache: %s", exc)
            self._disk = {}

    def _flush_disk(self) -> None:
        if not self._dirty:
            return
        try:
            self._disk_path.write_text(
                json.dumps(self._disk, ensure_ascii=False, indent=None),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception as exc:
            log.error("Failed to write search cache: %s", exc)

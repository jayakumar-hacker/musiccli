"""
MusiCLI - Configuration & Constants
====================================
Central configuration file. Modify these to tune behaviour.
"""

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR       = Path.home() / ".musicli"
CACHE_DIR      = BASE_DIR / "cache"
PLAYLIST_DIR   = BASE_DIR / "playlists"
LOG_DIR        = BASE_DIR / "logs"
HISTORY_FILE   = BASE_DIR / "history.json"
SEARCH_CACHE   = BASE_DIR / "search_cache.json"

# Ensure dirs exist at import time
for _d in (BASE_DIR, CACHE_DIR, PLAYLIST_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Search ────────────────────────────────────────────────────────────────────
SEARCH_MAX_RESULTS      = 8          # results returned per query
SEARCH_CACHE_TTL_HOURS  = 24         # how long a cached query stays valid
SEARCH_CACHE_MAX_SIZE   = 500        # max number of queries in disk cache
YTDLP_SEARCH_TIMEOUT    = 20         # seconds before search gives up

# yt-dlp base options shared across services
YTDLP_BASE_OPTS = {
    "quiet":            True,
    "no_warnings":      True,
    "extract_flat":     True,         # faster – no full metadata on search
    "socket_timeout":   10,
    "retries":          2,
    "geo_bypass":       True,
}

# ── Playback ──────────────────────────────────────────────────────────────────
DEFAULT_VOLUME          = 80         # 0-100
FFPLAY_EXTRA_ARGS       = [
    "-nodisp",                        # headless
    "-hide_banner",
    "-loglevel", "quiet",
    "-vn",                            # no video
    "-autoexit",                      # exit when stream ends
]
# yt-dlp audio format preference (best quality, no video)
AUDIO_FORMAT            = "bestaudio/best"
AUDIO_CODEC_PREFERENCE  = ["opus", "vorbis", "aac", "mp3"]

PRELOAD_BUFFER_SECONDS  = 4          # seconds before track end to start preload
PRELOAD_ENABLED         = True

# ── History ───────────────────────────────────────────────────────────────────
HISTORY_MAX_ENTRIES     = 500

# ── UI ────────────────────────────────────────────────────────────────────────
STATUS_REFRESH_INTERVAL = 0.5        # seconds between status-bar refreshes
PROMPT_SYMBOL           = "♫ "

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL               = "INFO"     # DEBUG / INFO / WARNING / ERROR
LOG_FILE                = LOG_DIR / "musicli.log"
LOG_MAX_BYTES           = 5 * 1024 * 1024   # 5 MB
LOG_BACKUP_COUNT        = 2

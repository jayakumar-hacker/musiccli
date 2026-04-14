# MusiCLI 🎵

> A modular, high-performance terminal music streaming player built on **yt-dlp** + **ffplay**.

---

## Quick Start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install ffmpeg (provides ffplay)
#   Ubuntu/Debian:  sudo apt install ffmpeg
#   macOS:          brew install ffmpeg
#   Windows:        winget install ffmpeg

# 3. Run
python main.py
```

---

## Commands

| Command | Description |
|---|---|
| `search <query>` / `s <query>` | Search YouTube |
| `add <#>` | Add result to end of queue |
| `addnext <#>` | Add result as the very next track |
| `play` / `p` | Start / resume playback |
| `pause` / `pa` | Toggle pause |
| `next` / `n` | Skip to next track |
| `prev` / `b` | Go back to previous track |
| `stop` | Stop playback |
| `vol <0-100>` | Set volume |
| `queue` / `q` | Show playback queue |
| `remove <pos>` | Remove track from queue |
| `shuffle` | Shuffle remaining tracks |
| `goto <pos>` | Jump to queue position |
| `pl list` | List playlists |
| `pl create <name>` | Create a playlist |
| `pl show <name>` | Show playlist contents |
| `pl load <name>` | Load playlist into queue |
| `pl add <name> <#>` | Add search result to playlist |
| `pl remove <name> <#>` | Remove track from playlist |
| `pl delete <name>` | Delete playlist |
| `history` / `h` | Show recently played |
| `status` | Show current player status |
| `help` | Show full help |
| `quit` / `exit` | Exit |

---

## Architecture

```
musicli/
├── main.py               ← Entry point, dependency check, arg parsing
├── config.py             ← All tunable constants in one place
├── logger.py             ← Rotating file logger + optional stderr output
├── requirements.txt
│
├── core/                 ← Business logic, zero UI code
│   ├── models.py         ← Track, Playlist, HistoryEntry, PlayerState
│   ├── cache_manager.py  ← Two-tier (RAM LRU + JSON disk) search cache
│   ├── search_service.py ← yt-dlp wrapper, async-capable search
│   ├── queue_manager.py  ← Thread-safe ordered playback queue
│   ├── player_engine.py  ← ffplay subprocess lifecycle + preloader
│   ├── playlist_manager.py ← Persistent playlist CRUD (per-file JSON)
│   └── history_manager.py  ← Append-only play history
│
└── cli/                  ← Presentation layer
    ├── controller.py     ← Command parser + dispatcher (the REPL)
    └── display.py        ← Pure rendering: ANSI colour, tables, banners
```

### Module responsibilities

| Module | Does | Does NOT |
|---|---|---|
| `core/models.py` | Define shared data structures | Any I/O |
| `core/cache_manager.py` | Cache search results (RAM + disk) | Knows about yt-dlp |
| `core/search_service.py` | Query YouTube, resolve stream URLs | Touch the player |
| `core/queue_manager.py` | Maintain ordered track list | Play anything |
| `core/player_engine.py` | Spawn/kill ffplay, manage state | UI, search, playlists |
| `core/playlist_manager.py` | CRUD playlists on disk | Queue or playback |
| `core/history_manager.py` | Record + retrieve play history | Anything else |
| `cli/display.py` | Render to terminal | Hold any state |
| `cli/controller.py` | Parse commands, wire services | Business logic |

---

## Performance Highlights

### Search speed
- **RAM cache**: An OrderedDict LRU (64 entries) answers repeat queries in < 1 ms.
- **Disk cache**: JSON file cache (24-hour TTL, 500-entry cap) survives restarts.
- **Thread-pool**: Searches run in a `ThreadPoolExecutor`, keeping the REPL responsive.
- **`extract_flat=True`**: Skips per-video metadata during search, making yt-dlp ~3× faster.

### Playback latency
- **Preloading**: As soon as a track starts playing, the *next* track's stream URL is resolved in the background. When the track ends the URL is already waiting — no gap.
- **Direct pipe**: We pass the resolved HTTPS URL directly to ffplay (no intermediate download). ffplay starts buffering within ~1 s.

### Concurrency model
```
Main thread      ← REPL input loop (never blocks long)
search-N         ← Thread-pool workers for yt-dlp queries
player-loop      ← Dedicated thread: resolve → play → advance → repeat
preload-watchdog ← Daemon thread checking preload Future once/second
```
All shared state is protected by `threading.RLock`.

---

## Configuration

Edit `config.py` to tune:

- `SEARCH_MAX_RESULTS` – how many YouTube results per query
- `SEARCH_CACHE_TTL_HOURS` – how long cached queries are valid
- `DEFAULT_VOLUME` – startup volume (0-100)
- `PRELOAD_ENABLED` – toggle background preloading
- `LOG_LEVEL` – DEBUG / INFO / WARNING

---

## Data Storage

All data lives under `~/.musicli/`:

```
~/.musicli/
├── search_cache.json    ← Disk search cache
├── history.json         ← Play history
├── playlists/
│   ├── my_playlist.json
│   └── chill_vibes.json
└── logs/
    └── musicli.log
```

---

## Extending the System

The modular design makes adding features straightforward:

- **Web UI / API**: Swap `cli/controller.py` for a FastAPI server; all core services remain unchanged.
- **Multi-device**: Replace `PlayerEngine._run_ffplay()` with a network-streaming backend.
- **Spotify/SoundCloud**: Add `SpotifySearchService` implementing the same interface as `SearchService`.
- **Related songs**: Add a `RecommendationService` that calls YouTube's "related videos" endpoint and feeds results to `QueueManager`.

---

## Debugging

```bash
python main.py --debug      # verbose logs on stderr + log file
tail -f ~/.musicli/logs/musicli.log
```

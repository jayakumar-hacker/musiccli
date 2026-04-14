"""
MusiCLI – CLI Display Helpers
==============================
Pure rendering functions.  No state, no I/O side-effects beyond stdout.
All colour/ANSI escape codes are centralised here.
"""

from __future__ import annotations

import os
import shutil
import textwrap
from typing import Optional

from core.models import PlayerState, Track

# ── ANSI palette ─────────────────────────────────────────────────────────────
# Disable colour when stdout is not a tty (piped output, CI, etc.)
_USE_COLOUR = os.isatty(1)


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI escape only when colour is enabled."""
    if not _USE_COLOUR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str)    -> str: return _c("1",       t)
def dim(t: str)     -> str: return _c("2",       t)
def green(t: str)   -> str: return _c("32",      t)
def cyan(t: str)    -> str: return _c("36",      t)
def yellow(t: str)  -> str: return _c("33",      t)
def red(t: str)     -> str: return _c("31",      t)
def magenta(t: str) -> str: return _c("35",      t)
def blue(t: str)    -> str: return _c("34",      t)
def white(t: str)   -> str: return _c("97",      t)
def grey(t: str)    -> str: return _c("90",      t)

# State → colour mapping
_STATE_COLOUR = {
    PlayerState.PLAYING: green,
    PlayerState.PAUSED:  yellow,
    PlayerState.LOADING: cyan,
    PlayerState.IDLE:    grey,
    PlayerState.ERROR:   red,
    PlayerState.STOPPED: grey,
}

_STATE_ICON = {
    PlayerState.PLAYING: "▶",
    PlayerState.PAUSED:  "⏸",
    PlayerState.LOADING: "⏳",
    PlayerState.IDLE:    "⏹",
    PlayerState.ERROR:   "✗",
    PlayerState.STOPPED: "⏹",
}


def term_width() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def hr(char: str = "─") -> str:
    return dim(char * term_width())


# ── Banner ─────────────────────────────────────────────────────────────────────

def print_banner() -> None:
    w = term_width()
    lines = [
        "",
        cyan(bold(" ♫  MusiCLI ".center(w))),
        grey("YouTube Music Streaming · yt-dlp + ffplay".center(w)),
        grey(("Type " + bold("help") + " to list commands").center(w + 8)),
        "",
    ]
    print("\n".join(lines))


# ── Search results ─────────────────────────────────────────────────────────────

def print_search_results(tracks: list[Track], query: str = "") -> None:
    if not tracks:
        print(yellow("  No results found."))
        return

    header = f"  Search results{f' for \"{query}\"' if query else ''}"
    print(f"\n{bold(header)}")
    print(hr())
    for i, t in enumerate(tracks, 1):
        num     = grey(f" {i:2}.")
        title   = cyan(t.title[:55].ljust(55))
        artist  = magenta(f"  {t.artist[:28]}" if t.artist else "")
        dur     = dim(f"  [{t.duration_str}]")
        print(f"{num}  {title}{artist}{dur}")
    print(hr())


# ── Queue ──────────────────────────────────────────────────────────────────────

def print_queue(items: list[tuple[int, Track, bool]]) -> None:
    if not items:
        print(grey("  Queue is empty."))
        return
    print(f"\n{bold('  Queue')}")
    print(hr())
    for pos, track, is_current in items:
        icon  = green("▶ ") if is_current else "  "
        num   = bold(f"{pos:2}.") if is_current else grey(f"{pos:2}.")
        title = (cyan if is_current else white)(track.title[:55].ljust(55))
        dur   = dim(f"  [{track.duration_str}]")
        print(f"{icon}{num}  {title}{dur}")
    print(hr())


# ── Now playing ────────────────────────────────────────────────────────────────

def print_now_playing(state: PlayerState, track: Optional[Track], volume: int) -> None:
    colour = _STATE_COLOUR.get(state, grey)
    icon   = _STATE_ICON.get(state, "?")
    w      = term_width()

    print(f"\n{hr()}")
    if track:
        status = colour(f"  {icon}  {track.display_title}")
        vol    = dim(f"  🔊 {volume}%")
        dur    = dim(f"  ⏱  {track.duration_str}")
        right  = vol + dur
        pad    = max(0, w - len(status) - len(vol) - len(dur))
        print(status + " " * pad + right)
    else:
        print(colour(f"  {icon}  {state.name.title()}"))
    print(hr())


# ── Playlists ──────────────────────────────────────────────────────────────────

def print_playlists(names: list[str]) -> None:
    if not names:
        print(grey("  No playlists yet.  Use: pl create <name>"))
        return
    print(f"\n{bold('  Playlists')}")
    print(hr())
    for i, name in enumerate(names, 1):
        print(f"  {grey(str(i) + '.'):<10} {cyan(name)}")
    print(hr())


def print_playlist_tracks(tracks: list[Track], name: str) -> None:
    print(f"\n{bold(f'  Playlist: {name}')}")
    print(hr())
    if not tracks:
        print(grey("  (empty)"))
    for i, t in enumerate(tracks, 1):
        print(f"  {grey(f'{i:2}.')}  {cyan(t.title[:55].ljust(55))}  {dim(t.duration_str)}")
    print(hr())


# ── History ────────────────────────────────────────────────────────────────────

def print_history(entries) -> None:
    import datetime
    if not entries:
        print(grey("  No history yet."))
        return
    print(f"\n{bold('  Recent History')}")
    print(hr())
    for e in entries:
        ts    = datetime.datetime.fromtimestamp(e.played_at).strftime("%b %d %H:%M")
        title = cyan(e.track.title[:50].ljust(50))
        print(f"  {grey(ts)}  {title}")
    print(hr())


# ── Error / info ───────────────────────────────────────────────────────────────

def print_error(msg: str)   -> None: print(f"  {red('✗')}  {msg}")
def print_ok(msg: str)      -> None: print(f"  {green('✓')}  {msg}")
def print_info(msg: str)    -> None: print(f"  {cyan('ℹ')}  {msg}")
def print_warning(msg: str) -> None: print(f"  {yellow('⚠')}  {msg}")


# ── Help ───────────────────────────────────────────────────────────────────────

HELP_TEXT = """
{bold_h}Playback{r}
  play / p              Resume or start playback
  pause / pa            Pause current track
  next / n              Skip to next track
  prev / b              Go back to previous track
  stop                  Stop playback
  vol <0-100>           Set volume (e.g. vol 70)

{bold_h}Search{r}
  search <query>        Search YouTube (e.g. search lofi hip hop)
  s <query>             Shorthand for search

{bold_h}Queue{r}
  queue / q             Show current queue
  add <#>               Add search result #N to queue
  addnext <#>           Add as the very next track
  remove <pos>          Remove track at queue position
  clear                 Clear the entire queue
  goto <pos>            Jump to queue position
  shuffle               Shuffle remaining tracks

{bold_h}Playlists{r}
  pl list               List all playlists
  pl create <name>      Create a new playlist
  pl show <name>        Show tracks in a playlist
  pl load <name>        Load a playlist into the queue
  pl add <name> <#>     Add search result #N to playlist
  pl remove <name> <#>  Remove track #N from playlist
  pl delete <name>      Delete a playlist

{bold_h}History{r}
  history / h           Show recently played tracks

{bold_h}Other{r}
  status                Show current player status
  help                  Show this help text
  quit / exit           Exit MusiCLI
"""


def print_help() -> None:
    from cli.display import bold  # local import to avoid circular at module level
    formatted = HELP_TEXT.replace("{bold_h}", "\033[1;36m").replace("{r}", "\033[0m")
    print(formatted)

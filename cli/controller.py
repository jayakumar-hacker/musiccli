"""
MusiCLI – CLIController
========================
Parses raw text commands and dispatches to the appropriate service.

Design
------
* The controller is the only module that imports from *all* others.
* It keeps a reference to the last search results so the user can
  refer to them by index (e.g. "add 3").
* Input is read in the main thread; all blocking work is delegated to
  background threads so the prompt stays responsive.
* State callbacks from PlayerEngine update a shared status dict that
  is printed inline (not in a separate thread) to avoid terminal noise.
"""

from __future__ import annotations

import shlex
import sys
import threading
from typing import Optional

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(__file__)))

from core.models import PlayerState, Track
from core.cache_manager import CacheManager
from core.search_service import SearchService
from core.queue_manager import QueueManager
from core.player_engine import PlayerEngine
from core.playlist_manager import PlaylistManager
from core.history_manager import HistoryManager
from cli.display import (
    print_banner, print_error, print_ok, print_info, print_warning,
    print_search_results, print_queue, print_now_playing,
    print_playlists, print_playlist_tracks, print_history, print_help,
    bold, cyan, green, grey, yellow,
)
from config import PROMPT_SYMBOL
from logger import get_logger

log = get_logger("cli")


class CLIController:
    """
    Main command-line controller.  Call `run()` to start the REPL.
    """

    def __init__(self) -> None:
        # ── Instantiate services ───────────────────────────────────────────
        self._cache     = CacheManager()
        self._search    = SearchService(cache=self._cache)
        self._queue     = QueueManager()
        self._player    = PlayerEngine(self._queue, self._search)
        self._playlists = PlaylistManager()
        self._history   = HistoryManager()

        # ── Session state ──────────────────────────────────────────────────
        self._last_results: list[Track]  = []
        self._search_lock                = threading.Lock()
        self._running                    = True

        # Register callbacks
        self._player.subscribe(self._on_player_state_change)
        self._queue.subscribe(self._on_queue_change)

    # ── Entry point ────────────────────────────────────────────────────────────

    def run(self) -> None:
        print_banner()
        print_info("Type 'help' for a list of commands.")
        while self._running:
            try:
                raw = input(f"\n{PROMPT_SYMBOL}").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                self._cmd_quit([])
                break
            if not raw:
                continue
            self._dispatch(raw)
        print_info("Goodbye! ♫")
        self._player.shutdown()

    # ── Dispatcher ─────────────────────────────────────────────────────────────

    def _dispatch(self, raw: str) -> None:
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()
        if not parts:
            return

        cmd  = parts[0].lower()
        args = parts[1:]

        route = {
            # Playback
            "play":    self._cmd_play,
            "p":       self._cmd_play,
            "pause":   self._cmd_pause,
            "pa":      self._cmd_pause,
            "resume":  self._cmd_resume,
            "next":    self._cmd_next,
            "n":       self._cmd_next,
            "prev":    self._cmd_prev,
            "b":       self._cmd_prev,
            "stop":    self._cmd_stop,
            "vol":     self._cmd_volume,
            "volume":  self._cmd_volume,
            # Search
            "search":  self._cmd_search,
            "s":       self._cmd_search,
            # Queue
            "queue":   self._cmd_queue,
            "q":       self._cmd_queue,
            "add":     self._cmd_add,
            "addnext": self._cmd_addnext,
            "remove":  self._cmd_remove,
            "clear":   self._cmd_clear,
            "goto":    self._cmd_goto,
            "shuffle": self._cmd_shuffle,
            # Playlists
            "pl":      self._cmd_playlist,
            "playlist":self._cmd_playlist,
            # History
            "history": self._cmd_history,
            "h":       self._cmd_history,
            # Meta
            "status":  self._cmd_status,
            "help":    self._cmd_help,
            "quit":    self._cmd_quit,
            "exit":    self._cmd_quit,
        }

        handler = route.get(cmd)
        if handler:
            try:
                handler(args)
            except Exception as exc:
                print_error(f"Command error: {exc}")
                log.exception("Unhandled command error in '%s'", cmd)
        else:
            # Treat unknown input as a search query
            self._cmd_search([cmd] + args)

    # ── Playback commands ──────────────────────────────────────────────────────

    def _cmd_play(self, args: list[str]) -> None:
        if self._queue.is_empty:
            print_warning("Queue is empty.  Search for something first.")
            return
        state = self._player.state
        if state == PlayerState.PAUSED:
            self._player.resume()
        else:
            self._player.play()

    def _cmd_pause(self, args: list[str]) -> None:
        state = self._player.state
        if state == PlayerState.PLAYING:
            self._player.pause()
        elif state == PlayerState.PAUSED:
            self._player.resume()
            print_ok("Resumed")
        else:
            print_warning("Nothing is playing.")

    def _cmd_resume(self, args: list[str]) -> None:
        self._player.resume()

    def _cmd_next(self, args: list[str]) -> None:
        self._player.next()

    def _cmd_prev(self, args: list[str]) -> None:
        self._player.previous()

    def _cmd_stop(self, args: list[str]) -> None:
        self._player.stop()
        print_ok("Stopped.")

    def _cmd_volume(self, args: list[str]) -> None:
        if not args:
            print_info(f"Current volume: {self._player.volume}%")
            return
        try:
            v = int(args[0])
        except ValueError:
            print_error("Usage: vol <0-100>")
            return
        self._player.set_volume(v)
        print_ok(f"Volume set to {self._player.volume}%")

    # ── Search commands ────────────────────────────────────────────────────────

    def _cmd_search(self, args: list[str]) -> None:
        if not args:
            print_error("Usage: search <query>")
            return
        query = " ".join(args)
        print_info(f"Searching for \"{query}\" …")

        # Run in background thread, block here and print when ready
        # (short searches finish in < 1 s from cache)
        future = self._search.search_async(query)
        try:
            results = future.result(timeout=30)
        except Exception as exc:
            print_error(f"Search failed: {exc}")
            return

        with self._search_lock:
            self._last_results = results

        print_search_results(results, query)
        if results:
            print_info("Use 'add <#>' to queue a track, or 'play' after adding.")

    # ── Queue commands ─────────────────────────────────────────────────────────

    def _cmd_queue(self, args: list[str]) -> None:
        print_queue(self._queue.list_tracks())

    def _cmd_add(self, args: list[str]) -> None:
        track = self._resolve_result(args)
        if track:
            self._queue.add(track)
            print_ok(f"Added to queue: {track.title}")
            if self._player.state == PlayerState.IDLE:
                print_info("Type 'play' or 'p' to start.")

    def _cmd_addnext(self, args: list[str]) -> None:
        track = self._resolve_result(args)
        if track:
            self._queue.add_next(track)
            print_ok(f"Play-next: {track.title}")

    def _cmd_remove(self, args: list[str]) -> None:
        pos = self._parse_int(args, "remove <position>")
        if pos is None:
            return
        removed = self._queue.remove(pos)
        if removed:
            print_ok(f"Removed: {removed.title}")
        else:
            print_error(f"No track at position {pos}")

    def _cmd_clear(self, args: list[str]) -> None:
        self._player.stop()
        self._queue.clear()
        print_ok("Queue cleared.")

    def _cmd_goto(self, args: list[str]) -> None:
        pos = self._parse_int(args, "goto <position>")
        if pos is None:
            return
        track = self._queue.go_to(pos)
        if track:
            self._player.play()
        else:
            print_error(f"No track at position {pos}")

    def _cmd_shuffle(self, args: list[str]) -> None:
        self._queue.shuffle()
        print_ok("Shuffled remaining tracks.")

    # ── Playlist commands ──────────────────────────────────────────────────────

    def _cmd_playlist(self, args: list[str]) -> None:
        if not args:
            self._cmd_playlist(["list"])
            return
        sub  = args[0].lower()
        rest = args[1:]

        if sub == "list":
            print_playlists(self._playlists.list_playlists())

        elif sub == "create":
            if not rest:
                print_error("Usage: pl create <n>"); return
            name = " ".join(rest)
            try:
                self._playlists.create(name)
                print_ok(f"Created playlist '{name}'")
            except ValueError as e:
                print_error(str(e))

        elif sub == "show":
            if not rest:
                print_error("Usage: pl show <n>"); return
            name = " ".join(rest)
            pl   = self._playlists.load(name)
            if pl:
                print_playlist_tracks(pl.tracks, pl.name)
            else:
                print_error(f"Playlist '{name}' not found")

        elif sub == "load":
            if not rest:
                print_error("Usage: pl load <n>"); return
            name  = " ".join(rest)
            added = self._playlists.load_into_queue(name, self._queue)
            if added:
                print_ok(f"Loaded {added} tracks from '{name}' into queue")
            else:
                print_error(f"Playlist '{name}' not found or empty")

        elif sub in ("add", "addtrack"):
            # pl add <playlist> <#N>
            if len(rest) < 2:
                print_error("Usage: pl add <n> <#>"); return
            *name_parts, num_str = rest
            pl_name = " ".join(name_parts)
            track   = self._resolve_result([num_str])
            if track:
                try:
                    self._playlists.add_track(pl_name, track)
                    print_ok(f"Added '{track.title}' to '{pl_name}'")
                except Exception as e:
                    print_error(str(e))

        elif sub == "remove":
            if len(rest) < 2:
                print_error("Usage: pl remove <n> <#>"); return
            *name_parts, num_str = rest
            pl_name = " ".join(name_parts)
            try:
                pos = int(num_str)
            except ValueError:
                print_error("Position must be a number"); return
            removed = self._playlists.remove_track(pl_name, pos)
            if removed:
                print_ok(f"Removed '{removed.title}' from '{pl_name}'")
            else:
                print_error("Track not found")

        elif sub == "delete":
            if not rest:
                print_error("Usage: pl delete <n>"); return
            name = " ".join(rest)
            if self._playlists.delete(name):
                print_ok(f"Deleted playlist '{name}'")
            else:
                print_error(f"Playlist '{name}' not found")

        else:
            print_error(f"Unknown playlist sub-command: {sub}")

    # ── History / Status / Help ────────────────────────────────────────────────

    def _cmd_history(self, args: list[str]) -> None:
        print_history(self._history.recent(20))

    def _cmd_status(self, args: list[str]) -> None:
        print_now_playing(
            self._player.state,
            self._player.current_track,
            self._player.volume,
        )
        size = self._queue.size
        if size:
            print_info(f"{size} track(s) in queue")

    def _cmd_help(self, args: list[str]) -> None:
        print_help()

    def _cmd_quit(self, args: list[str]) -> None:
        self._running = False

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _on_player_state_change(
        self, state: PlayerState, track: Optional[Track]
    ) -> None:
        if state == PlayerState.PLAYING and track:
            self._history.record(track)
        # Print state change inline (non-intrusive single line)
        if state == PlayerState.PLAYING and track:
            print(f"\n  {green('▶')}  {cyan(track.display_title)}")
        elif state == PlayerState.PAUSED:
            print(f"\n  {yellow('⏸')}  Paused")
        elif state == PlayerState.IDLE:
            print(f"\n  {grey('⏹')}  Queue finished")
        elif state == PlayerState.LOADING:
            print(f"\n  {cyan('⏳')}  Loading …")
        elif state == PlayerState.ERROR:
            print(f"\n  {yellow('⚠')}  Skipping errored track…")

    def _on_queue_change(self) -> None:
        pass   # Could print live queue size; kept silent to reduce noise

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _resolve_result(self, args: list[str]) -> Optional[Track]:
        """Parse an index string and look up in last_results."""
        if not args:
            print_error("Provide a result number (e.g. add 3)")
            return None
        try:
            n = int(args[0])
        except ValueError:
            print_error("Result number must be an integer")
            return None
        with self._search_lock:
            results = self._last_results
        if not (1 <= n <= len(results)):
            print_error(f"No result #{n}. Run a search first.")
            return None
        return results[n - 1]

    def _parse_int(self, args: list[str], usage: str) -> Optional[int]:
        if not args:
            print_error(f"Usage: {usage}")
            return None
        try:
            return int(args[0])
        except ValueError:
            print_error("Expected an integer")
            return None

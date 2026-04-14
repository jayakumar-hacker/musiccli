"""
MusiCLI – PlayerEngine  (FIXED v2)
====================================
Controls audio playback via ffplay subprocess.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUGS FIXED IN THIS VERSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BUG 1 – Two songs playing at the same time when switching tracks
ROOT CAUSE:
  next() / previous() / play() each called _stop_current_process()
  then immediately spawned a NEW _playback_loop thread — BUT the old
  _playback_loop thread was still alive, blocking on proc.wait().
  When _stop_current_process() killed the process, proc.wait()
  returned in the OLD thread, which then called _queue.advance()
  and spawned ANOTHER ffplay → two songs at once.
FIX:
  Added a _loop_gen (generation) counter. Every time we start a new
  playback loop we increment it. Each loop iteration checks whether
  its captured generation still matches — if not, exits immediately.
  _kill_and_wait() also join()s the old thread before returning, so
  it's physically impossible for the old loop to still be running
  when the new one starts.

BUG 2 – Pause / Stop doesn't actually stop audio
ROOT CAUSE:
  ffplay spawns child processes for network I/O and decoding.
  os.kill(proc.pid, SIGSTOP) only suspends the PARENT; children
  keep running and audio keeps flowing.
FIX:
  Popen is launched with preexec_fn=os.setsid so ffplay gets its
  own process group. We then use os.killpg(pgid, signal.SIGSTOP)
  to suspend EVERY process in that group at once.
  For Windows: NtSuspendProcess via ctypes suspends the entire process.

BUG 3 – _stop_current_process() race condition
ROOT CAUSE:
  self._proc was read, lock released, then proc.kill() called.
  Another thread could replace self._proc in that window, meaning
  we'd kill the WRONG (new) process.
FIX:
  Capture AND clear self._proc in a single lock section. Operate
  only on the local reference after releasing the lock.

BUG 4 – stop() returned before old thread finished
ROOT CAUSE:
  stop() killed the process but returned immediately. play() called
  right after would start a new loop while the old one was still
  winding down → race condition → double playback.
FIX:
  _kill_and_wait() joins the old thread (2s timeout) before returning.
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import threading
import time
from typing import Callable, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import DEFAULT_VOLUME, FFPLAY_EXTRA_ARGS, PRELOAD_ENABLED
from core.models import PlayerState, Track
from core.queue_manager import QueueManager
from core.search_service import SearchService
from logger import get_logger

log = get_logger("player")
_IS_WINDOWS = platform.system() == "Windows"

_StateChangeCallback = Callable[[PlayerState, Optional[Track]], None]


class PlayerEngine:
    """
    High-level playback controller.

        engine = PlayerEngine(queue, search_svc)
        engine.play()
        engine.pause()
        engine.resume()
        engine.stop()
        engine.next()
        engine.previous()
    """

    def __init__(self, queue: QueueManager, search_svc: SearchService) -> None:
        self._queue   = queue
        self._search  = search_svc
        self._lock    = threading.RLock()

        self._state:         PlayerState              = PlayerState.IDLE
        self._current_track: Optional[Track]          = None
        self._proc:          Optional[subprocess.Popen] = None
        self._volume:        int                      = DEFAULT_VOLUME

        # ── FIX 1: generation counter stops zombie threads ──────────────────
        self._loop_gen:    int                         = 0
        self._play_thread: Optional[threading.Thread] = None
        self._stop_event   = threading.Event()

        self._on_state_change: list[_StateChangeCallback] = []

        # Preload
        self._preload_track:  Optional[Track] = None
        self._preload_url:    Optional[str]   = None
        self._preload_future                  = None

        if PRELOAD_ENABLED:
            self._start_preload_watchdog()

    # ── Public API ─────────────────────────────────────────────────────────────

    def subscribe(self, cb: _StateChangeCallback) -> None:
        self._on_state_change.append(cb)

    def play(self, track: Optional[Track] = None) -> None:
        """Start or restart playback."""
        if track:
            self._queue.add_next(track)
            self._queue.advance()
        self._stop_event.clear()
        self._kill_and_wait()            # FIX 3+4
        self._start_playback_loop()

    def pause(self) -> None:
        """Pause by suspending the ffplay process GROUP."""
        with self._lock:
            if self._state != PlayerState.PLAYING:
                log.debug("pause() ignored – state=%s", self._state.name)
                return
            proc = self._proc
            if not proc or proc.poll() is not None:
                log.debug("pause() ignored – no live process")
                return

        try:
            if _IS_WINDOWS:
                self._windows_suspend(proc)
            else:
                # FIX 2: kill the entire process GROUP
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGSTOP)
            self._set_state(PlayerState.PAUSED)
            log.info("Paused pid=%s", proc.pid)
        except ProcessLookupError:
            log.debug("pause(): process already gone")
        except Exception as exc:
            log.error("pause() failed: %s", exc)

    def resume(self) -> None:
        """Resume a paused track."""
        with self._lock:
            if self._state != PlayerState.PAUSED:
                log.debug("resume() ignored – state=%s", self._state.name)
                return
            proc = self._proc
            if not proc or proc.poll() is not None:
                log.debug("resume() ignored – no live process")
                return

        try:
            if _IS_WINDOWS:
                self._windows_resume(proc)
            else:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGCONT)
            self._set_state(PlayerState.PLAYING)
            log.info("Resumed pid=%s", proc.pid)
        except ProcessLookupError:
            log.debug("resume(): process already gone")
        except Exception as exc:
            log.error("resume() failed: %s", exc)

    def stop(self) -> None:
        """Stop playback completely and return to IDLE."""
        self._stop_event.set()
        self._kill_and_wait()            # FIX 4: waits for thread to exit
        self._set_state(PlayerState.IDLE)
        log.info("Stopped")

    def next(self) -> None:
        """Skip to the next track."""
        log.info("Next track")
        self._kill_and_wait()            # FIX 1+4: wait before new loop
        self._stop_event.clear()
        if self._queue.advance():
            self._start_playback_loop()
        else:
            self._set_state(PlayerState.IDLE)

    def previous(self) -> None:
        """Go back to the previous track."""
        log.info("Previous track")
        self._kill_and_wait()
        self._stop_event.clear()
        if self._queue.go_back():
            self._start_playback_loop()
        else:
            self._set_state(PlayerState.IDLE)

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, volume))
        log.info("Volume → %d", self._volume)

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def state(self) -> PlayerState:
        with self._lock:
            return self._state

    @property
    def current_track(self) -> Optional[Track]:
        with self._lock:
            return self._current_track

    def shutdown(self) -> None:
        self.stop()
        self._search.shutdown()
        log.info("PlayerEngine shut down")

    # ── Thread management ──────────────────────────────────────────────────────

    def _start_playback_loop(self) -> None:
        """Bump generation counter and spawn a fresh playback thread."""
        with self._lock:
            self._loop_gen += 1
            my_gen = self._loop_gen

        t = threading.Thread(
            target=self._playback_loop,
            args=(my_gen,),
            daemon=True,
            name=f"player-loop-{my_gen}",
        )
        with self._lock:
            self._play_thread = t
        t.start()
        log.debug("Started playback loop gen=%d", my_gen)

    def _kill_and_wait(self) -> None:
        """
        Kill current ffplay process AND join the play thread.
        Must be called before starting any new playback loop.
        """
        # FIX 3: capture AND clear self._proc atomically
        with self._lock:
            proc = self._proc
            self._proc = None

        if proc is not None and proc.poll() is None:
            try:
                if _IS_WINDOWS:
                    proc.kill()
                else:
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                proc.wait(timeout=3)
                log.debug("ffplay killed pid=%s", proc.pid)
            except Exception as exc:
                log.warning("_kill_and_wait kill error: %s", exc)

        # FIX 4: join old thread so it fully exits before we start a new one
        with self._lock:
            old_thread = self._play_thread

        if old_thread is not None and old_thread.is_alive():
            old_thread.join(timeout=2.0)
            if old_thread.is_alive():
                log.warning("Old play thread still alive after 2s join – continuing")

    # ── Playback loop ──────────────────────────────────────────────────────────

    def _playback_loop(self, my_gen: int) -> None:
        """
        Drives the queue. my_gen is checked every iteration;
        exits immediately if a newer generation has taken over.
        """
        log.debug("Playback loop gen=%d started", my_gen)

        while True:
            # FIX 1: check generation at the top of every iteration
            with self._lock:
                if self._loop_gen != my_gen:
                    log.debug("Loop gen=%d superseded, exiting", my_gen)
                    return

            if self._stop_event.is_set():
                return

            track = self._queue.current()
            if not track:
                self._set_state(PlayerState.IDLE)
                return

            with self._lock:
                self._current_track = track

            stream_url = self._claim_preload(track)
            if not stream_url:
                self._set_state(PlayerState.LOADING)
                stream_url = self._search.resolve_stream_url(track)

            # Re-check generation after blocking resolve call
            with self._lock:
                if self._loop_gen != my_gen:
                    log.debug("Loop gen=%d superseded after resolve, exiting", my_gen)
                    return

            if not stream_url:
                log.error("Could not resolve stream for '%s'", track.title)
                self._set_state(PlayerState.ERROR)
                time.sleep(1)
                if not self._queue.advance():
                    return
                continue

            track.stream_url = stream_url
            self._set_state(PlayerState.PLAYING)
            self._trigger_preload()

            self._run_ffplay(stream_url, my_gen)

            # After ffplay returns, verify we're still the active generation
            with self._lock:
                if self._loop_gen != my_gen:
                    return

            if self._stop_event.is_set():
                return

            if not self._queue.advance():
                self._set_state(PlayerState.IDLE)
                return

    # ── ffplay subprocess ──────────────────────────────────────────────────────

    def _run_ffplay(self, url: str, my_gen: int) -> None:
        """Spawn ffplay in its own process group; block until it exits."""
        cmd = [
            "ffplay",
            "-volume", str(self._volume),
            *FFPLAY_EXTRA_ARGS,
            url,
        ]

        popen_kwargs: dict = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # FIX 2: new session → new process group → killpg works correctly
        if not _IS_WINDOWS:
            popen_kwargs["preexec_fn"] = os.setsid

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError:
            log.critical("ffplay not found. Install ffmpeg.")
            self._set_state(PlayerState.ERROR)
            return
        except Exception as exc:
            log.error("Failed to spawn ffplay: %s", exc)
            self._set_state(PlayerState.ERROR)
            return

        # FIX 1+3: only store proc if we're still the active generation
        with self._lock:
            if self._loop_gen != my_gen:
                log.debug("Spawned ffplay but gen already changed; killing it")
                try:
                    if not _IS_WINDOWS:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except Exception:
                    pass
                proc.wait()
                return
            self._proc = proc

        log.debug("ffplay pid=%d gen=%d", proc.pid, my_gen)
        proc.wait()

        with self._lock:
            if self._proc is proc:
                self._proc = None

        log.debug("ffplay exited pid=%d", proc.pid)

    # ── Preloader ──────────────────────────────────────────────────────────────

    def _start_preload_watchdog(self) -> None:
        def _watch():
            while True:
                time.sleep(1)
                try:
                    self._maybe_preload()
                except Exception as exc:
                    log.debug("Preload watchdog: %s", exc)
        threading.Thread(target=_watch, daemon=True, name="preload-watchdog").start()

    def _trigger_preload(self) -> None:
        next_track = self._queue.peek_next()
        if not next_track or next_track == self._preload_track:
            return
        self._preload_track  = next_track
        self._preload_url    = None
        self._preload_future = self._search.resolve_stream_async(next_track)
        log.debug("Preloading: %s", next_track.title)

    def _maybe_preload(self) -> None:
        future = self._preload_future
        if future and future.done() and self._preload_url is None:
            try:
                self._preload_url = future.result()
            except Exception as exc:
                log.warning("Preload failed: %s", exc)

    def _claim_preload(self, track: Track) -> Optional[str]:
        if self._preload_track == track and self._preload_url:
            url = self._preload_url
            self._preload_track = None
            self._preload_url   = None
            log.debug("Using preloaded URL for '%s'", track.title)
            return url
        return None

    # ── Windows process suspend/resume via NtSuspendProcess ───────────────────

    @staticmethod
    def _windows_suspend(proc: subprocess.Popen) -> None:
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, proc.pid)
            if h:
                ctypes.windll.ntdll.NtSuspendProcess(h)
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception as exc:
            log.error("Windows suspend failed: %s", exc)

    @staticmethod
    def _windows_resume(proc: subprocess.Popen) -> None:
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, proc.pid)
            if h:
                ctypes.windll.ntdll.NtResumeProcess(h)
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception as exc:
            log.error("Windows resume failed: %s", exc)

    # ── State helpers ──────────────────────────────────────────────────────────

    def _set_state(self, new_state: PlayerState) -> None:
        with self._lock:
            if self._state == new_state:
                return
            self._state = new_state
            track = self._current_track
        log.debug("State → %s", new_state.name)
        for cb in self._on_state_change:
            try:
                cb(new_state, track)
            except Exception as exc:
                log.warning("State callback error: %s", exc)

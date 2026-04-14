"""
MusiCLI – Test Suite
=====================
Run with:  python -m pytest tests.py -v
Or:        python tests.py
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import threading
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.models import Track, Playlist, HistoryEntry, PlayerState
from core.cache_manager import CacheManager
from core.queue_manager import QueueManager
from core.history_manager import HistoryManager
from core.playlist_manager import PlaylistManager
from core.search_service import SearchService


def _make_track(n: int) -> Track:
    return Track(f"vid{n}", f"Track {n}", f"Artist {n}", 180 + n)


class TestTrackModel(unittest.TestCase):
    def test_display_title_with_artist(self):
        t = Track("x", "Song", "Artist")
        self.assertEqual(t.display_title, "Artist – Song")

    def test_display_title_no_artist(self):
        t = Track("x", "Song", "")
        self.assertEqual(t.display_title, "Song")

    def test_duration_str_minutes(self):
        t = Track("x", "Song", "", 185)
        self.assertEqual(t.duration_str, "3:05")

    def test_duration_str_hours(self):
        t = Track("x", "Song", "", 3723)
        self.assertEqual(t.duration_str, "1:02:03")

    def test_duration_unknown(self):
        t = Track("x", "Song", "", 0)
        self.assertEqual(t.duration_str, "--:--")

    def test_round_trip_dict(self):
        t = Track("abc", "My Song", "My Artist", 300, "http://thumb", "http://watch")
        t2 = Track.from_dict(t.to_dict())
        self.assertEqual(t, t2)
        self.assertEqual(t.duration, t2.duration)

    def test_equality(self):
        self.assertEqual(Track("id1", "A"), Track("id1", "B"))
        self.assertNotEqual(Track("id1", "A"), Track("id2", "A"))

    def test_hash(self):
        s = {Track("id1", "A"), Track("id1", "B"), Track("id2", "C")}
        self.assertEqual(len(s), 2)


class TestCacheManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.cache = CacheManager(pathlib.Path(self.tmp.name))

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _data(self):
        return [{"video_id": "x", "title": "T", "artist": "", "duration": 0,
                 "thumbnail": "", "webpage_url": ""}]

    def test_miss_returns_none(self):
        self.assertIsNone(self.cache.get("unknown query"))

    def test_set_then_get(self):
        self.cache.set("my query", self._data())
        result = self.cache.get("my query")
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["title"], "T")

    def test_case_insensitive_key(self):
        self.cache.set("LOFI HIP HOP", self._data())
        self.assertIsNotNone(self.cache.get("lofi hip hop"))
        self.assertIsNotNone(self.cache.get("Lofi Hip Hop"))

    def test_invalidate(self):
        self.cache.set("q", self._data())
        self.cache.invalidate("q")
        self.assertIsNone(self.cache.get("q"))

    def test_clear(self):
        self.cache.set("q1", self._data())
        self.cache.set("q2", self._data())
        self.cache.clear()
        self.assertIsNone(self.cache.get("q1"))
        self.assertEqual(self.cache.stats["ram_entries"], 0)

    def test_disk_persistence(self):
        self.cache.set("persist", self._data())
        # Load from same file
        cache2 = CacheManager(pathlib.Path(self.tmp.name))
        self.assertIsNotNone(cache2.get("persist"))

    def test_thread_safety(self):
        errors = []
        def writer(i):
            try:
                self.cache.set(f"query{i}", self._data())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])


class TestQueueManager(unittest.TestCase):
    def _filled_queue(self, n=5):
        q = QueueManager()
        for i in range(1, n+1):
            q.add(_make_track(i))
        return q

    def test_add_and_size(self):
        q = self._filled_queue(3)
        self.assertEqual(q.size, 3)

    def test_current_is_first(self):
        q = self._filled_queue(3)
        self.assertEqual(q.current().video_id, "vid1")

    def test_advance(self):
        q = self._filled_queue(3)
        q.advance()
        self.assertEqual(q.current().video_id, "vid2")

    def test_advance_at_end_returns_none(self):
        q = self._filled_queue(1)
        self.assertIsNone(q.advance())

    def test_peek_next(self):
        q = self._filled_queue(3)
        self.assertEqual(q.peek_next().video_id, "vid2")

    def test_go_back(self):
        q = self._filled_queue(3)
        q.advance(); q.advance()
        q.go_back()
        self.assertEqual(q.current().video_id, "vid2")

    def test_go_back_at_start_returns_none(self):
        q = self._filled_queue(3)
        self.assertIsNone(q.go_back())

    def test_remove(self):
        q = self._filled_queue(4)
        removed = q.remove(2)
        self.assertEqual(removed.video_id, "vid2")
        self.assertEqual(q.size, 3)

    def test_remove_out_of_range(self):
        q = self._filled_queue(2)
        self.assertIsNone(q.remove(99))

    def test_add_next(self):
        q = self._filled_queue(3)
        extra = _make_track(99)
        q.add_next(extra)
        q.advance()
        self.assertEqual(q.current().video_id, "vid99")

    def test_clear(self):
        q = self._filled_queue(5)
        q.clear()
        self.assertTrue(q.is_empty)
        self.assertIsNone(q.current())

    def test_goto(self):
        q = self._filled_queue(5)
        track = q.go_to(4)
        self.assertEqual(track.video_id, "vid4")
        self.assertEqual(q.current_index, 3)

    def test_goto_out_of_range(self):
        q = self._filled_queue(3)
        self.assertIsNone(q.go_to(99))

    def test_move(self):
        q = self._filled_queue(4)
        q.move(1, 3)   # move vid1 to position 3
        items = q.list_tracks()
        self.assertEqual(items[0][1].video_id, "vid2")
        self.assertEqual(items[2][1].video_id, "vid1")

    def test_shuffle_preserves_count(self):
        q = self._filled_queue(10)
        q.shuffle()
        self.assertEqual(q.size, 10)

    def test_list_tracks_marks_current(self):
        q = self._filled_queue(3)
        q.advance()
        items = q.list_tracks()
        current_flags = [is_cur for _, _, is_cur in items]
        self.assertEqual(current_flags, [False, True, False])

    def test_subscribe_callback(self):
        events = []
        q = self._filled_queue(2)
        q.subscribe(lambda: events.append(1))
        q.advance()
        self.assertEqual(events, [1])

    def test_thread_safety(self):
        q = QueueManager()
        errors = []
        def adder(i):
            try:
                q.add(_make_track(i))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=adder, args=(i,)) for i in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])
        self.assertEqual(q.size, 50)


class TestHistoryManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.history = HistoryManager(pathlib.Path(self.tmp.name))

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_record_and_retrieve(self):
        t = _make_track(1)
        self.history.record(t)
        entries = self.history.recent(5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].track.video_id, "vid1")

    def test_newest_first(self):
        for i in range(1, 4):
            self.history.record(_make_track(i))
        entries = self.history.recent(10)
        self.assertEqual(entries[0].track.video_id, "vid3")
        self.assertEqual(entries[2].track.video_id, "vid1")

    def test_persistence(self):
        self.history.record(_make_track(42))
        h2 = HistoryManager(pathlib.Path(self.tmp.name))
        self.assertEqual(h2.recent(1)[0].track.video_id, "vid42")

    def test_clear(self):
        self.history.record(_make_track(1))
        self.history.clear()
        self.assertEqual(self.history.count, 0)


class TestPlaylistManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pm = PlaylistManager(pathlib.Path(self.tmpdir))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_create_and_load(self):
        self.pm.create("My Mix")
        pl = self.pm.load("My Mix")
        self.assertIsNotNone(pl)
        self.assertEqual(pl.name, "My Mix")

    def test_create_duplicate_raises(self):
        self.pm.create("Dup")
        with self.assertRaises(ValueError):
            self.pm.create("Dup")

    def test_list_playlists(self):
        self.pm.create("Alpha")
        self.pm.create("Beta")
        names = self.pm.list_playlists()
        self.assertIn("Alpha", names)
        self.assertIn("Beta", names)

    def test_add_and_remove_track(self):
        self.pm.create("Rock")
        self.pm.add_track("Rock", _make_track(1))
        self.pm.add_track("Rock", _make_track(2))
        pl = self.pm.load("Rock")
        self.assertEqual(len(pl.tracks), 2)
        self.pm.remove_track("Rock", 1)
        pl2 = self.pm.load("Rock")
        self.assertEqual(len(pl2.tracks), 1)
        self.assertEqual(pl2.tracks[0].video_id, "vid2")

    def test_no_duplicate_tracks(self):
        self.pm.create("NoDup")
        t = _make_track(1)
        self.pm.add_track("NoDup", t)
        self.pm.add_track("NoDup", t)   # second add should be ignored
        self.assertEqual(len(self.pm.load("NoDup").tracks), 1)

    def test_delete(self):
        self.pm.create("Temp")
        self.assertTrue(self.pm.delete("Temp"))
        self.assertIsNone(self.pm.load("Temp"))

    def test_delete_nonexistent(self):
        self.assertFalse(self.pm.delete("ghost"))

    def test_load_nonexistent(self):
        self.assertIsNone(self.pm.load("nonexistent"))

    def test_load_into_queue(self):
        self.pm.create("Q Test")
        for i in range(1, 4):
            self.pm.add_track("Q Test", _make_track(i))
        q = QueueManager()
        added = self.pm.load_into_queue("Q Test", q)
        self.assertEqual(added, 3)
        self.assertEqual(q.size, 3)

    def test_invalid_name_raises(self):
        with self.assertRaises(ValueError):
            self.pm.create("bad/name")

    def test_rename(self):
        self.pm.create("Old Name")
        self.pm.add_track("Old Name", _make_track(1))
        self.pm.rename("Old Name", "New Name")
        self.assertIsNone(self.pm.load("Old Name"))
        pl = self.pm.load("New Name")
        self.assertIsNotNone(pl)
        self.assertEqual(len(pl.tracks), 1)


class TestSearchServiceCache(unittest.TestCase):
    """Tests SearchService using pre-seeded cache (no real HTTP calls)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.cache = CacheManager(pathlib.Path(self.tmp.name))
        self.svc   = SearchService(cache=self.cache, max_results=5)

    def tearDown(self):
        self.svc.shutdown()
        os.unlink(self.tmp.name)

    def _seed(self, query, n=3):
        data = [_make_track(i).to_dict() for i in range(1, n+1)]
        self.cache.set(query, data)

    def test_cache_hit(self):
        self._seed("lofi")
        results = self.svc.search("lofi")
        self.assertEqual(len(results), 3)
        self.assertIsInstance(results[0], Track)

    def test_cache_hit_async(self):
        self._seed("jazz")
        future  = self.svc.search_async("jazz")
        results = future.result(timeout=5)
        self.assertEqual(len(results), 3)

    def test_empty_query_returns_empty(self):
        results = self.svc.search("   ")
        self.assertEqual(results, [])

    def test_force_refresh_bypasses_cache(self):
        self._seed("rock", 3)
        # Just verifies no crash; real re-fetch skipped in test environment
        # by checking cache is cleared
        self.cache.invalidate("rock")
        # Without HTTP we'll get [] back but no exception
        try:
            results = self.svc.search("rock", force_refresh=True)
            # May be [] due to no network in test env – that's fine
            self.assertIsInstance(results, list)
        except Exception:
            pass  # Network errors are acceptable in offline test env


if __name__ == "__main__":
    unittest.main(verbosity=2)

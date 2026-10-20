"""The world clock: one SQLite connection, one lock, exact day close and pause on downtime.

The server must run as a single process: the lock lives in memory.
"""

import asyncio
import contextlib
import threading
import time

from . import config, game
from . import db as dbmod


class World:
    def __init__(self, path=config.DB_PATH, day_seconds=config.DAY_SECONDS, now=time.time):
        self.db = dbmod.connect(path)
        self.day_seconds = day_seconds
        self.now = now
        self.lock = threading.Lock()
        with self.lock:
            row = self.db.execute("SELECT * FROM world").fetchone()
            t = self.now()
            if row is None:
                self.db.execute(
                    "INSERT INTO world (id, day, next_close_at, heartbeat) VALUES (1, 1, ?, ?)",
                    (t + day_seconds, t),
                )
            self._tick(t)

    def _tick(self, t):
        """Pause the world for any gap without heartbeat, then close the day if due."""
        w = self.db.execute("SELECT * FROM world").fetchone()
        gap = t - w["heartbeat"]
        next_close = w["next_close_at"]
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if gap > config.PAUSE_GAP_SECONDS:
                # Only the time before the expected close counted as play time.
                next_close += gap
                game._log(self.db, w["day"], "pause", f"World paused for {gap:.0f} s.")
            if t >= next_close:
                game.close_day(self.db)
                # Keep the schedule exact unless we fell more than a whole day behind.
                next_close += self.day_seconds
                if next_close <= t:
                    next_close = t + self.day_seconds
            self.db.execute("UPDATE world SET next_close_at = ?, heartbeat = ?", (next_close, t))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @contextlib.contextmanager
    def tx(self):
        """Run game code atomically, on the day that is current right now."""
        with self.lock:
            self._tick(self.now())
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except game.GameError as e:
                self.db.execute("COMMIT" if e.keep_changes else "ROLLBACK")
                raise
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")

    def clock(self):
        with self.lock:
            w = self.db.execute("SELECT day, next_close_at FROM world").fetchone()
        return {
            "day": w["day"],
            "day_seconds": self.day_seconds,
            "closes_at": w["next_close_at"],
            "seconds_left": max(0.0, w["next_close_at"] - self.now()),
        }

    async def run(self):
        """Background loop: heartbeat every second and close days on time."""
        while True:
            with self.lock:
                self._tick(self.now())
            left = self.clock()["seconds_left"]
            await asyncio.sleep(min(1.0, left + 0.001))

    def close(self):
        with self.lock:
            self.db.execute("UPDATE world SET heartbeat = ?", (self.now(),))
            self.db.close()

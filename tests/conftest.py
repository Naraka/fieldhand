import pytest

from fieldhand.world import World


class FakeTime:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Village:
    """A world with a controllable clock and helpers to act as players."""

    def __init__(self, path):
        self.time = FakeTime()
        self.world = World(path, day_seconds=60, now=self.time)

    def advance(self, seconds):
        # Heartbeats every second like the real clock loop, so no pause is detected.
        end = self.time.t + seconds
        while self.time.t < end:
            self.time.t = min(end, self.time.t + 1)
            with self.world.lock:
                self.world._tick(self.time.t)

    def next_day(self):
        self.advance(self.world.clock()["seconds_left"])

    def do(self, fn, *args):
        with self.world.tx() as db:
            return fn(db, *args)


@pytest.fixture
def village(tmp_path):
    v = Village(tmp_path / "test.db")
    yield v
    v.world.close()

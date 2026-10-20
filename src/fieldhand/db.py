import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS world (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    day INTEGER NOT NULL,
    next_close_at REAL NOT NULL,
    heartbeat REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    token TEXT NOT NULL UNIQUE,
    coins INTEGER NOT NULL,
    -- New and respawned players count as having eaten the day before.
    last_meal_day INTEGER NOT NULL,
    alive_since INTEGER NOT NULL,
    worked INTEGER NOT NULL DEFAULT 0,
    eaten_today INTEGER NOT NULL DEFAULT 0,
    eaten_total INTEGER NOT NULL DEFAULT 0,
    deaths INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plots (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER REFERENCES players(id),
    harvested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS plots_owner ON plots(owner_id);
-- Ration lots: edible up to and including exp_day.
CREATE TABLE IF NOT EXISTS rations (
    player_id INTEGER NOT NULL REFERENCES players(id),
    exp_day INTEGER NOT NULL,
    qty INTEGER NOT NULL,
    PRIMARY KEY (player_id, exp_day)
);
-- Offers last until the day closes.
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    qty INTEGER NOT NULL,
    price INTEGER NOT NULL,
    plot_id INTEGER REFERENCES plots(id)
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    day INTEGER NOT NULL,
    kind TEXT NOT NULL,
    seller_id INTEGER NOT NULL,
    buyer_id INTEGER NOT NULL,
    qty INTEGER NOT NULL,
    price INTEGER NOT NULL,
    plot_id INTEGER
);
CREATE INDEX IF NOT EXISTS trades_day ON trades(day, kind);
-- Plot ownership changes, to replay the map history.
CREATE TABLE IF NOT EXISTS plot_log (
    id INTEGER PRIMARY KEY,
    day INTEGER NOT NULL,
    plot_id INTEGER NOT NULL,
    owner_id INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    day INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS day_stats (
    day INTEGER PRIMARY KEY,
    players INTEGER NOT NULL,
    plots INTEGER NOT NULL,
    free_plots INTEGER NOT NULL,
    owners INTEGER NOT NULL,
    harvested INTEGER NOT NULL,
    deaths INTEGER NOT NULL,
    money INTEGER NOT NULL,
    rations INTEGER NOT NULL,
    ration_price INTEGER,
    wage INTEGER,
    land_price INTEGER
);
"""


def connect(path):
    db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db

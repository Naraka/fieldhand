import os

DB_PATH = os.environ.get("FIELDHAND_DB", "fieldhand.db")
DAY_SECONDS = float(os.environ.get("FIELDHAND_DAY_SECONDS", 3600))
RATE_LIMIT_PER_MIN = int(os.environ.get("FIELDHAND_RATE_LIMIT", 120))

START_COINS = 50
RATIONS_PER_HARVEST = 2
SPOIL_DAYS = 7
# Days in a row without eating that kill a player.
HUNGER_DAYS = 2
# No heartbeat for longer than this means the server was down or suspended:
# the world is paused for that time instead of closing days.
PAUSE_GAP_SECONDS = 3.0

# Coins are stored as integers in thousandths.
MILLI = 1000

import argparse

import uvicorn

from . import config, game
from . import db as dbmod
from .api import create_app


def add_player(name):
    """Create a player without GitHub, for house bots. Prints its token."""
    db = dbmod.connect(config.DB_PATH)
    db.execute("BEGIN IMMEDIATE")
    try:
        player = game.register(db, name)
    except game.GameError as e:
        db.execute("ROLLBACK")
        raise SystemExit(e.message) from None
    db.execute("COMMIT")
    print(player["token"])


def main():
    parser = argparse.ArgumentParser(description="Run the Fieldhand server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--add-player", metavar="NAME", help="create a player without GitHub and print its token"
    )
    args = parser.parse_args()
    if args.add_player:
        add_player(args.add_player)
        return
    # Single process on purpose: the world lock lives in memory.
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()

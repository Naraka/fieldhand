"""A simple Fieldhand bot. Standard library only: copy it and make it smarter.

    python bot.py --name my-bot --server http://127.0.0.1:8000
    python bot.py --name my-bot --once     # play today and exit, for cron

On servers with GitHub sign-in, get your token at /login and pass it in
FIELDHAND_TOKEN. Elsewhere the bot registers itself and keeps the token.

Every day it: claims land if it has none, harvests or looks for a job,
buys food if it has none, eats, and sells what it will not need.
"""

import argparse
import json
import os
import pathlib
import time
import urllib.error
import urllib.request


class Fieldhand:
    def __init__(self, server, token=None):
        self.server = server.rstrip("/")
        self.token = token

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.server + path, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(req, data, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path}: {json.load(e).get('detail')}") from None

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None):
        return self.call("POST", path, body or {})


def login(api, name):
    """Register once and keep the token in a file next to this script.
    FIELDHAND_TOKEN, if set, is used instead (handy for cron jobs)."""
    path = pathlib.Path(__file__).with_name(f".token-{name}")
    if os.environ.get("FIELDHAND_TOKEN"):
        api.token = os.environ["FIELDHAND_TOKEN"]
    elif path.exists():
        api.token = path.read_text().strip()
    else:
        api.token = api.post("/register", {"name": name})["token"]
        path.write_text(api.token)


def play_day(api, log):
    me = api.get("/me")
    prices = api.get("/world")["prices"]
    ration_price = prices["ration_price"] or 0.5

    # 1. Land: free plots go to whoever asks first.
    if not me["plots"]:
        try:
            api.post("/claim")
            me = api.get("/me")
            log("claimed a free plot")
        except RuntimeError:
            pass

    # 2. Workday: harvest my own plot or work for someone else.
    pending = [p["id"] for p in me["plots"] if not p["harvested_today"]]
    if pending and not me["worked_today"]:
        api.post("/harvest", {"plot_id": pending.pop(0)})
        log("harvested my plot")
    elif not me["worked_today"]:
        for job in sorted(api.get("/offers?kind=job"), key=lambda o: -o["price"]):
            try:
                api.post(f"/offers/{job['id']}/accept")
                log(f"worked for {job['player']} for {job['price']} coins")
                break
            except RuntimeError:
                continue

    # 3. Extra plots: hire workers for a wage below the value of 2 rations.
    for plot_id in pending:
        try:
            api.post("/offers", {"kind": "job", "plot_id": plot_id, "price": 1.5 * ration_price})
        except RuntimeError:
            break

    # 4. Food: buy the cheapest rations if there is nothing to eat.
    me = api.get("/me")
    if me["rations"] == 0:
        for offer in api.get("/offers?kind=sell_rations"):
            try:
                api.post(f"/offers/{offer['id']}/accept")
                log(f"bought a ration for {offer['price']}")
                break
            except RuntimeError:
                continue

    # 5. Eat. This is the one thing a bot must never forget.
    me = api.get("/me")
    if me["eaten_today"] == 0 and me["rations"] > 0:
        api.post("/eat", {"qty": 1})
        me["rations"] -= 1

    # 6. Sell the surplus before it spoils.
    surplus = me["rations"] - 4
    if surplus > 0:
        api.post("/offers", {"kind": "sell_rations", "qty": surplus, "price": ration_price})
        log(f"offered {surplus} rations at {ration_price:.3f}")
    return me


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--once", action="store_true", help="play today and exit")
    args = parser.parse_args()

    api = Fieldhand(args.server)
    login(api, args.name)
    while True:
        day = api.get("/clock")["day"]

        def log(msg, day=day):
            print(f"[{args.name}] day {day}: {msg}")

        try:
            me = play_day(api, log)
            print(
                f"[{args.name}] day {day}: {me['coins']:.2f} coins, {me['rations']} rations, "
                f"{len(me['plots'])} plots, {me['deaths']} deaths"
            )
        except (RuntimeError, OSError) as e:
            print(f"[{args.name}] day {day}: error: {e}")
        if args.once:
            break
        # Wait for the next day; the clock tells us exactly when it starts.
        time.sleep(api.get("/clock")["seconds_left"] + 0.5)


if __name__ == "__main__":
    main()

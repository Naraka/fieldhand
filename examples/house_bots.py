"""House bots: a village of bots with different characters, in one process.

    python house_bots.py --tokens house.json --server http://127.0.0.1:8000

house.json maps each bot name to its token. On a server with GitHub sign-in,
the operator creates them with `fieldhand --add-player NAME`.

Every bot acts four times a day:
    morning    harvest, hire workers for its other plots, sell surplus food and land
    midday     look for a job, buy land, buy food or post what it wants to buy
    afternoon  sell to the buyers of the day
    evening    eat, then learn: unsold goods get cheaper, unfilled needs pay more
and has its own character, derived from its position in the file:
    horizon      patience: how many days of rent a plot is worth to it
    beta         how much of its wealth it turns into extra food
    reservation  lowest wage it works for, from 1 to 1.2 rations
Standard library only.
"""

import argparse
import json
import math
import time
from pathlib import Path

from bot import Fieldhand

# When each phase starts, as a fraction of the day. Bots start a little apart.
PHASES = (("morning", 0.03), ("midday", 0.30), ("afternoon", 0.55), ("evening", 0.80))
STAGGER = 0.004
# How much an owner cuts the wage after a day with all its jobs filled.
WAGE_DOWN = 0.995


class HouseBot:
    def __init__(self, name, token, i, server):
        self.name = name
        self.api = Fieldhand(server, token)
        self.horizon = 30 + (i * 37) % 120
        self.beta = 0.02 + ((i * 13) % 10) / 100
        self.reservation = 1 + ((i * 7) % 5) / 20
        self.offset = i * STAGGER
        self.ask = 1.0
        self.bid = 1.0
        self.wage = 1.3
        self.posted = {}
        self.done = set()

    def log(self, msg):
        print(f"[{self.name}] {msg}", flush=True)

    def try_post(self, path, body=None):
        try:
            return self.api.post(path, body)
        except RuntimeError as e:
            self.log(e)
            return None

    def offers(self, kind):
        return self.api.get(f"/offers?kind={kind}")

    def my_open(self, kind):
        return sum(o["qty"] for o in self.offers(kind) if o["player"] == self.name)

    def prices(self):
        """Reference ration price, daily rent of a plot and free plots."""
        world = self.api.get("/world")
        p = world["prices"]["ration_price"] or 1.0
        w = world["prices"]["wage"] or 1.3
        return p, max(2 * p - w, 0.0), world["free_plots"]

    def food_target(self, me, p):
        return 3 + min(math.floor(self.beta * me["coins"] / max(p, 0.001)), 10)

    # --- phases ---------------------------------------------------------------

    def morning(self):
        self.posted = {}
        p, rent, free_plots = self.prices()
        me = self.api.get("/me")
        if not me["plots"] and free_plots:
            self.try_post("/claim")
            me = self.api.get("/me")
        pending = [plot["id"] for plot in me["plots"] if not plot["harvested_today"]]
        if pending and not me["worked_today"]:
            self.try_post("/harvest", {"plot_id": pending.pop(0)})
        self.wage = min(max(self.wage, 0.001), 2 * p * 0.95)
        for plot_id in pending:
            body = {"kind": "job", "price": round(self.wage, 3), "plot_id": plot_id}
            if self.try_post("/offers", body):
                self.posted["job"] = self.posted.get("job", 0) + 1
        me = self.api.get("/me")
        surplus = me["rations"] - self.food_target(me, p)
        if surplus > 0:
            body = {"kind": "sell_rations", "price": round(self.ask, 3), "qty": surplus}
            if self.try_post("/offers", body):
                self.posted["sell_rations"] = surplus
        # Impatient owners sell land to patient ones.
        if self.horizon < 60 and me["plots"] and rent > 0:
            price = round(max(rent * self.horizon * 1.2, p), 3)
            self.try_post(
                "/offers", {"kind": "sell_land", "price": price, "plot_id": me["plots"][-1]["id"]}
            )

    def midday(self):
        p, rent, _ = self.prices()
        me = self.api.get("/me")

        if not me["worked_today"]:
            lowest = p * self.reservation
            if me["rations"] == 0:
                # Hungry: any wage that buys a ration beats starving.
                asks = [o["price"] for o in self.offers("sell_rations")]
                lowest = min(lowest, max((min(asks) if asks else p) - me["coins"], 0.001))
            for job in sorted(self.offers("job"), key=lambda o: -o["price"]):
                if job["price"] < lowest:
                    break
                if self.try_post(f"/offers/{job['id']}/accept"):
                    self.log(f"works for {job['player']} for {job['price']}")
                    break

        if self.horizon > 100 and rent > 0:
            for offer in sorted(self.offers("sell_land"), key=lambda o: o["price"]):
                coins = self.api.get("/me")["coins"]
                if offer["price"] < rent * self.horizon and coins >= offer["price"] + 10 * p:
                    if self.try_post(f"/offers/{offer['id']}/accept"):
                        self.log(f"buys plot #{offer['plot_id']} for {offer['price']}")
                        break

        me = self.api.get("/me")
        need = self.food_target(me, p) - me["rations"]
        coins = me["coins"]
        for offer in sorted(self.offers("sell_rations"), key=lambda o: o["price"]):
            if need <= 0 or (offer["price"] > self.bid and me["rations"] > 0):
                break
            if offer["player"] == self.name:
                continue
            n = min(need, offer["qty"], int(coins // offer["price"]))
            if n >= 1 and self.try_post(f"/offers/{offer['id']}/accept", {"qty": n}):
                need -= n
                coins -= n * offer["price"]
        n = min(need, int(coins // self.bid))
        if n >= 1:
            body = {"kind": "buy_rations", "price": round(self.bid, 3), "qty": n}
            if self.try_post("/offers", body):
                self.posted["buy_rations"] = n

    def afternoon(self):
        surplus = self.api.get("/me")["rations"] - 3
        for offer in sorted(self.offers("buy_rations"), key=lambda o: -o["price"]):
            if surplus <= 0 or offer["price"] < self.ask * 0.9:
                break
            if offer["player"] == self.name:
                continue
            n = min(surplus, offer["qty"])
            if self.try_post(f"/offers/{offer['id']}/accept", {"qty": n}):
                surplus -= n

    def evening(self):
        p, _, _ = self.prices()
        me = self.api.get("/me")
        if me["rations"]:
            day = self.api.get("/clock")["day"]
            expiring = sum(
                lot["qty"] for lot in me["ration_lots"] if lot["expires_after_day"] <= day
            )
            extra = max(0, min(me["rations"] - 3, math.floor(self.beta * me["coins"] / p)))
            self.try_post("/eat", {"qty": min(me["rations"], max(1, expiring) + extra)})
        if self.posted.get("sell_rations"):
            left = self.my_open("sell_rations")
            if left == self.posted["sell_rations"]:
                self.ask *= 0.93
            elif left == 0:
                self.ask *= 1.03
        if self.posted.get("buy_rations"):
            self.bid *= 1.05 if self.my_open("buy_rations") else 0.99
        if self.posted.get("job"):
            self.wage *= 1.05 if self.my_open("job") else WAGE_DOWN
        self.ask = max(self.ask, 0.001)
        self.bid = max(self.bid, 0.001)

    def tick(self, day, fraction):
        """Run every phase of today that is due and not done yet."""
        for phase, start in PHASES:
            if fraction >= start + self.offset and (day, phase) not in self.done:
                self.done = {d for d in self.done if d[0] == day}
                self.done.add((day, phase))
                try:
                    getattr(self, phase)()
                except (RuntimeError, OSError) as e:
                    self.log(f"{phase} failed: {e}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tokens", type=Path, required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    tokens = json.loads(args.tokens.read_text())
    bots = [HouseBot(name, token, i, args.server) for i, (name, token) in enumerate(tokens.items())]
    clock_api = Fieldhand(args.server)
    while True:
        # Check the clock about 200 times a day, but at least every 20 seconds.
        wait = 20.0
        try:
            clock = clock_api.get("/clock")
            wait = min(wait, clock["day_seconds"] / 200)
            fraction = 1 - clock["seconds_left"] / clock["day_seconds"]
            for bot in bots:
                bot.tick(clock["day"], fraction)
        except (RuntimeError, OSError) as e:
            print(f"clock failed: {e}", flush=True)
        time.sleep(max(1.0, wait))


if __name__ == "__main__":
    main()

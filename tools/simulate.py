"""Economic stress test: drives the real game engine with many strategy bots.

No HTTP and no clock: bots call the same functions the API calls, and each
day is closed with the same close_day(). Prices, wages and land values are
set by every bot on its own; there is no central price.

    uv run python tools/simulate.py --scenario base --out results/

Each bot has deterministic traits derived from its index:
    horizon      patience: how many days of rent a plot is worth to it
    beta         how much of its wealth it turns into extra consumption
    reservation  lowest wage it works for, from 1 to 1.2 rations
Bot outages use a seeded generator, so runs are reproducible.
"""

import argparse
import csv
import json
import math
import random
import statistics
import time
from pathlib import Path

from fieldhand import config, game
from fieldhand import db as dbmod

M = config.MILLI

SCENARIOS = {
    "base": {},
    "no_outages": {"down_every": 0},
    "closed_world": {"reg_every": 0},
    "fast_growth": {"reg_every": 2},
    "many_outages": {"down_every": 300},
    "coins_0": {"start_coins": 0},
    "coins_10": {"start_coins": 10},
    "coins_20": {"start_coins": 20},
    "coins_100": {"start_coins": 100},
    "big_village": {"bots": 300, "days": 2000},
    "newcomer_wave": {"burst_day": 1000, "burst_n": 100},
    "small_village": {"bots": 10},
    "naive_workers": {"reservation": 0},
    "fair_owners": {"wage_down": 0.995},
    "greedy_owners": {"wage_down": 0.95},
}
DEFAULTS = {
    "bots": 100,
    "days": 3000,
    "start_coins": 50,
    "reg_every": 20,
    "down_every": 3000,
    "burst_day": 0,
    "burst_n": 0,
    "seed": 20261020,
    # Lowest wage a worker accepts, in rations at the reference price.
    # 0 = naive workers that take any job.
    "reservation": 1,
    # How much owners cut a wage after a day with all their jobs filled.
    "wage_down": 0.98,
}


class Bot:
    def __init__(self, pid, i):
        self.pid = pid
        self.horizon = 30 + (i * 37) % 120
        self.beta = 0.02 + ((i * 13) % 10) / 100
        self.reservation = 1 + ((i * 7) % 5) / 20
        self.ask = 1.0
        self.bid = 1.0
        self.wage = 1.3
        self.posted = {}


def milli(coins):
    return max(1, round(coins * M))


class Sim:
    def __init__(self, cfg):
        self.cfg = cfg
        config.START_COINS = cfg["start_coins"]
        self.db = dbmod.connect(":memory:")
        self.db.execute("INSERT INTO world VALUES (1, 1, 0, 0)")
        self.rng = random.Random(cfg["seed"])
        self.bots = []
        self.money_expected = 0
        self.rows = []
        for _ in range(cfg["bots"]):
            self.register()

    # --- engine access ---------------------------------------------------

    def act(self, fn, *args):
        """Run one action atomically, like World.tx() does for the API."""
        self.db.execute("SAVEPOINT a")
        try:
            result = fn(self.db, *args)
        except game.GameError as e:
            if not e.keep_changes:
                self.db.execute("ROLLBACK TO a")
            self.db.execute("RELEASE a")
            return None
        self.db.execute("RELEASE a")
        return result

    def q(self, sql, *args):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql, *args):
        return self.db.execute(sql, args).fetchone()[0]

    def register(self):
        i = len(self.bots)
        pid = self.act(game.register, f"bot-{i}")["player_id"]
        self.bots.append(Bot(pid, i))
        self.money_expected += config.START_COINS * M

    def coins(self, b):
        return self.one("SELECT coins FROM players WHERE id = ?", b.pid) / M

    def stock(self, b):
        return game.ration_stock(self.db, b.pid)

    def plots(self, b):
        return self.q("SELECT id, harvested FROM plots WHERE owner_id = ? ORDER BY id", b.pid)

    def worked(self, b):
        return self.one("SELECT worked FROM players WHERE id = ?", b.pid)

    def offers(self, kind):
        return self.q("SELECT id, player_id, qty, price, plot_id FROM offers WHERE kind = ?", kind)

    def my_open(self, b, kind):
        return self.one(
            "SELECT COALESCE(SUM(qty), 0) FROM offers WHERE player_id = ? AND kind = ?",
            b.pid,
            kind,
        )

    # --- one day -----------------------------------------------------------

    def ref_prices(self):
        prices = game.last_prices(self.db)
        p = (prices["ration_price"] or M) / M
        w = (prices["wage"] or 1.3 * M) / M
        return p, w

    def run_day(self, day):
        cfg = self.cfg
        if cfg["reg_every"] and day > 1 and day % cfg["reg_every"] == 0:
            self.register()
        if day == cfg["burst_day"]:
            for _ in range(cfg["burst_n"]):
                self.register()

        # Rotate the order every day so no bot is always first.
        k = day % len(self.bots)
        order = self.bots[k:] + self.bots[:k]
        down = {
            b.pid for b in order if cfg["down_every"] and self.rng.random() < 1 / cfg["down_every"]
        }
        up = [b for b in order if b.pid not in down]
        p, w = self.ref_prices()
        rent = max(2 * p - w, 0.0)

        for b in up:
            b.posted = {}
            self.morning(b, p, rent)
        self.jobs_posted = len(self.offers("job"))
        for b in up:
            self.buy_land(b, p, rent)
        for b in up:
            self.find_work(b, p)
        for b in up:
            self.buy_food(b, p)
        for b in up:
            self.fill_bids(b)
        for b in up:
            self.evening(b, day, p)

        self.jobs_filled = self.one(
            "SELECT COUNT(*) FROM trades WHERE day = ? AND kind = 'job'", day
        )
        self.record(day, down)

    def morning(self, b, p, rent):
        plots = self.plots(b)
        if not plots:
            self.act(game.claim, b.pid)
            plots = self.plots(b)
        pending = [r["id"] for r in plots if not r["harvested"]]
        if pending and not self.worked(b):
            self.act(game.harvest, b.pid, pending.pop(0))
        b.wage = min(max(b.wage, 0.001), 2 * p * 0.95)
        for plot_id in pending:
            if self.act(game.post_offer, b.pid, "job", milli(b.wage), 1, plot_id):
                b.posted["job"] = b.posted.get("job", 0) + 1
        target = self.food_target(b, p)
        surplus = self.stock(b) - target
        if surplus > 0:
            self.act(game.post_offer, b.pid, "sell_rations", milli(b.ask), surplus)
            b.posted["sell_rations"] = surplus
        # Impatient owners sell land to patient ones.
        if b.horizon < 60 and plots and rent > 0:
            price = milli(max(rent * b.horizon * 1.2, p))
            self.act(game.post_offer, b.pid, "sell_land", price, 1, plots[-1]["id"])

    def food_target(self, b, p):
        extra = math.floor(b.beta * self.coins(b) / max(p, 0.001))
        return 3 + min(extra, 10)

    def buy_land(self, b, p, rent):
        if b.horizon <= 100 or rent <= 0:
            return
        for offer in sorted(self.offers("sell_land"), key=lambda o: o["price"]):
            price = offer["price"] / M
            if price < rent * b.horizon and self.coins(b) >= price + 10 * p:
                if self.act(game.accept_offer, b.pid, offer["id"], 1):
                    return

    def find_work(self, b, p):
        if self.worked(b):
            return
        lowest = p * b.reservation * self.cfg["reservation"]
        if self.stock(b) == 0:
            # Hungry: any wage that buys today's ration beats starving.
            asks = [o["price"] / M for o in self.offers("sell_rations")]
            cheapest = min(asks) if asks else p
            lowest = min(lowest, max(cheapest - self.coins(b), 0.001))
        for job in sorted(self.offers("job"), key=lambda o: -o["price"]):
            if job["price"] / M < lowest:
                return
            if self.act(game.accept_offer, b.pid, job["id"], 1):
                return

    def buy_food(self, b, p):
        need = self.food_target(b, p) - self.stock(b)
        if need <= 0:
            return
        for offer in sorted(self.offers("sell_rations"), key=lambda o: o["price"]):
            price = offer["price"] / M
            hungry = self.stock(b) == 0
            if price > b.bid and not hungry:
                break
            n = min(need, offer["qty"], int(self.coins(b) // price))
            if n >= 1 and self.act(game.accept_offer, b.pid, offer["id"], n):
                need -= n
            if need <= 0:
                return
        n = min(need, int(self.coins(b) // b.bid))
        if n >= 1:
            self.act(game.post_offer, b.pid, "buy_rations", milli(b.bid), n)
            b.posted["buy_rations"] = n

    def fill_bids(self, b):
        surplus = self.stock(b) - 3
        for offer in sorted(self.offers("buy_rations"), key=lambda o: -o["price"]):
            if surplus <= 0 or offer["price"] / M < b.ask * 0.9:
                return
            n = min(surplus, offer["qty"])
            if self.act(game.accept_offer, b.pid, offer["id"], n):
                surplus -= n

    def evening(self, b, day, p):
        stock = self.stock(b)
        if stock:
            expiring = self.one(
                "SELECT COALESCE(SUM(qty), 0) FROM rations WHERE player_id = ? AND exp_day <= ?",
                b.pid,
                day,
            )
            extra = max(0, min(stock - 3, math.floor(b.beta * self.coins(b) / max(p, 0.001))))
            self.act(game.eat, b.pid, min(stock, max(1, expiring) + extra))
        # Learn from the day: unsold goods get cheaper, unfilled needs pay more.
        if b.posted.get("sell_rations"):
            left = self.my_open(b, "sell_rations")
            b.ask *= 0.93 if left == b.posted["sell_rations"] else 1.03 if left == 0 else 1
        if b.posted.get("buy_rations"):
            b.bid *= 1.05 if self.my_open(b, "buy_rations") else 0.99
        if b.posted.get("job"):
            b.wage *= 1.05 if self.my_open(b, "job") else self.cfg["wage_down"]
        b.ask = max(b.ask, 0.001)
        b.bid = max(b.bid, 0.001)

    # --- metrics and invariants ---------------------------------------------

    def record(self, day, down):
        dying = game.starving(self.db)
        landless = self.q(
            "SELECT worked FROM players WHERE id NOT IN "
            "(SELECT owner_id FROM plots WHERE owner_id IS NOT NULL)"
        )
        land = sorted(
            (r[0] for r in self.q("SELECT COUNT(*) FROM plots GROUP BY owner_id HAVING owner_id")),
            reverse=True,
        )
        coins = sorted(r[0] for r in self.q("SELECT coins FROM players"))
        eaten = [r[0] for r in self.q("SELECT eaten_today FROM players")]
        unharvested_owned = self.one(
            "SELECT COUNT(*) FROM plots WHERE owner_id IS NOT NULL AND harvested = 0"
        )
        n = len(self.bots)

        game.close_day(self.db)
        self.money_expected -= sum(r["coins"] for r in dying)
        money = self.one("SELECT SUM(coins) FROM players")
        assert money == self.money_expected, (day, money, self.money_expected)
        assert self.one("SELECT MIN(coins) FROM players") >= 0, day
        assert self.one("SELECT COALESCE(MIN(qty), 1) FROM rations") > 0, day

        s = dict(self.db.execute("SELECT * FROM day_stats WHERE day = ?", (day,)).fetchone())
        top = max(1, round(n / 10))
        self.rows.append(
            {
                "day": day,
                "players": n,
                "owners": s["owners"],
                "landless": len(landless),
                "unemployed": sum(1 for r in landless if not r[0]),
                "free_plots": s["free_plots"],
                "harvest_rate": s["harvested"] / s["plots"],
                "lost_owned": unharvested_owned,
                "jobs_posted": self.jobs_posted,
                "jobs_filled": self.jobs_filled,
                "deaths_hunger": sum(1 for r in dying if r["id"] not in down),
                "deaths_outage": sum(1 for r in dying if r["id"] in down),
                "money": money / M,
                "rations": s["rations"],
                "ration_price": s["ration_price"] / M if s["ration_price"] else None,
                "wage": s["wage"] / M if s["wage"] else None,
                "land_price": s["land_price"] / M if s["land_price"] else None,
                "top10_land": sum(land[:top]) / max(1, sum(land)),
                "max_plots": land[0] if land else 0,
                "gini_coins": gini(coins),
                "eaten_mean": statistics.fmean(eaten),
            }
        )


def gini(values):
    total = sum(values)
    if not total:
        return 0.0
    n = len(values)
    return sum((2 * i - n + 1) * v for i, v in enumerate(values)) / (n * total)


def summarize(rows, cfg):
    tail = rows[-len(rows) // 5 :]

    def mean(key, data=tail):
        vals = [r[key] for r in data if r[key] is not None]
        return statistics.fmean(vals) if vals else None

    prices = [r["ration_price"] for r in tail if r["ration_price"]]
    early = [
        r["ration_price"] for r in rows[len(rows) // 5 : 2 * len(rows) // 5] if r["ration_price"]
    ]
    bot_days = sum(r["players"] for r in rows)
    hunger = sum(r["deaths_hunger"] for r in rows)
    return {
        "config": cfg,
        "deaths_hunger": hunger,
        "deaths_outage": sum(r["deaths_outage"] for r in rows),
        "hunger_deaths_per_1000_bot_days": 1000 * hunger / bot_days,
        "worst_day_hunger": max(r["deaths_hunger"] for r in rows),
        "worst_day": max(rows, key=lambda r: r["deaths_hunger"])["day"],
        "tail": {
            "ration_price": mean("ration_price"),
            "ration_price_cv": statistics.pstdev(prices) / statistics.fmean(prices)
            if prices
            else None,
            "ration_price_min": min(prices) if prices else None,
            "ration_price_max": max(prices) if prices else None,
            "price_change_vs_early": statistics.fmean(prices) / statistics.fmean(early)
            if prices and early
            else None,
            "wage_in_rations": (mean("wage") / mean("ration_price"))
            if mean("wage") and mean("ration_price")
            else None,
            "harvest_rate": mean("harvest_rate"),
            "unemployed_share": mean("unemployed") / rows[-1]["players"],
            "landless_share": mean("landless") / rows[-1]["players"],
            "top10_land": mean("top10_land"),
            "gini_coins": mean("gini_coins"),
            "eaten_mean": mean("eaten_mean"),
            "hunger_deaths_per_day": mean("deaths_hunger"),
        },
        "final": rows[-1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=SCENARIOS, default="base")
    parser.add_argument("--days", type=int)
    parser.add_argument("--bots", type=int)
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    cfg = {**DEFAULTS, **SCENARIOS[args.scenario]}
    if args.days:
        cfg["days"] = args.days
    if args.bots:
        cfg["bots"] = args.bots
    sim = Sim(cfg)
    t0 = time.time()
    for day in range(1, cfg["days"] + 1):
        sim.run_day(day)
    summary = summarize(sim.rows, cfg)
    summary["seconds"] = round(time.time() - t0, 1)

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / f"{args.scenario}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sim.rows[0].keys())
        writer.writeheader()
        writer.writerows(sim.rows)
    (args.out / f"{args.scenario}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"scenario": args.scenario, **summary["tail"], "seconds": summary["seconds"]}))


if __name__ == "__main__":
    main()

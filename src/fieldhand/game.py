"""Game rules. Every function runs inside a transaction holding the world lock."""

import re
import secrets

from . import config

OFFER_KINDS = ("sell_rations", "buy_rations", "sell_land", "job")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,39}$")


class GameError(Exception):
    def __init__(self, message, status=400, keep_changes=False):
        super().__init__(message)
        self.message = message
        self.status = status
        # True when the changes made before the error must still be saved.
        self.keep_changes = keep_changes


def current_day(db):
    return db.execute("SELECT day FROM world").fetchone()["day"]


def _log(db, day, kind, text):
    db.execute("INSERT INTO events (day, kind, text) VALUES (?, ?, ?)", (day, kind, text))


def _player(db, pid):
    return db.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()


def _name(db, pid):
    return db.execute("SELECT name FROM players WHERE id = ?", (pid,)).fetchone()["name"]


def _set_owner(db, day, plot_id, owner_id):
    db.execute("UPDATE plots SET owner_id = ? WHERE id = ?", (owner_id, plot_id))
    db.execute("DELETE FROM offers WHERE plot_id = ?", (plot_id,))
    db.execute(
        "INSERT INTO plot_log (day, plot_id, owner_id) VALUES (?, ?, ?)",
        (day, plot_id, owner_id),
    )


def _move_coins(db, from_id, to_id, amount):
    db.execute("UPDATE players SET coins = coins - ? WHERE id = ?", (amount, from_id))
    db.execute("UPDATE players SET coins = coins + ? WHERE id = ?", (amount, to_id))


def ration_stock(db, pid):
    return db.execute(
        "SELECT COALESCE(SUM(qty), 0) AS n FROM rations WHERE player_id = ?", (pid,)
    ).fetchone()["n"]


def _add_rations(db, pid, lots):
    for exp_day, qty in lots:
        db.execute(
            "INSERT INTO rations (player_id, exp_day, qty) VALUES (?, ?, ?) "
            "ON CONFLICT (player_id, exp_day) DO UPDATE SET qty = qty + excluded.qty",
            (pid, exp_day, qty),
        )


def _take_rations(db, pid, qty):
    """Remove qty rations, oldest first. Returns the lots taken."""
    lots = db.execute(
        "SELECT exp_day, qty FROM rations WHERE player_id = ? ORDER BY exp_day", (pid,)
    ).fetchall()
    if sum(lot["qty"] for lot in lots) < qty:
        raise GameError("not enough rations", 409)
    taken = []
    for lot in lots:
        if qty == 0:
            break
        n = min(lot["qty"], qty)
        if n == lot["qty"]:
            db.execute(
                "DELETE FROM rations WHERE player_id = ? AND exp_day = ?",
                (pid, lot["exp_day"]),
            )
        else:
            db.execute(
                "UPDATE rations SET qty = qty - ? WHERE player_id = ? AND exp_day = ?",
                (n, pid, lot["exp_day"]),
            )
        taken.append((lot["exp_day"], n))
        qty -= n
    return taken


def _harvest_into(db, day, owner_id, plot_id):
    db.execute("UPDATE plots SET harvested = 1 WHERE id = ?", (plot_id,))
    db.execute("DELETE FROM offers WHERE kind = 'job' AND plot_id = ?", (plot_id,))
    _add_rations(db, owner_id, [(day + config.SPOIL_DAYS - 1, config.RATIONS_PER_HARVEST)])


def _own_plot(db, pid, plot_id):
    plot = db.execute("SELECT * FROM plots WHERE id = ?", (plot_id,)).fetchone()
    if plot is None:
        raise GameError("plot not found", 404)
    if plot["owner_id"] != pid:
        raise GameError("that plot is not yours", 403)
    return plot


# --- Actions ---------------------------------------------------------------


def register(db, name, github_id=None):
    if not NAME_RE.match(name):
        raise GameError("name must be 1-39 characters: letters, digits, _ or -")
    if db.execute("SELECT 1 FROM players WHERE name = ?", (name,)).fetchone():
        raise GameError("name already taken", 409)
    day = current_day(db)
    token = secrets.token_urlsafe(24)
    pid = db.execute(
        "INSERT INTO players (name, token, github_id, coins, last_meal_day, alive_since) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, token, github_id, config.START_COINS * config.MILLI, day - 1, day),
    ).lastrowid
    plot_id = db.execute("INSERT INTO plots (owner_id) VALUES (NULL)").lastrowid
    db.execute("INSERT INTO plot_log (day, plot_id, owner_id) VALUES (?, ?, NULL)", (day, plot_id))
    _log(db, day, "register", f"{name} arrives. A new free plot appears (#{plot_id}).")
    return {"player_id": pid, "name": name, "token": token}


def register_github(db, github_id, login):
    """One player per GitHub account, named after it. Signing in again gives
    back the same token."""
    row = db.execute(
        "SELECT id, name, token FROM players WHERE github_id = ?", (github_id,)
    ).fetchone()
    if row:
        return {"player_id": row["id"], "name": row["name"], "token": row["token"]}
    return register(db, login, github_id)


def claim(db, pid, plot_id=None):
    """Take a free plot. Only players without land can claim."""
    day = current_day(db)
    if db.execute("SELECT 1 FROM plots WHERE owner_id = ?", (pid,)).fetchone():
        raise GameError("only players without land can claim a free plot", 409)
    if plot_id is None:
        plot = db.execute("SELECT id FROM plots WHERE owner_id IS NULL ORDER BY id").fetchone()
    else:
        plot = db.execute(
            "SELECT id FROM plots WHERE id = ? AND owner_id IS NULL", (plot_id,)
        ).fetchone()
    if plot is None:
        raise GameError("no free plot available", 409)
    _set_owner(db, day, plot["id"], pid)
    _log(db, day, "claim", f"{_name(db, pid)} claims free plot #{plot['id']}.")
    return {"plot_id": plot["id"]}


def harvest(db, pid, plot_id):
    day = current_day(db)
    plot = _own_plot(db, pid, plot_id)
    if _player(db, pid)["worked"]:
        raise GameError("you already used your workday today", 409)
    if plot["harvested"]:
        raise GameError("plot already harvested today", 409)
    db.execute("UPDATE players SET worked = 1 WHERE id = ?", (pid,))
    _harvest_into(db, day, pid, plot_id)
    return {"rations": config.RATIONS_PER_HARVEST}


def eat(db, pid, qty):
    if qty < 1:
        raise GameError("qty must be at least 1")
    _take_rations(db, pid, qty)
    db.execute(
        "UPDATE players SET eaten_today = eaten_today + ?, eaten_total = eaten_total + ?, "
        "last_meal_day = ? WHERE id = ?",
        (qty, qty, current_day(db), pid),
    )
    return {"eaten_today": _player(db, pid)["eaten_today"]}


def post_offer(db, pid, kind, price, qty=1, plot_id=None):
    if kind not in OFFER_KINDS:
        raise GameError(f"kind must be one of {', '.join(OFFER_KINDS)}")
    if price <= 0:
        raise GameError("price must be positive")
    if qty < 1:
        raise GameError("qty must be at least 1")
    me = _player(db, pid)
    if kind == "sell_rations":
        plot_id = None
        if ration_stock(db, pid) < qty:
            raise GameError("not enough rations", 409)
    elif kind == "buy_rations":
        plot_id = None
        if me["coins"] < qty * price:
            raise GameError("not enough coins", 409)
    else:
        if plot_id is None:
            raise GameError("plot_id is required for this kind of offer")
        plot = _own_plot(db, pid, plot_id)
        qty = 1
        if kind == "job" and plot["harvested"]:
            raise GameError("plot already harvested today", 409)
        if kind == "job" and me["coins"] < price:
            raise GameError("not enough coins to pay that wage", 409)
    oid = db.execute(
        "INSERT INTO offers (kind, player_id, qty, price, plot_id) VALUES (?, ?, ?, ?, ?)",
        (kind, pid, qty, price, plot_id),
    ).lastrowid
    return {"offer_id": oid}


def cancel_offer(db, pid, offer_id):
    n = db.execute("DELETE FROM offers WHERE id = ? AND player_id = ?", (offer_id, pid)).rowcount
    if not n:
        raise GameError("offer not found", 404)
    return {"cancelled": offer_id}


def accept_offer(db, pid, offer_id, qty=1):
    """Take someone else's offer. Goods and coins are checked at this moment:
    if the offer's author can no longer honour it, the offer is removed."""
    day = current_day(db)
    offer = db.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    if offer is None:
        raise GameError("offer not found", 404)
    if offer["player_id"] == pid:
        raise GameError("you cannot accept your own offer", 409)
    if qty < 1 or qty > offer["qty"]:
        raise GameError(f"qty must be between 1 and {offer['qty']}")
    author = offer["player_id"]
    me = _player(db, pid)
    kind, price = offer["kind"], offer["price"]

    def withdraw(reason):
        db.execute("DELETE FROM offers WHERE id = ?", (offer_id,))
        return GameError(f"offer withdrawn: {reason}", 409, keep_changes=True)

    if kind in ("sell_rations", "buy_rations"):
        seller, buyer = (author, pid) if kind == "sell_rations" else (pid, author)
        total = qty * price
        if _player(db, buyer)["coins"] < total:
            if buyer == pid:
                raise GameError("not enough coins", 409)
            raise withdraw("buyer has not enough coins")
        if ration_stock(db, seller) < qty:
            if seller == pid:
                raise GameError("not enough rations", 409)
            raise withdraw("seller has not enough rations")
        _add_rations(db, buyer, _take_rations(db, seller, qty))
        _move_coins(db, buyer, seller, total)
    elif kind == "sell_land":
        qty = 1
        if me["coins"] < price:
            raise GameError("not enough coins", 409)
        seller, buyer = author, pid
        _move_coins(db, buyer, seller, price)
        _set_owner(db, day, offer["plot_id"], buyer)
        _log(
            db,
            day,
            "land",
            f"{_name(db, seller)} sells plot #{offer['plot_id']} to {me['name']} "
            f"for {price / config.MILLI:g} coins.",
        )
    else:  # job
        qty = 1
        if me["worked"]:
            raise GameError("you already used your workday today", 409)
        if _player(db, author)["coins"] < price:
            raise withdraw("owner has not enough coins to pay the wage")
        seller, buyer = pid, author
        db.execute("UPDATE players SET worked = 1 WHERE id = ?", (pid,))
        _move_coins(db, buyer, seller, price)
        _harvest_into(db, day, buyer, offer["plot_id"])

    db.execute(
        "INSERT INTO trades (day, kind, seller_id, buyer_id, qty, price, plot_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (day, kind, seller, buyer, qty, price, offer["plot_id"]),
    )
    db.execute("UPDATE offers SET qty = qty - ? WHERE id = ?", (qty, offer_id))
    db.execute("DELETE FROM offers WHERE id = ? AND qty <= 0", (offer_id,))
    return {"kind": kind, "qty": qty, "price": price}


# --- Day close -------------------------------------------------------------


def _vwap(db, day, kind):
    row = db.execute(
        "SELECT SUM(qty * price) AS v, SUM(qty) AS q FROM trades WHERE day = ? AND kind = ?",
        (day, kind),
    ).fetchone()
    return round(row["v"] / row["q"]) if row["q"] else None


def starving(db):
    """Players who die if the day closes now."""
    return db.execute(
        "SELECT id, name, coins FROM players WHERE last_meal_day <= ?",
        (current_day(db) - config.HUNGER_DAYS,),
    ).fetchall()


def close_day(db):
    """Hunger, spoilage and reset. Offers and unharvested crops are lost."""
    day = current_day(db)
    harvested = db.execute("SELECT COUNT(*) FROM plots WHERE harvested = 1").fetchone()[0]

    dead = starving(db)
    for p in dead:
        plots = db.execute("SELECT id FROM plots WHERE owner_id = ?", (p["id"],)).fetchall()
        for plot in plots:
            _set_owner(db, day, plot["id"], None)
        db.execute("DELETE FROM rations WHERE player_id = ?", (p["id"],))
        db.execute(
            "UPDATE players SET coins = 0, deaths = deaths + 1, alive_since = ?, "
            "last_meal_day = ? WHERE id = ?",
            (day + 1, day, p["id"]),
        )
        _log(
            db,
            day,
            "death",
            f"{p['name']} went {config.HUNGER_DAYS} days without eating and died. "
            f"{len(plots)} plot(s) are free again.",
        )

    db.execute("DELETE FROM rations WHERE exp_day <= ?", (day,))
    db.execute("DELETE FROM offers")
    db.execute("UPDATE players SET worked = 0, eaten_today = 0")
    db.execute("UPDATE plots SET harvested = 0")

    totals = db.execute(
        "SELECT (SELECT COUNT(*) FROM players) AS players,"
        " (SELECT COUNT(*) FROM plots) AS plots,"
        " (SELECT COUNT(*) FROM plots WHERE owner_id IS NULL) AS free_plots,"
        " (SELECT COUNT(DISTINCT owner_id) FROM plots) AS owners,"
        " (SELECT COALESCE(SUM(coins), 0) FROM players) AS money,"
        " (SELECT COALESCE(SUM(qty), 0) FROM rations) AS rations"
    ).fetchone()
    db.execute(
        "INSERT INTO day_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            day,
            totals["players"],
            totals["plots"],
            totals["free_plots"],
            totals["owners"],
            harvested,
            len(dead),
            totals["money"],
            totals["rations"],
            _vwap(db, day, "sell_rations") or _vwap(db, day, "buy_rations"),
            _vwap(db, day, "job"),
            _vwap(db, day, "sell_land"),
        ),
    )
    db.execute("UPDATE world SET day = day + 1")
    return {"day": day, "deaths": len(dead)}


# --- Queries ---------------------------------------------------------------


def last_prices(db):
    """Most recent daily average price of rations, wages and land."""
    prices = {}
    for col in ("ration_price", "wage", "land_price"):
        row = db.execute(
            f"SELECT {col} FROM day_stats WHERE {col} IS NOT NULL ORDER BY day DESC LIMIT 1"
        ).fetchone()
        prices[col] = row[0] if row else None
    return prices


def player_state(db, pid):
    p = _player(db, pid)
    plots = db.execute(
        "SELECT id, harvested FROM plots WHERE owner_id = ? ORDER BY id", (pid,)
    ).fetchall()
    lots = db.execute(
        "SELECT exp_day, qty FROM rations WHERE player_id = ? ORDER BY exp_day", (pid,)
    ).fetchall()
    return {
        "id": p["id"],
        "name": p["name"],
        "coins": p["coins"] / config.MILLI,
        "rations": sum(lot["qty"] for lot in lots),
        "ration_lots": [{"expires_after_day": lot["exp_day"], "qty": lot["qty"]} for lot in lots],
        "plots": [{"id": r["id"], "harvested_today": bool(r["harvested"])} for r in plots],
        "worked_today": bool(p["worked"]),
        "eaten_today": p["eaten_today"],
        "eaten_total": p["eaten_total"],
        "days_alive": current_day(db) - p["alive_since"],
        "deaths": p["deaths"],
        "last_meal_day": p["last_meal_day"],
        "must_eat_by_day": p["last_meal_day"] + config.HUNGER_DAYS,
    }


def list_offers(db, kind=None):
    sql = (
        "SELECT o.id, o.kind, o.player_id, p.name AS player, o.qty, o.price, o.plot_id "
        "FROM offers o JOIN players p ON p.id = o.player_id"
    )
    if kind:
        rows = db.execute(sql + " WHERE o.kind = ? ORDER BY o.price, o.id", (kind,))
    else:
        rows = db.execute(sql + " ORDER BY o.kind, o.price, o.id")
    return [{**dict(r), "price": r["price"] / config.MILLI} for r in rows]


def ranking(db, by, limit=50):
    day = current_day(db)
    if by == "life":
        sql = "SELECT id, name, eaten_total AS value FROM players"
    elif by == "alive":
        sql = f"SELECT id, name, {day} - alive_since AS value FROM players"
    elif by == "wealth":
        prices = last_prices(db)
        land = prices["land_price"] or 0
        ration = prices["ration_price"] or 0
        sql = (
            f"SELECT p.id, p.name, (p.coins"
            f" + {land} * (SELECT COUNT(*) FROM plots WHERE owner_id = p.id)"
            f" + {ration} * (SELECT COALESCE(SUM(qty), 0) FROM rations WHERE player_id = p.id)"
            f") / {float(config.MILLI)} AS value FROM players p"
        )
    else:
        raise GameError("by must be life, wealth or alive")
    rows = db.execute(sql + " ORDER BY value DESC, id LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

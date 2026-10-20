"""HTTP API. Interactive docs at /docs."""

import asyncio
import contextlib
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import __version__, config, game
from .world import World

VIEWER = Path(__file__).with_name("static") / "index.html"


class RegisterIn(BaseModel):
    name: str = Field(examples=["my-bot"])


class ClaimIn(BaseModel):
    plot_id: int | None = None


class HarvestIn(BaseModel):
    plot_id: int


class EatIn(BaseModel):
    qty: int = Field(1, ge=1)


class OfferIn(BaseModel):
    kind: Literal["sell_rations", "buy_rations", "sell_land", "job"]
    price: float = Field(gt=0, description="Coins per unit (wage for a job).")
    qty: int = Field(1, ge=1, description="Only for rations.")
    plot_id: int | None = Field(None, description="Required for sell_land and job.")


class AcceptIn(BaseModel):
    qty: int = Field(1, ge=1)


def to_milli(coins):
    return round(coins * config.MILLI)


def create_app(world=None):
    @contextlib.asynccontextmanager
    async def lifespan(app):
        app.state.world = world or World()
        task = asyncio.create_task(app.state.world.run())
        yield
        task.cancel()
        app.state.world.close()

    app = FastAPI(
        title="Fieldhand",
        version=__version__,
        description="An economic game for bots: land, labour, coins and survival.",
        lifespan=lifespan,
    )
    bearer = HTTPBearer(auto_error=False)
    hits = defaultdict(deque)

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        key = request.headers.get("authorization") or request.client.host
        now = time.monotonic()
        q = hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= config.RATE_LIMIT_PER_MIN:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        q.append(now)
        return await call_next(request)

    def play(request: Request, fn, *args):
        """Run a game action and add the clock to the answer."""
        w = request.app.state.world
        try:
            with w.tx() as db:
                result = fn(db, *args)
        except game.GameError as e:
            raise HTTPException(e.status, e.message) from None
        return {**result, **w.clock()} if isinstance(result, dict) else result

    def player_id(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if cred is None:
            raise HTTPException(401, "missing bearer token")
        with request.app.state.world.lock:
            row = request.app.state.world.db.execute(
                "SELECT id FROM players WHERE token = ?", (cred.credentials,)
            ).fetchone()
        if row is None:
            raise HTTPException(401, "invalid token")
        return row["id"]

    @app.get("/clock", summary="Current day and seconds left until it closes")
    def clock(request: Request):
        return request.app.state.world.clock()

    @app.get("/world", summary="Village summary and latest prices")
    def world_summary(request: Request):
        def summary(db):
            counts = db.execute(
                "SELECT (SELECT COUNT(*) FROM players) AS players,"
                " (SELECT COUNT(*) FROM plots) AS plots,"
                " (SELECT COUNT(*) FROM plots WHERE owner_id IS NULL) AS free_plots"
            ).fetchone()
            prices = {
                k: (v / config.MILLI if v is not None else None)
                for k, v in game.last_prices(db).items()
            }
            return {**dict(counts), "prices": prices}

        return play(request, summary)

    @app.post("/register", summary="Create a player. Keep the token: it is shown only once")
    def register(body: RegisterIn, request: Request):
        return play(request, game.register, body.name)

    @app.get("/me", summary="Your coins, rations, plots and today's status")
    def me(request: Request, pid: int = Depends(player_id)):
        return play(request, game.player_state, pid)

    @app.post("/claim", summary="Take a free plot (only if you have no land)")
    def claim(body: ClaimIn, request: Request, pid: int = Depends(player_id)):
        return play(request, game.claim, pid, body.plot_id)

    @app.post("/harvest", summary="Use your workday to harvest one of your plots")
    def harvest(body: HarvestIn, request: Request, pid: int = Depends(player_id)):
        return play(request, game.harvest, pid, body.plot_id)

    @app.post("/eat", summary="Eat rations. 2 days in a row without eating kill you")
    def eat(body: EatIn, request: Request, pid: int = Depends(player_id)):
        return play(request, game.eat, pid, body.qty)

    @app.get("/offers", summary="Open offers of the day")
    def offers(request: Request, kind: str | None = None):
        return play(request, game.list_offers, kind)

    @app.post("/offers", summary="Post an offer. Offers expire when the day closes")
    def post_offer(body: OfferIn, request: Request, pid: int = Depends(player_id)):
        return play(
            request, game.post_offer, pid, body.kind, to_milli(body.price), body.qty, body.plot_id
        )

    @app.delete("/offers/{offer_id}", summary="Cancel one of your offers")
    def cancel_offer(offer_id: int, request: Request, pid: int = Depends(player_id)):
        return play(request, game.cancel_offer, pid, offer_id)

    @app.post("/offers/{offer_id}/accept", summary="Accept someone else's offer")
    def accept_offer(
        offer_id: int, body: AcceptIn, request: Request, pid: int = Depends(player_id)
    ):
        result = play(request, game.accept_offer, pid, offer_id, body.qty)
        return {**result, "price": result["price"] / config.MILLI}

    @app.get("/plots", summary="Owner of every plot, in spiral order (for the map)")
    def plots(request: Request):
        def rows(db):
            return [
                dict(r)
                for r in db.execute(
                    "SELECT p.id, p.owner_id, pl.name AS owner, p.harvested FROM plots p"
                    " LEFT JOIN players pl ON pl.id = p.owner_id ORDER BY p.id"
                )
            ]

        return play(request, rows)

    @app.get("/plots/history", summary="Every change of plot owner, oldest first")
    def plots_history(request: Request, after_id: int = 0, limit: int = Query(5000, ge=1, le=5000)):
        def rows(db):
            return [
                dict(r)
                for r in db.execute(
                    "SELECT l.id, l.day, l.plot_id, pl.name AS owner FROM plot_log l"
                    " LEFT JOIN players pl ON pl.id = l.owner_id"
                    " WHERE l.id > ? ORDER BY l.id LIMIT ?",
                    (after_id, limit),
                )
            ]

        return play(request, rows)

    @app.get("/ranking", summary="Rankings: life (eaten), wealth or alive (days)")
    def ranking(request: Request, by: Literal["life", "wealth", "alive"] = "life"):
        return play(request, game.ranking, by)

    @app.get("/events", summary="Village history, newest first")
    def events(request: Request, after_id: int = 0, limit: int = Query(100, ge=1, le=500)):
        def rows(db):
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM events WHERE id > ? ORDER BY id DESC LIMIT ?",
                    (after_id, limit),
                )
            ]

        return play(request, rows)

    @app.get("/stats", summary="Daily statistics (prices in coins)")
    def stats(request: Request, since_day: int = 0):
        def rows(db):
            out = []
            query = "SELECT * FROM day_stats WHERE day >= ? ORDER BY day LIMIT 2000"
            for r in db.execute(query, (since_day,)):
                d = dict(r)
                for k in ("money", "ration_price", "wage", "land_price"):
                    if d[k] is not None:
                        d[k] /= config.MILLI
                out.append(d)
            return out

        return play(request, rows)

    @app.get("/", include_in_schema=False)
    def viewer():
        return FileResponse(VIEWER)

    return app

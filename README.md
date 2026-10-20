# Fieldhand

**An economic game for bots.** You don't click: you write a program that plays
through an HTTP API. Land, labour, coins and survival. No randomness, no
resets, no seasons. The world runs forever, one day every hour.

```
you register        → 50 coins and a new free plot appears in the village
every day (1 hour)  → one workday: harvest your plot or work on someone else's
a harvest           → 2 rations for the plot owner
2 days without food → you die and lose everything
```

Everything else is up to the players: rations, land and labour are bought and
sold for coins. There is no bank and no institution. The code enforces the
rules, and nobody else does. Full rules in [docs/RULES.md](docs/RULES.md).

## Play in 5 minutes

You only need Python 3.12+. The example bot uses the standard library only.

```bash
git clone https://github.com/Naraka/fieldhand
cd fieldhand
python examples/bot.py --name my-bot --server http://127.0.0.1:8000
```

Then make it smarter. The interesting questions start soon: when to buy land,
what wage to offer, what to do with the rations you cannot eat before they spoil.

## The API

Interactive documentation is served at `/docs` (OpenAPI). Authenticate with
`Authorization: Bearer <token>`. On the public server you get your token by
signing in with GitHub at `/login`: one player per GitHub account, and the
account must be at least 30 days old. Servers without GitHub sign-in let
anyone register with `POST /register`.

| Method | Path                       | What it does                                   |
|--------|----------------------------|------------------------------------------------|
| GET    | `/clock`                   | Day, exact close time and seconds left         |
| GET    | `/world`                   | Players, plots and latest prices               |
| GET    | `/login`                   | Sign in with GitHub to get your token          |
| POST   | `/register`                | Create a player, if registration is open       |
| GET    | `/me`                      | Your coins, rations, plots and today's status  |
| POST   | `/claim`                   | Take a free plot (only if you have no land)    |
| POST   | `/harvest`                 | Harvest one of your plots (`{"plot_id": 1}`)   |
| POST   | `/eat`                     | Eat rations (`{"qty": 1}`)                     |
| GET    | `/offers`                  | Open offers (`?kind=sell_rations`…)            |
| POST   | `/offers`                  | Post an offer                                  |
| POST   | `/offers/{id}/accept`      | Accept an offer                                |
| DELETE | `/offers/{id}`             | Cancel your offer                              |
| GET    | `/ranking?by=life`         | Rankings: `life`, `wealth`, `alive`            |
| GET    | `/plots`                   | Owner of every plot (for the map)              |
| GET    | `/plots/history`           | Every change of plot owner                     |
| GET    | `/events`                  | Village history                                |
| GET    | `/stats`                   | Daily statistics                               |

Each bot can make 120 requests per minute.

## Run your own server

```bash
uv sync
uv run fieldhand                           # http://127.0.0.1:8000
FIELDHAND_DAY_SECONDS=10 uv run fieldhand  # short days for testing
python examples/village.py --bots 10       # fill it with example bots
```

| Variable                         | Default        | Meaning                                  |
|----------------------------------|----------------|------------------------------------------|
| `FIELDHAND_DB`                   | `fieldhand.db` | SQLite database file                     |
| `FIELDHAND_DAY_SECONDS`          | `3600`         | Length of a game day                     |
| `FIELDHAND_RATE_LIMIT`           | `120`          | Requests per minute per bot              |
| `FIELDHAND_GITHUB_CLIENT_ID`     | none           | GitHub OAuth app; enables GitHub sign-in |
| `FIELDHAND_GITHUB_CLIENT_SECRET` | none           | Its client secret                        |

The server must run as **a single process**: the world lock lives in memory.
To deploy it on a small Linux server, see [deploy/](deploy/).

## Watch the village

The server shows a live viewer at `/`: the map of plots and who owns them (with
a replay of its whole history), prices, wages, deaths, rankings and the log.
To look at a simulated village instead of a live one:

```bash
uv run python tools/simulate.py --days 400 --db village.db
FIELDHAND_DB=village.db uv run fieldhand
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Rule changes start as an issue.

## License

[AGPL-3.0-or-later](LICENSE). If you run a modified server, publish your changes.
Your bots are yours: talking to the API does not make them part of this work.

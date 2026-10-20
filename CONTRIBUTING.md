# Contributing

Thanks for your interest in Fieldhand.

## Two kinds of contributions

- **Code** (bugs, performance, the web viewer, docs, example bots): open a pull request.
- **Rules** (anything that changes how the economy works): open an issue with the
  *Rule proposal* template first. Rules change rarely, because bots in the live
  world depend on them. A proposal backed by a simulation has the best chance.

## Development

```bash
git clone https://github.com/Naraka/fieldhand
cd fieldhand
uv sync
uv run pytest
FIELDHAND_DAY_SECONDS=10 uv run fieldhand   # short days for local testing
```

Before sending a pull request:

```bash
uv run ruff check .
uv run ruff format .
uv run pytest
```

## Guidelines

- Keep it simple: the game is meant to be small enough to read in one sitting.
- No randomness in the rules. Ever.
- Every rule change comes with a test.
- Coins are integers in thousandths inside the server; the API speaks in coins.

By contributing you agree that your contributions are licensed under the AGPL-3.0.

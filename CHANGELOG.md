# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Game server: FastAPI + SQLite, one-hour days, exact day close, world pause on downtime.
- Rules: registration, free plots, harvest, jobs, ration and land market, eating, death after
  2 days without food, spoilage.
- Rankings (life, wealth, alive), village events, daily stats and plot history.
- Sign in with GitHub: one player per GitHub account at least 30 days old. Without a
  GitHub app the server keeps open registration, for local games.
- Web viewer at `/`: village map with its history, economy charts, rankings and log.
- House bots with different characters (`examples/house_bots.py`) to keep a new village
  alive, and `fieldhand --add-player NAME` to create players without GitHub for them.
- Example bot (standard library only) and a script to run a local village.
- Economic stress test (`tools/simulate.py`) that drives the real engine with strategy bots,
  checks money conservation every day and compares strategies.

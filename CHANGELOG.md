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
- Example bot (standard library only) and a script to run a local village.
- Economic stress test (`tools/simulate.py`) that drives the real engine with strategy bots,
  checks money conservation every day and compares strategies.

"""Print one line per scenario from the output of tools/simulate.py.

    uv run python tools/results_table.py results/

Columns: hunger deaths per 1000 bot-days and per day (last fifth of the run),
ration price, its coefficient of variation, price vs the second fifth, wage in
rations, harvest rate, unemployed and landless shares, land held by the top
10 %, coin Gini, rations eaten per bot and day, and hunger deaths per day in
the second fifth -> last fifth.
"""

import csv
import json
import statistics
import sys
from pathlib import Path

COLUMNS = (
    f"{'scenario':24} {'d/1k':>6} {'d/day':>6} {'price':>6} {'cv':>5} {'p/p0':>5} "
    f"{'wage':>5} {'harv':>5} {'unemp':>5} {'nolnd':>5} {'top10':>5} {'gini':>5} "
    f"{'eaten':>5} {'deaths trend':>13}"
)


def fmt(value, digits=2):
    return "-" if value is None else f"{value:.{digits}f}"


def line(name, summary, rows):
    t = summary["tail"]
    fifth = len(rows) // 5

    def deaths(a, b):
        return statistics.fmean(float(r["deaths_hunger"]) for r in rows[a:b])

    trend = f"{deaths(fifth, 2 * fifth):.1f}->{deaths(len(rows) - fifth, len(rows)):.1f}"
    return (
        f"{name:24} {summary['hunger_deaths_per_1000_bot_days']:6.1f} "
        f"{t['hunger_deaths_per_day']:6.1f} {fmt(t['ration_price']):>6} "
        f"{fmt(t['ration_price_cv']):>5} {fmt(t['price_change_vs_early']):>5} "
        f"{fmt(t['wage_in_rations']):>5} {t['harvest_rate']:5.0%} "
        f"{t['unemployed_share']:5.0%} {t['landless_share']:5.0%} {t['top10_land']:5.0%} "
        f"{t['gini_coins']:5.2f} {t['eaten_mean']:5.2f} {trend:>13}"
    )


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
    print(COLUMNS)
    for path in sorted(folder.glob("*.json")):
        with open(path.with_suffix(".csv")) as f:
            rows = list(csv.DictReader(f))
        print(line(path.stem, json.loads(path.read_text()), rows))


if __name__ == "__main__":
    main()

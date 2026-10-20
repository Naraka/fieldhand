"""Run several example bots at once to fill a local village.

python examples/village.py --bots 10
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bots", type=int, default=10)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    bot = Path(__file__).with_name("bot.py")
    procs = [
        subprocess.Popen(
            [sys.executable, str(bot), "--name", f"house-{i:02d}", "--server", args.server]
        )
        for i in range(args.bots)
    ]
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()

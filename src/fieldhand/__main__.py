import argparse

import uvicorn

from .api import create_app


def main():
    parser = argparse.ArgumentParser(description="Run the Fieldhand server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    # Single process on purpose: the world lock lives in memory.
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()

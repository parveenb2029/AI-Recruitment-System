"""Run the review console.

    python -m recruit.web
    python -m recruit.web --port 8080 --reload
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit.web", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print('uvicorn is not installed. Run:  pip install -e ".[web]"')
        return 1

    print(f"  Review console on http://{args.host}:{args.port}")
    uvicorn.run("recruit.web.factory:app", host=args.host, port=args.port,
                reload=args.reload, factory=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

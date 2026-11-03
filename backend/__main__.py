"""Entry point: `python -m backend [--check] [--reload]`.

Validates configuration first so a missing API key stops startup with a clear message.
"""

import argparse
import sys

from backend.config import ConfigError, load_config
from backend.runner import check_interpreter


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m backend")
    parser.add_argument("--check", action="store_true", help="validate config and exit")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    try:
        config = load_config()
        interpreter = check_interpreter(config.runner)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        print(f"config OK (Runner interpreter: {interpreter})")
        return 0

    import uvicorn

    uvicorn.run(
        "backend.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=["backend"] if args.reload else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

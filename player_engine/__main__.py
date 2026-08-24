"""Entry point: python -m player_app [serve|resolve|download|...]"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

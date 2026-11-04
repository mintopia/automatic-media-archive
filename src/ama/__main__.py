"""`uv run ama [--config PATH]`: run the app (web UI + background monitors)."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path

import uvicorn

from ama.app import build_services, create_app
from ama.config import ConfigError, load_config


def _setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:  # pythonw.exe (Task Scheduler) has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    # httpx logs each request's full URL at INFO, and a TMDB v3 key travels in the URL.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ama", description="Automatic Media Archive")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("AMA_CONFIG", "ama.toml")),
        help="config file (default: $AMA_CONFIG or ./ama.toml)",
    )
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        if sys.stderr is not None:
            print(f"ama: {e}", file=sys.stderr)
        else:  # no console under pythonw: leave the reason next to the config
            args.config.resolve().with_name("ama-startup-error.log").write_text(
                f"{e}\n", encoding="utf-8"
            )
        sys.exit(2)
    _setup_logging(cfg.paths.log_file)
    logging.getLogger("ama").info("starting; config %s", args.config.resolve())
    services = build_services(cfg)
    uvicorn.run(create_app(services), host=cfg.web.host, port=cfg.web.port, log_config=None)


if __name__ == "__main__":
    main()

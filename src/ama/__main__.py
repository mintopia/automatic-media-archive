"""`uv run ama [run|serve] [--config PATH]`: run the app (web UI + background monitors).

`run` (the default) is the supervisor (ADR 0009, `ama.supervisor`): it starts
`serve` as a child and starts it again when it exits asking to restart; on
Windows it shows the tray icon (`ama.tray`).
`serve` is the server itself; it exits with RESTART_EXIT_CODE after a restart
from the UI, so without a supervisor (or a container restart policy) it stays down.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

import uvicorn

from ama.app import build_services, create_app
from ama.config import ConfigError, PathsConfig, default_config_path, load_config
from ama.settings import upgrade
from ama.setup import run_setup
from ama.supervisor import RESTART_EXIT_CODE, run
from ama.tray import CONTROL_ENV


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


def _message_box(title: str, text: str) -> None:
    """Show `text` in a Windows message box (elsewhere, nothing): pythonw has no console."""
    if sys.platform != "win32":
        return
    import ctypes
    mb_iconerror, mb_setforeground, mb_topmost = 0x10, 0x10000, 0x40000
    ctypes.windll.user32.MessageBoxW(None, text, title,
                                     mb_iconerror | mb_setforeground | mb_topmost)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ama", description="Automatic Media Archive")
    parser.add_argument("command", nargs="?", choices=("run", "serve"), default="run",
                        help="run: the supervisor (default); serve: the server alone")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("AMA_CONFIG") or default_config_path()),
        help=r"config file (default: $AMA_CONFIG or %%LOCALAPPDATA%%\AMA\ama.toml)",
    )
    args = parser.parse_args(argv)
    if args.command == "run":
        sys.exit(run(args.config.resolve()))
    serve(args.config)


def serve(config: Path) -> None:
    control_token = os.environ.pop(CONTROL_ENV, "")  # from `ama run`; tools don't inherit it
    if not config.exists():  # first run: Setup writes the file (ADR 0016)
        _setup_logging(config.resolve().parent / PathsConfig.model_fields["log_file"].default)
        if not run_setup(config, control_token=control_token):
            return  # stopped before it finished
    try:
        upgrade(config)
        cfg = load_config(config)
    except ConfigError as e:
        if sys.stderr is not None:
            print(f"ama: {e}", file=sys.stderr)
        else:  # no console under pythonw: leave the reason next to the config, and say so
            log = config.resolve().with_name("ama-startup-error.log")
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(f"{e}\n", encoding="utf-8")
            _message_box("AMA couldn't start", f"{e}\n\nThis is also in {log}.")
        sys.exit(2)
    _setup_logging(cfg.paths.log_file)
    logging.getLogger("ama").info("starting; config %s", config.resolve())
    services = build_services(cfg, config_path=config)
    # A streaming /events response never finishes on its own: give shutdown a deadline.
    server = uvicorn.Server(uvicorn.Config(create_app(services, control_token), host=cfg.web.host,
                                           port=cfg.web.port, log_config=None,
                                           timeout_graceful_shutdown=3))

    def stop() -> None:  # after the restarting page is on its way to the browser
        threading.Timer(0.5, lambda: setattr(server, "should_exit", True)).start()

    services.restart.on_request = stop
    server.run()
    if services.restart.requested:
        logging.getLogger("ama").info("restarting")
        sys.exit(RESTART_EXIT_CODE)


if __name__ == "__main__":
    main()

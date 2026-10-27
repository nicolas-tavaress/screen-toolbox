"""Logging do app.

- Sempre grava em ~/.local/state/screen-toolbox/screen-toolbox.log (INFO+, rotativo).
- Modo dev (--dev ou SCREEN_TOOLBOX_DEV=1): mostra tudo (DEBUG+) colorido no terminal.
- Modo normal: só WARNING+ no terminal.
"""

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOG_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "screen-toolbox"
LOG_FILE = LOG_DIR / "screen-toolbox.log"

COLORS = {
    logging.DEBUG: "\033[2m",       # cinza
    logging.INFO: "\033[36m",       # ciano
    logging.WARNING: "\033[33m",    # amarelo
    logging.ERROR: "\033[31m",      # vermelho
    logging.CRITICAL: "\033[1;31m",
}
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    def __init__(self, use_color):
        super().__init__("%(asctime)s.%(msecs)03d %(levelname)-7s %(name)-24s %(message)s", "%H:%M:%S")
        self.use_color = use_color

    def format(self, record):
        record.name = record.name.removeprefix("screen_toolbox.")
        text = super().format(record)
        if self.use_color:
            return f"{COLORS.get(record.levelno, '')}{text}{RESET}"
        return text


def setup(dev=False):
    root = logging.getLogger("screen_toolbox")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if dev else logging.WARNING)
    console.setFormatter(ColorFormatter(dev and sys.stderr.isatty()))
    root.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG if dev else logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s [%(threadName)s] %(message)s"))
        root.addHandler(file_handler)
    except OSError as e:
        root.warning("Não foi possível criar o arquivo de log %s: %s", LOG_FILE, e)

    _install_exception_hooks(root)
    root.info("Logging iniciado (modo %s, arquivo: %s)", "dev" if dev else "normal", LOG_FILE)
    return root


def _install_exception_hooks(logger):
    """Exceções não tratadas (inclusive em callbacks GTK e threads) vão para o log."""

    def excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("Exceção não tratada", exc_info=(exc_type, exc, tb))

    def thread_excepthook(args):
        logger.critical("Exceção não tratada na thread %s", args.thread.name if args.thread else "?",
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook


def get(name):
    return logging.getLogger(name)

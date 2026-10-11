# qp_logging.py
"""Centralized logging setup for QPing.

Call setup_logging() once, early in main_entry(), before constructing the
main window. All modules then use:

    import logging
    log = logging.getLogger(__name__)
    log.info("...")

Log file: ~/.config/QPing/qping.log (rotated at 1 MB, 3 backups = 4 MB max).
Console output is also enabled when stderr is a TTY, so running from a
terminal still shows messages.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import utils


_configured = False


def setup_logging(level=logging.INFO, console=True):
    """Configure the root logger. Idempotent: a second call is a no-op."""
    global _configured
    if _configured:
        return
    _configured = True

    os.makedirs(utils.CONFIG_DIR, exist_ok=True)
    log_path = os.path.join(utils.CONFIG_DIR, "qping.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    try:
        fh = RotatingFileHandler(
            log_path, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        print(f"[logging] cannot open {log_path}: {e}", file=sys.stderr)

    if console and sys.stderr.isatty():
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        root.addHandler(ch)

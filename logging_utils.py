# yourpkg/logging_utils.py
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# one canonical place for your format
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

def get_logger(module_name: str,
               log_dir: str | Path = "logs",
               level: int = logging.INFO,
               *,
               rotate: bool = True,
               max_bytes: int = 5_000_000,
               backup_count: int = 3,
               also_console: bool = False) -> logging.Logger:
    """
    Create/return a logger that writes to logs/<module_name>.log
    All loggers share the same format. Handlers are added once.
    """
    logger = logging.getLogger(module_name)
    logger.setLevel(level)

    if logger.handlers:        # already set up -> just return it
        return logger

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logfile = log_dir / f"{module_name}.log"

    if rotate:
        fh = RotatingFileHandler(logfile, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    else:
        fh = logging.FileHandler(logfile, encoding="utf-8")

    fh.setLevel(level)
    fh.setFormatter(_formatter)
    logger.addHandler(fh)

    if also_console:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(_formatter)
        logger.addHandler(sh)

    # prevent messages from also going to ancestor loggers and duplicating
    logger.propagate = False
    return logger
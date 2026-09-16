"""Very small logging helper: one rotating file, no console noise in the EXE."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from utils.config import data_dir, load_config

_configured = False


def _setup() -> None:
    global _configured
    if _configured:
        return
    cfg = load_config()
    log_dir = os.path.join(data_dir(), "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
    except Exception:
        handler = logging.NullHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s")
    )
    root = logging.getLogger("pricematcher")
    root.setLevel(getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO))
    root.addHandler(handler)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _setup()
    return logging.getLogger("pricematcher." + name)

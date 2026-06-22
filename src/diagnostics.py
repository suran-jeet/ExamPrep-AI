from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path


LOGGER_NAME = "examprep"


def log_path() -> Path:
    base = Path(os.getenv("APPDATA", Path.home())) / "ExamPrepAI"
    base.mkdir(parents=True, exist_ok=True)
    return base / "examprep.log"


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def read_recent_log(max_lines: int = 150) -> str:
    path = log_path()
    if not path.exists():
        return "No diagnostic events have been recorded yet."
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])

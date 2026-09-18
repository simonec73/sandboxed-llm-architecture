import faulthandler
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sandboxed-llm")

# Force logging when debugging
is_debugging = sys.gettrace() is not None
logLevel = os.getenv("LOG_LEVEL", "OFF").upper()

if is_debugging and logLevel == "OFF":
    logLevel = "DEBUG"

if logLevel == "OFF":
    logger.disabled = True
else:
    level = getattr(logging, logLevel, logging.INFO)

    # Keep third-party libraries at WARNING+ to avoid noisy and potentially re-entrant debug traces.
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers if this module is imported multiple times.
    if logger.handlers:
        logger.handlers.clear()

    file_handler = logging.FileHandler(
        f"./logs/Log_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.log", # noqa: DTZ005
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"
        )
    )
    logger.addHandler(file_handler)
    if file_handler.stream is not None:
        faulthandler.enable(file=file_handler.stream, all_threads=True)

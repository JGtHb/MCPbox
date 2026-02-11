"""MCPbox Logging Configuration."""

import json
import logging
import sys
from typing import Literal

# Human-readable format for development
DEV_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter that properly escapes all fields.

    Unlike a simple %-format string inside a JSON template, this formatter
    uses json.dumps() to escape special characters (quotes, backslashes,
    newlines) in log messages, preventing malformed JSON output.
    """

    def __init__(self):
        super().__init__(datefmt="%Y-%m-%dT%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    format_type: Literal["structured", "dev"] = "dev",
) -> None:
    """
    Configure application logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: Log format - 'structured' for JSON, 'dev' for readable
    """
    if format_type == "structured":
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logging.root.handlers = [handler]
        logging.root.setLevel(getattr(logging, level.upper()))
    else:
        logging.basicConfig(
            level=getattr(logging, level.upper()),
            format=DEV_FORMAT,
            datefmt="%Y-%m-%d %H:%M:%S",
            stream=sys.stdout,
            force=True,
        )

    # Set third-party loggers to WARNING to reduce noise
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Keep SQLAlchemy quiet unless debugging
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if level.upper() == "DEBUG" else logging.WARNING
    )

    # Log startup
    logger = logging.getLogger("mcpbox")
    logger.info(f"Logging configured: level={level}, format={format_type}")


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the mcpbox prefix."""
    return logging.getLogger(f"mcpbox.{name}")

"""MCPbox Logging Configuration."""

import logging
import sys
from typing import Literal

# Structured log format for production
STRUCTURED_FORMAT = (
    '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
    '"logger": "%(name)s", "message": "%(message)s"}'
)

# Human-readable format for development
DEV_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


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
    log_format = STRUCTURED_FORMAT if format_type == "structured" else DEV_FORMAT

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # Override any existing configuration
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

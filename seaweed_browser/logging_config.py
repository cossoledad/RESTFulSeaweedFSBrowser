import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

from .core import APP_NAME


_qt_message_handler = None


def get_log_dir() -> str:
    appdata = os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    log_dir = os.path.join(appdata, APP_NAME, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def configure_logging(component: str, log_path: Optional[str] = None) -> str:
    global _qt_message_handler
    resolved_path = log_path or os.path.join(get_log_dir(), f"{component}.log")
    os.makedirs(os.path.dirname(os.path.abspath(resolved_path)), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(
        resolved_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)

    def handle_uncaught_exception(exc_type, exc_value, traceback) -> None:
        logging.getLogger("uncaught").critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, traceback),
        )
        sys.__excepthook__(exc_type, exc_value, traceback)

    sys.excepthook = handle_uncaught_exception

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handle_qt_message(message_type, context, message) -> None:
        category = getattr(context, "category", "qt") or "qt"
        logging.getLogger(f"qt.{category}").log(
            levels.get(message_type, logging.INFO),
            message,
        )

    _qt_message_handler = handle_qt_message
    qInstallMessageHandler(_qt_message_handler)
    logging.getLogger(__name__).info("Logging initialized: %s", resolved_path)
    return resolved_path

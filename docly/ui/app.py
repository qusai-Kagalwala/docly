"""Application bootstrap: QApplication, font, theme, crash handling."""

from __future__ import annotations

import signal
import sys
import threading
from collections.abc import Callable
from types import TracebackType

from PySide6.QtCore import QMessageLogContext, Qt, QtMsgType, QTimer, qInstallMessageHandler
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from docly import config
from docly.logger import current_log_file, get_logger, setup_logging
from docly.presets import PresetLoadResult, default_presets
from docly.ui.main_window import MainWindow
from docly.ui.settings_store import SettingsStore
from docly.ui.theme import ThemeManager

log = get_logger(__name__)
qt_log = get_logger("qt")

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI"]
BASE_FONT_PX = 13

_QT_LEVELS = {
    QtMsgType.QtDebugMsg: 10,
    QtMsgType.QtInfoMsg: 20,
    QtMsgType.QtWarningMsg: 30,
    QtMsgType.QtCriticalMsg: 40,
    QtMsgType.QtFatalMsg: 50,
}


def build_app_font() -> QFont:
    """Segoe UI Variable, falling back to Segoe UI, at 13px."""
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(BASE_FONT_PX)
    return font


def _qt_message_handler(msg_type: QtMsgType, _context: QMessageLogContext, message: str) -> None:
    """Send Qt's own warnings into our log instead of the console."""
    qt_log.log(_QT_LEVELS.get(msg_type, 30), message)


def _set_windows_app_id() -> None:
    """Give Docly its own taskbar identity on Windows.

    Without this, Windows groups the window under python.exe and shows
    Python's icon on the taskbar while running from source.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.APP_ID)
    except Exception:  # pragma: no cover - Windows only
        log.debug("Could not set AppUserModelID", exc_info=True)


def make_exception_hook(
    parent_getter: Callable[[], QWidget | None] = lambda: None,
) -> Callable[[type[BaseException], BaseException, TracebackType | None], None]:
    """Build a ``sys.excepthook`` that logs the error and shows a friendly dialog.

    In PySide6, an exception raised inside a slot reaches ``sys.excepthook``.
    Without a hook it is only printed to a console that a packaged app
    doesn't have, so problems would vanish silently.
    """
    showing = False

    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        nonlocal showing
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        if showing or QApplication.instance() is None:
            return
        showing = True
        try:
            log_file = current_log_file()
            where = f"\n\nDetails were saved to:\n{log_file}" if log_file else ""
            QMessageBox.critical(
                parent_getter(),
                f"{config.APP_NAME} — something went wrong",
                "Docly hit an unexpected error. Your files were not changed." + where,
            )
        except Exception:  # never let the error handler itself crash
            log.exception("Could not show the error dialog")
        finally:
            showing = False

    return hook


def _thread_exception_hook(args: threading.ExceptHookArgs) -> None:
    """Log exceptions from Python threads (dialogs must stay on the UI thread)."""
    log.critical(
        "Unhandled exception in thread %s",
        getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def install_ctrl_c_handler(app: QApplication) -> QTimer:
    """Make Ctrl+C in the terminal close Docly cleanly.

    Qt's event loop runs in C++, so Python only notices Ctrl+C when some
    Python code happens to run — often in the middle of a paint event, which
    prints a scary ``KeyboardInterrupt`` traceback. Instead we catch the
    signal ourselves and ask Qt to quit. The idle timer wakes Python a few
    times a second so the signal is noticed promptly.
    """
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    timer = QTimer(app)
    timer.setInterval(250)
    timer.timeout.connect(lambda: None)
    timer.start()
    return timer


def load_and_log_presets() -> PresetLoadResult:
    """Load presets and record the outcome in the log.

    Phase 4 hands the result to the Photo page; for now this proves the
    presets load on a real machine.
    """
    result = default_presets()
    skipped = result.skipped_count
    from_user = sum(1 for p in result.presets if p.origin == "user")
    log.info(
        "Loaded %d presets (%d skipped, %d from user file)",
        len(result.presets),
        skipped,
        from_user,
    )
    for issue in result.issues:
        level = {"error": 30, "warning": 30, "info": 20}.get(issue.level, 30)
        log.log(level, "Preset %s: %s", issue.level, issue)
    return result


def run(argv: list[str] | None = None) -> int:
    """Start Docly and return the process exit code."""
    log_path = setup_logging()
    log.info("Starting %s %s (Python %s)", config.APP_NAME, config.APP_VERSION, sys.version.split()[0])
    if log_path:
        log.info("Logging to %s", log_path)

    _set_windows_app_id()
    # Crisp rendering at 125 % / 150 % Windows scaling instead of rounding.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.ORG_NAME)
    # Fusion is Qt's neutral cross-platform style; it respects our palette
    # and stylesheet consistently, unlike the native Windows style.
    app.setStyle("Fusion")
    app.setFont(build_app_font())
    qInstallMessageHandler(_qt_message_handler)
    install_ctrl_c_handler(app)

    # Install crash handling before building the UI, so even an error while
    # creating the window is logged and shown instead of vanishing.
    holder: dict[str, QWidget] = {}
    sys.excepthook = make_exception_hook(lambda: holder.get("window"))
    threading.excepthook = _thread_exception_hook

    load_and_log_presets()
    theme = ThemeManager(app, SettingsStore())
    window = MainWindow(theme)
    holder["window"] = window
    window.show()

    exit_code = app.exec()
    log.info("Exiting with code %s", exit_code)
    return exit_code
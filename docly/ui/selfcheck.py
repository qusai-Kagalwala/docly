"""``Docly.exe --self-check``: prove a packaged build really works.

A frozen app can start fine and still be broken: a missing Qt plugin, an
asset PyInstaller didn't copy, or an OpenCV/pikepdf library that won't
load. This runs every engine once on tiny generated files, opens the main
window, and writes a plain report:

    PASS  presets        20 presets
    PASS  photo          IBPS — Photograph: 18.2 KB, Ready
    FAIL  pdf render     QtPdf couldn't open the page
    ...

The report goes to ``self-check.txt`` in Docly's data folder (the packaged
app has no console) and the exit code is 0 only if everything passed.
``tools/build.py`` runs it after every build.
"""

from __future__ import annotations

import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from docly import config
from docly.logger import get_logger

log = get_logger(__name__)

REPORT_NAME = "self-check.txt"
Check = Callable[[Path], str]


def _photo(folder: Path) -> Path:
    """A small portrait-like JPEG: a face-coloured oval on a grey wall."""
    image = Image.new("RGB", (480, 640), (150, 155, 160))
    draw = ImageDraw.Draw(image)
    draw.ellipse((150, 120, 330, 360), fill=(205, 160, 130))
    draw.rectangle((110, 380, 370, 640), fill=(40, 60, 110))
    path = folder / "photo.jpg"
    image.save(path, quality=92)
    return path


def check_presets(_folder: Path) -> str:
    from docly.presets import default_presets

    result = default_presets()
    if not result.presets:
        raise RuntimeError("no presets loaded")
    return f"{len(result.presets)} presets"


def check_assets(_folder: Path) -> str:
    missing = [p for p in (config.APP_ICON_PATH, config.ICONS_DIR / "check.svg", config.NOTICES_PATH) if not p.exists()]
    if missing:
        raise RuntimeError("missing " + ", ".join(str(p) for p in missing))
    from docly.ui.icons import render_icon
    from docly.ui.theme import LIGHT

    if render_icon("check", LIGHT.text, 16).isNull():
        raise RuntimeError("SVG icons don't render (QtSvg missing?)")
    return "icons, app icon and licence notices present"


def check_photo(folder: Path) -> str:
    from docly.core.background import BackgroundOptions, model_available
    from docly.core.image_io import load_image
    from docly.core.pipeline import process_loaded
    from docly.presets import default_presets

    if not model_available():
        raise RuntimeError("background model file missing")
    preset = next(p for p in default_presets().presets if p.id == "in-ibps-photo")
    result = process_loaded(load_image(_photo(folder)), preset, background=BackgroundOptions())
    verdict = "Ready" if result.passed else "needs attention"
    return f"{preset.name}: {result.size_bytes / 1024:.1f} KB, background changed, {verdict}"


def check_signature(_folder: Path) -> str:
    from docly.core.signature import clean_signature

    paper = Image.new("RGB", (600, 220), (225, 222, 215))
    ImageDraw.Draw(paper).line([(60, 150), (200, 60), (330, 160), (520, 70)], fill=(30, 30, 60), width=7)
    result = clean_signature(paper)
    return f"cleaned to {result.image.width} × {result.image.height} px"


def check_pdf(folder: Path) -> str:
    from docly.core.pdf_compress import compress_to_target
    from docly.core.pdf_fill import fill_pdf, text_item
    from docly.core.pdf_ops import close_all, images_to_pdf, load_source

    photo = load_source(_photo(folder))
    made = images_to_pdf([photo])
    pdf_path = folder / "made.pdf"
    pdf_path.write_bytes(made.data)
    source = load_source(pdf_path)
    try:
        filled = fill_pdf(source, [text_item(0, 72, 72, "Docly self-check")])
    finally:
        close_all([photo, source])
    shrunk = compress_to_target(filled.data, 60_000, 0)
    (folder / "filled.pdf").write_bytes(shrunk.data)
    return f"made, filled and shrunk to {len(shrunk.data) / 1024:.0f} KB"


def check_pdf_render(folder: Path) -> str:
    from docly.ui.pages.sign_page import render_page

    image = render_page((folder / "filled.pdf").read_bytes(), None, 0)
    if image.isNull():
        raise RuntimeError("QtPdf couldn't draw the page")
    return f"page drawn at {image.width()} × {image.height()} px"


def check_window(_folder: Path) -> str:
    from docly.presets import default_presets
    from docly.ui.main_window import MainWindow
    from docly.ui.settings_store import SettingsStore
    from docly.ui.theme import ThemeManager

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    window = MainWindow(ThemeManager(app, SettingsStore()), default_presets())
    window.show()
    for page_id in window.page_ids():
        window.show_page(page_id)
        app.processEvents()
    window.close()
    window.deleteLater()
    return f"opened {len(window.page_ids())} pages"


CHECKS: tuple[tuple[str, Check], ...] = (
    ("presets", check_presets),
    ("assets", check_assets),
    ("photo", check_photo),
    ("signature", check_signature),
    ("pdf", check_pdf),
    ("pdf render", check_pdf_render),
    ("window", check_window),
)


def run_self_check(report_path: Path | None = None) -> int:
    """Run every check (a QApplication must exist). Returns 0 if all passed."""
    lines = [f"{config.APP_NAME} {config.APP_VERSION} self-check (frozen={config.IS_FROZEN})"]
    failures = 0
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="docly-selfcheck-") as temp:
        folder = Path(temp)
        for name, check in CHECKS:
            began = time.perf_counter()
            try:
                detail = check(folder)
                status = "PASS"
            except Exception as exc:  # report every failure, keep going
                failures += 1
                status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
                log.error("Self-check %s failed\n%s", name, traceback.format_exc())
            lines.append(f"{status}  {name:<11} {detail}  ({time.perf_counter() - began:.1f} s)")
    lines.append(f"{'ALL PASSED' if failures == 0 else f'{failures} FAILED'} in {time.perf_counter() - started:.1f} s")
    text = "\n".join(lines) + "\n"
    target = report_path or config.app_data_dir() / REPORT_NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError:
        log.warning("Could not write %s", target)
    log.info("Self-check:\n%s", text)
    return 0 if failures == 0 else 1


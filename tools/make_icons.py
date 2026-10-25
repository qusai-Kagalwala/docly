"""Make every app icon file from the two SVGs in ``assets/app/``.

    python tools/make_icons.py          # writes the files
    python tools/make_icons.py --check  # exits 1 if any file is missing or out of date

Outputs
-------
* ``assets/app/docly.ico`` — the .exe / window icon (16–256 px). Sizes up to
  24 px use ``docly-app-small.svg`` (bigger page, bolder tick) so they stay
  readable in Explorer's details view and the title bar.
* ``assets/app/docly-256.png`` — the window icon Qt loads at run time.
* ``packaging/msix/Assets/*.png`` — the logos the MSIX manifest and the
  Microsoft Store need, at every scale Windows asks for (100–400 %).
* ``packaging/store/*.png`` — square logos to upload on the Store listing page.

Desktop note: Windows picks an icon size to match the display scaling
(125 %, 150 %…). Supplying each size means it never has to stretch a small
one, which is what makes icons look blurry.

Rendering uses Qt's SVG renderer and Pillow, both already Docly
dependencies. Qt antialiases edges a tiny bit differently on Windows and
Linux, so ``--check`` compares pixels with a small tolerance instead of
bytes, and the files are only rewritten when they really differ.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "assets" / "app"
MSIX_ASSETS = ROOT / "packaging" / "msix" / "Assets"
STORE_ART = ROOT / "packaging" / "store"
ICON_SVG = APP_DIR / "docly-app.svg"
SMALL_SVG = APP_DIR / "docly-app-small.svg"

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SMALL_MAX = 24
SCALES = (100, 125, 150, 200, 400)
TARGET_SIZES = (16, 24, 32, 48, 256)

Painter = Callable[[int, int], Image.Image]


# ----------------------------------------------------------------------
def _render(svg: Path, width: int, height: int, icon_size: int | None = None) -> Image.Image:
    """``svg`` drawn centred on a transparent ``width`` × ``height`` canvas."""
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"Can't read {svg}")
    side = icon_size if icon_size is not None else min(width, height)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF((width - side) / 2, (height - side) / 2, side, side))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def icon(size: int) -> Image.Image:
    """The square app icon at ``size`` px (small artwork at 24 px and below)."""
    return _render(SMALL_SVG if size <= SMALL_MAX else ICON_SVG, size, size)


def tile(width: int, height: int) -> Image.Image:
    """Start-menu style tile: the icon at 60 % of the height, centred."""
    side = round(height * 0.6)
    svg = SMALL_SVG if side <= SMALL_MAX else ICON_SVG
    return _render(svg, width, height, side)


def png_bytes(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def ico_bytes() -> bytes:
    images = [icon(size) for size in ICO_SIZES]
    out = io.BytesIO()
    images[-1].save(out, "ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    return out.getvalue()


# ----------------------------------------------------------------------
def planned_files() -> dict[Path, Callable[[], bytes]]:
    """Every output path and how to make it."""
    files: dict[Path, Callable[[], bytes]] = {
        APP_DIR / "docly.ico": ico_bytes,
        APP_DIR / "docly-256.png": lambda: png_bytes(icon(256)),
    }

    def add(name: str, make: Callable[[], Image.Image]) -> None:
        files[MSIX_ASSETS / name] = lambda: png_bytes(make())

    for scale in SCALES:
        factor = scale / 100
        add(f"Square44x44Logo.scale-{scale}.png", lambda f=factor: icon(round(44 * f)))
        add(f"Square150x150Logo.scale-{scale}.png", lambda f=factor: tile(round(150 * f), round(150 * f)))
        add(f"Wide310x150Logo.scale-{scale}.png", lambda f=factor: tile(round(310 * f), round(150 * f)))
        add(f"StoreLogo.scale-{scale}.png", lambda f=factor: icon(round(50 * f)))
    # Partner Center > Store listings > Store logos (optional, shown on some Windows versions).
    files[STORE_ART / "box-art-1080.png"] = lambda: png_bytes(icon(1080))
    files[STORE_ART / "box-art-2160.png"] = lambda: png_bytes(icon(2160))
    files[STORE_ART / "logo-300.png"] = lambda: png_bytes(icon(300))
    for size in TARGET_SIZES:
        # "unplated" = shown straight on the taskbar, without a coloured plate behind it.
        add(f"Square44x44Logo.targetsize-{size}.png", lambda s=size: icon(s))
        add(f"Square44x44Logo.targetsize-{size}_altform-unplated.png", lambda s=size: icon(s))
    return files


#: "Same picture" = under 10 % of pixels differ noticeably (> 48 of 255 in any
#: channel; antialiased edges do) and the average difference stays tiny.
PIXEL_TOLERANCE = 48
CHANGED_SHARE = 0.10
MEAN_TOLERANCE = 2.0


def _frames(data: bytes) -> list[Image.Image]:
    """Every picture in a PNG (one) or an ICO (one per size), as RGBA."""
    image = Image.open(io.BytesIO(data))
    if image.format != "ICO":
        return [image.convert("RGBA")]
    frames = []
    for size in sorted(image.info["sizes"]):
        frame = Image.open(io.BytesIO(data))
        frame.size = size
        frame.load()
        frames.append(frame.convert("RGBA"))
    return frames


def same_picture(old: bytes, new: bytes) -> bool:
    """True if two icon files show the same picture (tiny antialiasing
    differences between Windows and Linux don't count)."""
    import numpy as np

    try:
        old_frames, new_frames = _frames(old), _frames(new)
    except Exception:  # unreadable or wrong kind of file
        return False
    if [f.size for f in old_frames] != [f.size for f in new_frames]:
        return False
    for a, b in zip(old_frames, new_frames, strict=True):
        diff = np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16))
        changed = (diff.max(axis=2) > PIXEL_TOLERANCE).mean()
        if changed > CHANGED_SHARE or diff.mean() > MEAN_TOLERANCE:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only check the files are present and current")
    args = parser.parse_args(argv)
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (must stay alive)
    stale: list[Path] = []
    for path, make in planned_files().items():
        data = make()
        if path.exists() and same_picture(path.read_bytes(), data):
            continue
        if args.check:
            stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path.relative_to(ROOT)} ({len(data):,} bytes)")
    if stale:
        print("Out of date (run python tools/make_icons.py):")
        for path in stale:
            print(f"  {path.relative_to(ROOT)}")
        return 1
    if args.check:
        print("All icon files are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Write ``assets/licenses/THIRD_PARTY_NOTICES.txt``: the licence of everything
the packaged app contains, shown in About > Open-source licences.

    python tools/make_notices.py

Run it after changing or upgrading dependencies, then commit the file.
It reads the licence files that pip installed with each package, so run it
in the same virtual environment you build with.

Why it matters: Docly is MIT, but it ships other people's code. Most of
those licences (Apache, BSD, MIT, MPL) only ask for their text and
copyright to travel with the app. Qt / PySide6 are LGPL-3.0: that also
asks that people can swap in their own build of Qt — the one-folder build
keeps Qt as separate DLLs, which allows that — and that we say where Qt's
source is.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import Distribution, PackageNotFoundError, distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "licenses" / "THIRD_PARTY_NOTICES.txt"
LICENSES = ROOT / "assets" / "licenses"

#: What Docly imports directly; their own dependencies are found from metadata.
TOP_LEVEL = ("PySide6-Essentials", "Pillow", "opencv-python-headless", "pikepdf")
#: Parts of the PySide6 family Docly doesn't bundle (same licence anyway).
SKIP = {"pyside6", "pyside6-addons", "pyside6-webengine", "pyside6-pdf"}
LICENCE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.IGNORECASE)
RULE = "=" * 78

QT_NOTE = """\
Qt for Python (PySide6, Shiboken6) and the Qt libraries it contains
(QtCore, QtGui, QtWidgets, QtSvg, QtPdf, QtNetwork and their plugins)
are used under the GNU Lesser General Public License version 3 (below,
with the GNU GPL version 3 it builds on).

Docly uses Qt unmodified. The Qt libraries are separate files in the
app's folder, so they can be replaced with another compatible build.
Source code:
  Qt:       https://download.qt.io/official_releases/qt/
  PySide6:  https://code.qt.io/cgit/pyside/pyside-setup.git/
Qt's own third-party components (including PDFium, BSD-3-Clause, used by
QtPdf) are listed at https://doc.qt.io/qt-6/licenses-used-in-qt.html
"""


def dependencies(names: tuple[str, ...] = TOP_LEVEL) -> list[Distribution]:
    """The packages named plus everything they require (no extras), A–Z."""
    found: dict[str, Distribution] = {}

    def walk(name: str) -> None:
        key = name.lower().replace("_", "-")
        if key in found or key in SKIP:
            return
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            return  # optional / platform-only dependency that isn't installed
        found[key] = dist
        for requirement in dist.requires or []:
            if "extra ==" in requirement:
                continue
            walk(re.split(r"[ ;<>=!~\[(]", requirement, maxsplit=1)[0])

    for name in names:
        walk(name)
    return [found[k] for k in sorted(found)]


def licence_texts(dist: Distribution) -> list[tuple[str, str]]:
    texts = []
    for file in dist.files or []:
        if LICENCE_FILE.search(str(file).replace("\\", "/")) and not str(file).endswith(".py"):
            try:
                texts.append((str(file), Path(str(dist.locate_file(file))).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return texts


def _section(title: str, body: str) -> str:
    return f"{RULE}\n{title}\n{RULE}\n\n{body.strip()}\n\n"


def build_notices() -> str:
    parts = [
        "Docly — third-party software notices\n\n"
        "Docly itself is MIT-licensed (https://github.com/qusai-Kagalwala/docly).\n"
        "The packaged app also contains the software below, under these licences.\n\n"
    ]
    python_licence = Path(sys.base_prefix) / "LICENSE.txt"
    parts.append(_section(
        f"Python {sys.version.split()[0]} — Python Software Foundation License",
        python_licence.read_text(encoding="utf-8", errors="replace") if python_licence.exists()
        else "See https://docs.python.org/3/license.html",
    ))  # fmt: skip
    parts.append(_section("Qt and Qt for Python (PySide6)", QT_NOTE))
    for dist in dependencies():
        name, version = dist.metadata["Name"], dist.version
        if name.lower().startswith(("pyside6", "shiboken6")):
            continue  # covered by the Qt section
        licence = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        body = [f"Licence: {licence.splitlines()[0] if licence else 'see below'}"]
        for path, text in licence_texts(dist):
            body.append(f"--- {path} ---\n{text.strip()}")
        parts.append(_section(f"{name} {version}", "\n\n".join(body)))
    parts.append(_section("Lucide icons — ISC License", (ROOT / "assets" / "icons" / "LICENSE-lucide.txt").read_text(encoding="utf-8")))
    model = ROOT / "assets" / "models"
    parts.append(_section(
        "MODNet portrait matting model — Apache License 2.0",
        (model / "NOTICE-modnet.txt").read_text(encoding="utf-8") + "\n\n" + (model / "LICENSE-modnet.txt").read_text(encoding="utf-8"),
    ))  # fmt: skip
    parts.append(_section("GNU Lesser General Public License v3.0", (LICENSES / "LGPL-3.0.txt").read_text(encoding="utf-8")))
    parts.append(_section("GNU General Public License v3.0", (LICENSES / "GPL-3.0.txt").read_text(encoding="utf-8")))
    return "".join(parts)


def main() -> int:
    text = build_notices()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    names = ", ".join(d.metadata["Name"] for d in dependencies())
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text) / 1024:.0f} KB) covering Python, Qt, {names}, Lucide, MODNet")
    return 0


if __name__ == "__main__":
    sys.exit(main())

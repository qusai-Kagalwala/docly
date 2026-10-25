"""Build the packaged app: ``dist/Docly/Docly.exe``.

    pip install -r requirements-build.txt     (once)
    python tools/build.py

Steps: check the icon files, write the .exe's version info, run
PyInstaller with ``packaging/docly.spec``, then run the built app with
``--self-check`` (every engine on tiny files, plus the main window) and
print its report and the build's size.

Works on Linux and macOS too (handy for checking the recipe), but the
Microsoft Store build must be made on Windows.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "docly.spec"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP_DIR = DIST / "Docly"
SELF_CHECK_TIMEOUT = 180  # seconds; the first run of a fresh build is the slowest

sys.path.insert(0, str(ROOT))
from docly import __version__  # noqa: E402
from docly.config import APP_NAME, CREATOR_NAME  # noqa: E402


def version_tuple(version: str = __version__) -> tuple[int, int, int, int]:
    """``"1.2.3"`` → ``(1, 2, 3, 0)``: Windows wants exactly four numbers."""
    parts = [int(p) for p in version.split("+")[0].split("-")[0].split(".")[:4] if p.isdigit()]
    return tuple((parts + [0, 0, 0, 0])[:4])  # type: ignore[return-value]


def version_info_text(version: str = __version__) -> str:
    """PyInstaller's version-resource file: what File Explorer shows under
    Properties › Details for Docly.exe."""
    numbers = version_tuple(version)
    dotted = ".".join(str(n) for n in numbers)
    fields = {
        "CompanyName": CREATOR_NAME,
        "FileDescription": f"{APP_NAME} — photos, signatures and PDFs ready to upload",
        "FileVersion": dotted,
        "InternalName": APP_NAME,
        "LegalCopyright": f"© {CREATOR_NAME}. MIT licence.",
        "OriginalFilename": f"{APP_NAME}.exe",
        "ProductName": APP_NAME,
        "ProductVersion": version,
    }
    strings = ",\n".join(f"          StringStruct({k!r}, {v!r})" for k, v in fields.items())
    return f"""# Made by tools/build.py — don't edit by hand.
VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
{strings}
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def executable() -> Path:
    return APP_DIR / (f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME)


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def biggest(path: Path, count: int = 8) -> list[tuple[int, str]]:
    """Largest top-level items inside the app's ``_internal`` folder."""
    inner = path / "_internal" if (path / "_internal").exists() else path
    sizes = []
    for child in inner.iterdir():
        size = folder_size(child) if child.is_dir() else child.stat().st_size
        sizes.append((size, child.name))
    return sorted(sizes, reverse=True)[:count]


def run_self_check() -> tuple[int, str, float]:
    """Start the built app with ``--self-check`` in a throwaway data folder."""
    with tempfile.TemporaryDirectory(prefix="docly-build-check-") as data:
        env = {**os.environ, "DOCLY_DATA_DIR": data}
        if sys.platform != "win32":
            env.setdefault("QT_QPA_PLATFORM", "offscreen")  # no screen needed off Windows
        started = time.perf_counter()
        try:
            result = subprocess.run([str(executable()), "--self-check"], env=env, timeout=SELF_CHECK_TIMEOUT, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = -1
        seconds = time.perf_counter() - started
        report = Path(data) / "self-check.txt"
        text = report.read_text(encoding="utf-8") if report.exists() else "(no report written — see the log)\n"
        log_file = Path(data) / "logs" / "docly.log"
        if code != 0 and log_file.exists():
            text += "\n--- log ---\n" + log_file.read_text(encoding="utf-8", errors="replace")[-4000:]
        return code, text, seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/Docly with PyInstaller and test it.")
    parser.add_argument("--skip-check", action="store_true", help="don't run the built app's self-check")
    args = parser.parse_args(argv)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller isn't installed. Run:  pip install -r requirements-build.txt")
        return 2

    print("1/4  Checking icon files…")
    if subprocess.run([sys.executable, str(ROOT / "tools" / "make_icons.py"), "--check"], check=False).returncode:
        print("     Run  python tools/make_icons.py  and build again.")
        return 1

    print(f"2/4  Version info for {APP_NAME} {__version__}…")
    BUILD.mkdir(exist_ok=True)
    (BUILD / "version_info.txt").write_text(version_info_text(), encoding="utf-8")

    print("3/4  Running PyInstaller (a few minutes)…")
    shutil.rmtree(APP_DIR, ignore_errors=True)
    started = time.perf_counter()
    command = [
        sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean",
        "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--log-level", "WARN",
    ]  # fmt: skip
    if subprocess.run(command, cwd=ROOT, check=False).returncode:
        print("PyInstaller failed — see the messages above.")
        return 1
    size = folder_size(APP_DIR)
    print(f"     Built {executable().relative_to(ROOT)} in {time.perf_counter() - started:.0f} s; "
          f"folder size {size / 1_048_576:.0f} MB")  # fmt: skip
    for item_size, name in biggest(APP_DIR):
        print(f"       {item_size / 1_048_576:7.1f} MB  {name}")

    if args.skip_check:
        return 0
    print("4/4  Self-check of the built app…")
    code, report, seconds = run_self_check()
    print("     " + report.replace("\n", "\n     ").rstrip())
    print(f"     Finished in {seconds:.1f} s (exit code {code}).")
    if code != 0:
        print("The build is broken: fix the FAIL lines above before packaging.")
        return 1
    print(f"Done. Try it:  {executable().relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

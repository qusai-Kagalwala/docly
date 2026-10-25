"""Wrap ``dist/Docly`` into an MSIX package for the Microsoft Store.

    python tools/build.py                 (first: makes dist/Docly)
    python tools/make_msix.py             -> dist/Docly-<version>.msix        (upload this to the Store)
    python tools/make_msix.py --test-cert -> also dist/Docly-<version>-test.msix, signed for your own PC

Needs the free Windows SDK (only "Windows App Certification Kit" and
"Windows SDK Signing Tools for Desktop Apps" are used). It provides:

* ``makepri``  — indexes the logos so Windows picks the right size for
  your display scaling (Square44x44Logo.scale-150.png at 150 %, …);
* ``makeappx`` — packs the folder into the .msix file;
* ``signtool`` — signs the test package. The Store signs the real one.

Desktop note: Windows only installs signed packages. For testing before the
Store, this script makes a *self-signed* certificate whose name matches
your publisher ID; you trust it once on your PC (see the printed steps).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
MSIX_DIR = ROOT / "packaging" / "msix"
TEMPLATE = MSIX_DIR / "AppxManifest.xml"
IDENTITY = MSIX_DIR / "identity.json"
ASSETS = MSIX_DIR / "Assets"
APP_DIR = ROOT / "dist" / "Docly"
STAGE = ROOT / "build" / "msix"
CERT_DIR = ROOT / "build" / "cert"
CERT_PASSWORD = "docly-test"  # protects a throwaway test certificate only; never used for the Store
SDK_ROOT = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from build import version_tuple  # noqa: E402
from docly import __version__  # noqa: E402


# ----------------------------------------------------------------------
def load_identity(path: Path = IDENTITY) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def msix_version(version: str = __version__) -> str:
    """Four numbers, the last one 0 — the Store reserves the fourth."""
    major, minor, patch, _revision = version_tuple(version)
    return f"{major}.{minor}.{patch}.0"


def render_manifest(identity: dict[str, str], version: str = __version__, template: Path = TEMPLATE) -> str:
    values = {key: escape(value, {'"': "&quot;"}) for key, value in identity.items()}
    values["version"] = msix_version(version)
    text = template.read_text(encoding="utf-8")
    missing = sorted(set(re.findall(r"\{(\w+)\}", text)) - set(values))
    if missing:
        raise SystemExit(f"identity.json is missing: {', '.join(missing)}")
    return text.format(**values)


def logos_in(manifest: str) -> list[str]:
    """Logo files the manifest names, e.g. ``Assets\\StoreLogo.png``."""
    return sorted(set(re.findall(r"(Assets\\[\w.]+\.png)", manifest)))


def missing_logos(manifest: str, assets: Path = ASSETS) -> list[str]:
    """Logos with no file at all (plain or with a .scale-/.targetsize- qualifier)."""
    missing = []
    for logo in logos_in(manifest):
        stem = Path(logo.replace("\\", "/")).stem
        if not any(assets.glob(f"{stem}.png")) and not any(assets.glob(f"{stem}.*.png")):
            missing.append(logo)
    return missing


def find_sdk_tool(name: str, sdk_root: Path = SDK_ROOT) -> Path | None:
    """Newest ``<sdk>/bin/<version>/x64/<name>.exe``."""
    candidates = sorted(sdk_root.glob(f"10.*/x64/{name}.exe"), key=lambda p: [int(n) for n in p.parent.parent.name.split(".")])
    return candidates[-1] if candidates else None


def run(command: list[str | Path], **kwargs) -> None:  # noqa: ANN003
    print("     >", " ".join(str(c) for c in command[:3]), "…")
    result = subprocess.run([str(c) for c in command], capture_output=True, text=True, check=False, **kwargs)
    if result.returncode:
        print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
        raise SystemExit(f"{Path(str(command[0])).name} failed (exit {result.returncode}).")


# ----------------------------------------------------------------------
def stage(identity: dict[str, str]) -> str:
    """Lay out build/msix: AppxManifest.xml, Assets/, Docly/ (the frozen app)."""
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    shutil.copytree(APP_DIR, STAGE / "Docly")
    shutil.copytree(ASSETS, STAGE / "Assets")
    manifest = render_manifest(identity)
    (STAGE / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
    return manifest


def make_test_certificate(publisher: str) -> tuple[Path, Path]:
    """A self-signed code-signing certificate named exactly like the publisher."""
    pfx, cer = CERT_DIR / "docly-test.pfx", CERT_DIR / "docly-test.cer"
    if pfx.exists() and cer.exists():
        return pfx, cer
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    script = f"""
$cert = New-SelfSignedCertificate -Type Custom -Subject '{publisher}' -KeyUsage DigitalSignature `
  -FriendlyName 'Docly test signing' -CertStoreLocation 'Cert:\\CurrentUser\\My' `
  -TextExtension @('2.5.29.37={{text}}1.3.6.1.5.5.7.3.3', '2.5.29.19={{text}}')
$password = ConvertTo-SecureString -String '{CERT_PASSWORD}' -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath '{pfx}' -Password $password | Out-Null
Export-Certificate -Cert $cert -FilePath '{cer}' | Out-Null
"""
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
    return pfx, cer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package dist/Docly as MSIX.")
    parser.add_argument("--test-cert", action="store_true", help="also make a package signed for testing on this PC")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("MSIX packages are made on Windows (the tools come with the Windows SDK).")
        return 2
    tools = {name: find_sdk_tool(name) for name in ("makepri", "makeappx", "signtool")}
    if not all(tools.values()):
        missing = ", ".join(name for name, path in tools.items() if path is None)
        print(f"Windows SDK tools not found ({missing}). Install the Windows SDK, choosing\n"
              '"Windows App Certification Kit" and "Windows SDK Signing Tools for Desktop Apps".')  # fmt: skip
        return 2
    if not (APP_DIR / "Docly.exe").exists():
        print("dist/Docly/Docly.exe not found. Run  python tools/build.py  first.")
        return 1

    identity = load_identity()
    version = msix_version()
    print(f"1/4  Staging Docly {version} for {identity['name']}…")
    manifest = stage(identity)
    if missing_logos(manifest):
        print("Missing logos:", ", ".join(missing_logos(manifest)), "— run python tools/make_icons.py")
        return 1

    print("2/4  Indexing logos (makepri)…")
    config = ROOT / "build" / "priconfig.xml"
    run([tools["makepri"], "createconfig", "/cf", config, "/dq", "en-US", "/o"])
    run([tools["makepri"], "new", "/pr", STAGE, "/cf", config, "/of", STAGE / "resources.pri", "/o"])

    print("3/4  Packing (makeappx)…")
    store_package = ROOT / "dist" / f"Docly-{version}.msix"
    run([tools["makeappx"], "pack", "/d", STAGE, "/p", store_package, "/o"])
    print(f"     {store_package.relative_to(ROOT)}  ({store_package.stat().st_size / 1_048_576:.0f} MB) — upload this one")

    if not args.test_cert:
        print("4/4  Skipped the test package (add --test-cert to make one).")
        return 0
    print("4/4  Test package signed with a self-signed certificate…")
    pfx, cer = make_test_certificate(identity["publisher"])
    test_package = ROOT / "dist" / f"Docly-{version}-test.msix"
    shutil.copyfile(store_package, test_package)
    run([tools["signtool"], "sign", "/fd", "SHA256", "/f", pfx, "/p", CERT_PASSWORD, test_package])
    print(f"""     {test_package.relative_to(ROOT)}
To install it on this PC (once per certificate):
  1. Double-click {cer.relative_to(ROOT)} > Install Certificate > Local Machine >
     "Place all certificates in the following store" > Browse > Trusted People > Finish.
  2. Double-click {test_package.name} > Install.
Remove it later from Settings > Apps, and delete the certificate with certlm.msc.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())

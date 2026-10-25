"""Phase 13.3: the MSIX manifest and finding Docly's files inside a package."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from docly import __version__
from docly.ui import desktop

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import make_msix  # noqa: E402

NS = {
    "m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
}


@pytest.fixture(scope="module")
def manifest() -> ET.Element:
    return ET.fromstring(make_msix.render_manifest(make_msix.load_identity()))


def test_identity_matches_partner_center(manifest: ET.Element) -> None:
    """These three must match Partner Center exactly, or the upload is refused."""
    identity = manifest.find("m:Identity", NS)
    assert identity is not None
    assert identity.get("Name") == "QusaiKagalwala.Docly"
    assert identity.get("Publisher") == "CN=775C1D17-053C-4160-976D-B6782AF2C690"
    assert manifest.findtext("m:Properties/m:PublisherDisplayName", namespaces=NS) == "Qusai Kagalwala"
    assert identity.get("ProcessorArchitecture") == "x64"


def test_version_follows_the_app(manifest: ET.Element) -> None:
    version = manifest.find("m:Identity", NS).get("Version")
    assert version == make_msix.msix_version(__version__)
    assert version.split(".")[3] == "0"  # the Store reserves the fourth number


@pytest.mark.parametrize(("version", "expected"), [("1.0.0", "1.0.0.0"), ("1.2.3.9", "1.2.3.0"), ("2.0", "2.0.0.0")])
def test_msix_version(version: str, expected: str) -> None:
    assert make_msix.msix_version(version) == expected


def test_runs_as_a_full_desktop_app(manifest: ET.Element) -> None:
    app = manifest.find("m:Applications/m:Application", NS)
    assert app.get("Executable") == "Docly\\Docly.exe"
    assert app.get("EntryPoint") == "Windows.FullTrustApplication"
    capabilities = [c.get("Name") for c in manifest.findall("m:Capabilities/rescap:Capability", NS)]
    assert capabilities == ["runFullTrust"]  # nothing else: no internet, camera, location…
    device = manifest.find("m:Dependencies/m:TargetDeviceFamily", NS)
    assert device.get("Name") == "Windows.Desktop" and device.get("MinVersion") == "10.0.17763.0"


def test_every_logo_exists(manifest: ET.Element) -> None:
    text = make_msix.render_manifest(make_msix.load_identity())
    assert len(make_msix.logos_in(text)) == 4
    assert make_msix.missing_logos(text) == []


def test_missing_identity_value_is_reported(tmp_path: Path) -> None:
    identity = make_msix.load_identity()
    del identity["publisher"]
    with pytest.raises(SystemExit, match="publisher"):
        make_msix.render_manifest(identity)


def test_text_is_escaped_for_xml() -> None:
    identity = {**make_msix.load_identity(), "description": 'Photos & PDFs <fast> "ready"'}
    root = ET.fromstring(make_msix.render_manifest(identity))
    assert root.findtext("m:Properties/m:Description", namespaces=NS) == 'Photos & PDFs <fast> "ready"'


def test_finds_newest_sdk_tool(tmp_path: Path) -> None:
    for version in ("10.0.19041.0", "10.0.26100.0", "10.0.22621.0"):
        tool = tmp_path / version / "x64" / "makeappx.exe"
        tool.parent.mkdir(parents=True)
        tool.write_bytes(b"")
    assert make_msix.find_sdk_tool("makeappx", tmp_path).parent.parent.name == "10.0.26100.0"
    assert make_msix.find_sdk_tool("signtool", tmp_path) is None


def test_refuses_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(make_msix.sys, "platform", "linux")
    assert make_msix.main([]) == 2


# ----- files inside the package ---------------------------------------------------
def test_explorer_path_unchanged_outside_a_package(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(desktop, "package_family_name", lambda: None)
    assert desktop.explorer_path(tmp_path / "Docly" / "logs") == tmp_path / "Docly" / "logs"


def test_explorer_path_inside_a_package(tmp_path: Path, monkeypatch) -> None:
    family = "QusaiKagalwala.Docly_8wekyb3d8bbwe"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(desktop, "package_family_name", lambda: family)
    logs = tmp_path / "Docly" / "logs"
    real = tmp_path / "Packages" / family / "LocalCache" / "Local" / "Docly" / "logs"
    assert desktop.explorer_path(logs) == logs  # nothing redirected yet: keep the normal path
    real.mkdir(parents=True)
    assert desktop.explorer_path(logs) == real
    assert desktop.explorer_path(Path("/elsewhere/file.txt")) == Path("/elsewhere/file.txt")


def test_tests_never_run_packaged() -> None:
    """Off Windows there is no package; on Windows, tests run from source."""
    assert desktop.package_family_name() is None

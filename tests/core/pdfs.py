"""Test-PDF factory. Each page carries a label we can read back to check order."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name


def make_pdf(
    labels: list[str],
    size: tuple[float, float] = (595, 842),
    rotate: int = 0,
    password: str | None = None,
    owner_only: bool = False,
    extras: bool = False,
) -> bytes:
    """A PDF whose page *n* shows ``labels[n]``.

    ``password`` sets an open password; ``owner_only`` instead adds only
    "no editing" restrictions. ``extras`` adds document JavaScript, an
    auto-run action, metadata, a page action and an attachment annotation.
    """
    pdf = pikepdf.Pdf.new()
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica))
    for label in labels:
        content = pdf.make_stream(f"BT /F1 24 Tf 72 700 Td (LABEL:{label}) Tj ET".encode())
        page = Dictionary(
            Type=Name.Page,
            MediaBox=Array([0, 0, size[0], size[1]]),
            Contents=content,
            Resources=Dictionary(Font=Dictionary(F1=font)),
        )
        if rotate:
            page.Rotate = rotate
        pdf.pages.append(pikepdf.Page(page))

    if extras:
        script = Dictionary(S=Name.JavaScript, JS=pikepdf.String("app.alert('hi')"))
        pdf.Root.OpenAction = script
        pdf.Root.Names = Dictionary(JavaScript=Dictionary(Names=Array([pikepdf.String("x"), script])))
        pdf.docinfo["/Author"] = "Secret Person"
        first = pdf.pages[0].obj
        first.AA = Dictionary(O=script)
        attachment = Dictionary(Type=Name.Annot, Subtype=Name.FileAttachment, Rect=Array([0, 0, 10, 10]))
        launch = Dictionary(
            Type=Name.Annot, Subtype=Name.Link, Rect=Array([20, 20, 60, 60]),
            A=Dictionary(S=Name.Launch, F=pikepdf.String("calc.exe")),
        )  # fmt: skip
        web = Dictionary(
            Type=Name.Annot, Subtype=Name.Link, Rect=Array([70, 20, 110, 60]),
            A=Dictionary(S=Name.URI, URI=pikepdf.String("https://example.org")),
        )  # fmt: skip
        first.Annots = Array([attachment, launch, web])

    buffer = io.BytesIO()
    if password or owner_only:
        encryption = pikepdf.Encryption(
            owner="owner-secret",
            user=password or "",
            R=6,
            allow=pikepdf.Permissions(modify_other=False, extract=False),
        )
        pdf.save(buffer, encryption=encryption)
    else:
        pdf.save(buffer)
    return buffer.getvalue()


def write_pdf(path: Path, labels: list[str], **kwargs) -> Path:
    path.write_bytes(make_pdf(labels, **kwargs))
    return path


def labels_of(data: bytes) -> list[str]:
    """Labels of each page, in order (pages without a label give '')."""
    with pikepdf.open(io.BytesIO(data)) as pdf:
        result = []
        for page in pdf.pages:
            contents = page.obj.get(Name.Contents)
            raw = b""
            if isinstance(contents, pikepdf.Array):
                raw = b"".join(c.read_bytes() for c in contents)
            elif contents is not None:
                raw = contents.read_bytes()
            match = re.search(rb"LABEL:([^)]*)\)", raw)
            result.append(match.group(1).decode() if match else "")
        return result


def rotations_of(data: bytes) -> list[int]:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return [int(page.obj.get(Name.Rotate, 0)) % 360 for page in pdf.pages]

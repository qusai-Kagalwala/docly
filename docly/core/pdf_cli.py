"""Command-line demo of the PDF engine, for trying it before the UI exists.

    python -m docly.core.pdf_cli info     form.pdf
    python -m docly.core.pdf_cli merge    a.pdf "page 2.jpg" b.pdf
    python -m docly.core.pdf_cli extract  form.pdf --pages "1, 3-4"
    python -m docly.core.pdf_cli delete   form.pdf --pages 2
    python -m docly.core.pdf_cli rotate   scan.pdf --pages "2,4" --angle 90
    python -m docly.core.pdf_cli split    form.pdf --ranges "1-2, 3-"
    python -m docly.core.pdf_cli split    form.pdf --every 1
    python -m docly.core.pdf_cli compress scan.pdf --kb 500 [--min-kb 50] [--grayscale]
    python -m docly.core.pdf_cli fill     form.pdf --text 1 72 700 "Qusai K" --date 1 400 700 \
                                          --tick 1 60 300 --sign sign.png 1 380 740 150 --blue

Fill positions are in points (72 per inch) from the page's top-left corner as
you see it; A4 is 595 × 842. Page numbers start at 1.

Results go into ``Docly_Output`` next to the first input (or ``--out``);
nothing is ever overwritten. Password-protected PDFs prompt for the password.
"""

from __future__ import annotations

import argparse
import getpass
import math
import sys
from pathlib import Path

from docly.core.errors import DoclyError, InvalidPageRangeError, PasswordRequiredError, WrongPasswordError
from docly.core.files import write_new_file
from docly.core.image_pdf import PageSize
from docly.core.files import read_bytes
from docly.core.image_io import MAX_FILE_BYTES
from docly.core.pdf_compress import apply_to_result
from docly.core.pdf_fill import (
    BLACK,
    BLUE_INK,
    DATE_FORMATS,
    FillItem,
    ItemKind,
    cover_item,
    date_item,
    fill_pdf,
    image_item,
    mark_item,
    text_item,
)
from docly.core.pdf_ops import (
    PdfResult,
    Source,
    all_pages,
    build_pdf,
    close_all,
    delete_pages,
    extract,
    load_source,
    merge,
    rotate,
    split_by_ranges,
    split_every,
    suggest_name,
)

OUTPUT_FOLDER = "Docly_Output"
MAX_PASSWORD_TRIES = 3


def open_with_prompt(path: Path, password: str | None, ask=getpass.getpass) -> Source:
    """Open ``path``, asking for the password in the terminal if needed."""
    tries = 0
    while True:
        try:
            return load_source(path, password)
        except (PasswordRequiredError, WrongPasswordError) as exc:
            tries += 1
            if tries > MAX_PASSWORD_TRIES:
                raise
            if isinstance(exc, WrongPasswordError):
                print(exc)
            password = ask(f"Password for {path.name}: ")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docly.core.pdf_cli", description="Docly PDF tools (demo).")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, many: bool = False) -> argparse.ArgumentParser:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("files" if many else "file", type=Path, nargs="+" if many else None)
        cmd.add_argument("--password", help="password for protected PDFs (otherwise you'll be asked)")
        cmd.add_argument("--out", type=Path, help=f"output folder (default: {OUTPUT_FOLDER} next to the input)")
        return cmd

    add("info", "show pages, sizes and protection")
    merge_cmd = add("merge", "combine PDFs and images into one PDF", many=True)
    merge_cmd.add_argument("--page-size", choices=[s.value for s in PageSize], default=PageSize.A4.value)
    add("extract", "keep only some pages").add_argument("--pages", required=True)
    add("delete", "remove some pages").add_argument("--pages", required=True)
    rotate_cmd = add("rotate", "turn some pages")
    rotate_cmd.add_argument("--pages", required=True)
    rotate_cmd.add_argument("--angle", type=int, choices=(90, 180, 270), required=True)
    split_cmd = add("split", "split into several PDFs")
    group = split_cmd.add_mutually_exclusive_group(required=True)
    group.add_argument("--ranges", help='one file per range, e.g. "1-2, 3-"')
    group.add_argument("--every", type=int, help="one file per N pages")
    compress_cmd = add("compress", "shrink to a size limit")
    compress_cmd.add_argument("--kb", type=float, help="largest allowed size in KB (1 KB = 1000 bytes, the safe reading)")
    compress_cmd.add_argument("--min-kb", type=float, help="smallest allowed size in KB, if the portal has one")
    compress_cmd.add_argument("--grayscale", action="store_true", help="turn pictures grey")
    fill_cmd = add("fill", "add text, dates, ticks, a signature or cover-up boxes")
    fill_cmd.add_argument("--text", nargs=4, action="append", default=[], metavar=("PAGE", "X", "Y", "TEXT"))
    fill_cmd.add_argument("--date", nargs=3, action="append", default=[], metavar=("PAGE", "X", "Y"))
    fill_cmd.add_argument("--date-format", default="DD/MM/YYYY", choices=list(DATE_FORMATS))
    fill_cmd.add_argument("--tick", nargs=3, action="append", default=[], metavar=("PAGE", "X", "Y"))
    fill_cmd.add_argument("--cross", nargs=3, action="append", default=[], metavar=("PAGE", "X", "Y"))
    fill_cmd.add_argument("--sign", nargs=5, action="append", default=[], metavar=("IMAGE", "PAGE", "X", "Y", "WIDTH"))
    fill_cmd.add_argument("--cover", nargs=5, action="append", default=[], metavar=("PAGE", "X", "Y", "W", "H"))
    fill_cmd.add_argument("--size", type=float, default=12.0, help="text size in points (default 12)")
    fill_cmd.add_argument("--blue", action="store_true", help="blue ink instead of black")
    return parser


def main(argv: list[str] | None = None, ask=getpass.getpass) -> int:
    """Run a command. Exit codes: 0 done, 2 error."""
    args = _parser().parse_args(argv)
    paths: list[Path] = args.files if args.command == "merge" else [args.file]
    sources: list[Source] = []
    try:
        for path in paths:
            sources.append(open_with_prompt(path, args.password, ask))
        if args.command == "info":
            _print_info(sources[0])
            return 0
        results = _run(args, sources)
        folder = args.out or paths[0].resolve().parent / OUTPUT_FOLDER
        for result in results:
            saved = write_new_file(folder, result.suggested_name, result.data)
            pages = "page" if result.page_count == 1 else "pages"
            print(f"Saved: {saved}  ({result.page_count} {pages}, {result.size_bytes / 1024:.1f} KB)")
        for warning in dict.fromkeys(w for r in results for w in r.warnings):
            print(f"Note: {warning}")
        return 0
    except DoclyError as exc:
        print(f"Error: {exc}")
        return 2
    finally:
        close_all(sources)


def _run(args: argparse.Namespace, sources: list[Source]) -> list[PdfResult]:
    source = sources[0]
    if args.command == "merge":
        return [merge(sources, PageSize(args.page_size))]
    if args.command == "extract":
        return [extract(source, args.pages)]
    if args.command == "delete":
        return [delete_pages(source, args.pages)]
    if args.command == "rotate":
        return [rotate(source, args.pages, args.angle)]
    if args.command == "compress":
        if args.kb is None and not args.grayscale:
            raise InvalidPageRangeError("Give a size limit with --kb (and/or use --grayscale).")
        built = build_pdf([source], all_pages([source]), suggest_name([source], all_pages([source])))
        target = math.floor(args.kb * 1000) if args.kb else None
        minimum = math.ceil(args.min_kb * 1024) if args.min_kb else None
        result = apply_to_result(built, target, minimum, args.grayscale)
        if result.met_target is False:
            print(f"Couldn't reach {args.kb:g} KB; this is the smallest readable version.")
        return [result]
    if args.command == "fill":
        return [fill_pdf(source, _fill_items(args))]
    if args.ranges:
        return split_by_ranges(source, args.ranges)
    return split_every(source, args.every)


def _fill_items(args: argparse.Namespace) -> list[FillItem]:
    def num(value: str) -> float:
        try:
            return float(value)
        except ValueError:
            raise InvalidPageRangeError(f"{value!r} isn't a number.") from None

    def page(value: str) -> int:
        return int(num(value)) - 1  # people count pages from 1

    colour = BLUE_INK if args.blue else BLACK
    items: list[FillItem] = []
    for p, x, y, text in args.text:
        items.append(text_item(page(p), num(x), num(y), text.replace("\\n", "\n"), args.size, colour))
    for p, x, y in args.date:
        items.append(date_item(page(p), num(x), num(y), style=args.date_format, font_size=args.size, colour=colour))
    for kind, entries in ((ItemKind.TICK, args.tick), (ItemKind.CROSS, args.cross)):
        for p, x, y in entries:
            items.append(mark_item(kind, page(p), num(x), num(y), args.size * 1.2, colour))
    for image, p, x, y, width in args.sign:
        data = read_bytes(Path(image), MAX_FILE_BYTES)
        items.append(image_item(page(p), num(x), num(y), data, num(width)))
    for p, x, y, w, h in args.cover:
        items.append(cover_item(page(p), num(x), num(y), num(w), num(h)))
    return items


def _print_info(source: Source) -> None:
    print(source.name)
    if source.pdf is None:
        print("  Image (becomes 1 page)")
        return
    pdf = source.pdf
    print(f"  Pages: {pdf.page_count}")
    print(f"  Size: {pdf.size_bytes / 1024:.1f} KB")
    print(f"  Protected: {'yes (output will not be)' if pdf.encrypted else 'no'}")
    for index in range(min(pdf.page_count, 10)):
        w, h = pdf.page_size(index)
        print(f"  Page {index + 1}: {w / 72 * 25.4:.0f} × {h / 72 * 25.4:.0f} mm")
    if pdf.page_count > 10:
        print(f"  … and {pdf.page_count - 10} more")
    for warning in pdf.warnings:
        print(f"  Note: {warning}")


if __name__ == "__main__":
    sys.exit(main())

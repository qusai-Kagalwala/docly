"""Fill & Sign page: type on a form, tick boxes, add the date and a signature.

Flow:
    open a PDF (or a photo of a form, which becomes a PDF page)
    pick a tool → click the page → the item appears; drag, resize, edit
    Create signed PDF → result card → Save (Docly_Output, never overwriting)

Everything is drawn into a new copy; the original file is never changed.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QKeySequence, QPainter, QShortcut, QUndoStack
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docly.core.errors import CorruptPdfError, DoclyError, PasswordRequiredError, WrongPasswordError
from docly.core.files import read_bytes
from docly.core.image_io import MAX_FILE_BYTES, load_image_bytes
from docly.core.pdf_compress import apply_to_result
from docly.core.pdf_fill import ItemKind, displayed_size, fill_pdf
from docly.core.pdf_io import open_pdf_bytes
from docly.core.pdf_ops import PageRef, PdfResult, Source, build_pdf, load_source
from docly.core.signature import CleanOptions, clean_signature
from docly.logger import get_logger
from docly.presets import PresetLoadResult, default_presets
from docly.ui.icons import make_icon
from docly.ui.pages.base_page import BasePage, SideColumn
from docly.ui.pdf.compress_card import CompressCard
from docly.ui.pdf.password_dialog import ask_password
from docly.ui.pdfium import PDFIUM_LOCK
from docly.ui.sign.item_panel import ItemPanel
from docly.ui.sign.items import CoverItem, ImageItem, MarkItem, SignItem, TextItem
from docly.ui.sign.page_view import AddRemoveCommand, PageScene, PageView, SnapshotCommand
from docly.ui.sign.text_editing import InlineTextEditor
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.card import Card
from docly.ui.widgets.drop_zone import DropZone, ask_open_files, paths_from_mime
from docly.ui.widgets.pdf_result_card import PdfResultCard
from docly.ui.widgets.status_badge import Banner
from docly.ui.workers import CancelToken, TaskRunner

log = get_logger(__name__)

SIDE_WIDTH = 320
RENDER_SCALE = 2.0  # page pictures are drawn at 144 dpi so they stay sharp when zoomed
MAX_RENDER_SIDE = 2400
MAX_SIGNATURE_SIDE = 1600
FILE_FILTER = "PDFs and photos (*.pdf *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff);;All files (*)"
SIGN_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)"
ACCEPTED = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif")

TOOLS: tuple[tuple[str, str, str], ...] = (
    ("select", "mouse-pointer-2", "Select and move (Esc)"),
    ("text", "type", "Text: click where it should go"),
    ("date", "calendar", "Today's date"),
    ("tick", "check", "Tick"),
    ("cross", "x", "Cross"),
    ("signature", "signature", "Your signature"),
    ("cover", "square", "Cover-up box (hides, doesn't delete)"),
)


class _NeedsPassword:
    def __init__(self, path: Path, wrong: bool) -> None:
        self.path, self.wrong = path, wrong


class _Progress(QObject):
    changed = Signal(int, int)


def prepare_signature(data: bytes) -> bytes:
    """A PNG with see-through paper. Photos of ink on paper are cleaned first."""
    picture = load_image_bytes(data, "signature", keep_alpha=True).image
    if picture.mode != "RGBA":
        picture = clean_signature(picture, CleanOptions(transparent=True)).image
    if max(picture.size) > MAX_SIGNATURE_SIDE:
        picture = picture.copy()
        picture.thumbnail((MAX_SIGNATURE_SIDE, MAX_SIGNATURE_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    picture.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def render_page(data: bytes, password: str | None, page: int) -> QImage:
    """One page as a picture (runs on a worker thread, under the PDFium lock)."""
    with PDFIUM_LOCK:
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        document = QPdfDocument()
        if password:
            document.setPassword(password)
        document.load(buffer)
        try:
            if document.status() != QPdfDocument.Status.Ready:
                raise CorruptPdfError("This page couldn't be drawn.")
            size = document.pagePointSize(page)
            scale = min(RENDER_SCALE, MAX_RENDER_SIDE / max(size.width(), size.height(), 1))
            image = document.render(page, QSize(round(size.width() * scale), round(size.height() * scale)))
        finally:
            document.close()
            buffer.close()
    backed = QImage(image.size(), QImage.Format.Format_RGB32)
    backed.fill(Qt.GlobalColor.white)
    painter = QPainter(backed)
    painter.drawImage(0, 0, image)
    painter.end()
    return backed


class SignPage(BasePage):
    PAGE_ID = "sign"
    TITLE = "Fill & Sign"
    SUBTITLE = "Type on forms, tick boxes, add the date and your signature."
    ICON = "signature"
    SCROLLS = False

    def __init__(
        self,
        theme: ThemeManager,
        presets: PresetLoadResult | None = None,
        region: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent)
        self.setAcceptDrops(True)
        presets = presets if presets is not None else default_presets()
        self.source: Source | None = None
        self.page_sizes: list[tuple[float, float]] = []
        self.scenes: dict[int, PageScene] = {}
        self.current = 0
        self.tool = "select"
        self.signature_png: bytes | None = None
        self.last_signature: bytes | None = None
        self.undo = QUndoStack(self)
        self._progress = _Progress(self)

        self.loader = TaskRunner(parent=self)
        self.renderer = TaskRunner(parent=self)
        self.signer = TaskRunner(parent=self)
        self.processor = TaskRunner(parent=self)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        self.content.addLayout(columns, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        columns.addLayout(left, 1)
        self.banner = Banner(theme)
        left.addWidget(self.banner)

        self.stack = QStackedWidget()
        self.drop_zone = DropZone(
            theme,
            title="Drop a form here",
            hint="or click to browse · a PDF, or a photo of a paper form",
            privacy="Your files stay on this computer. The original is never changed.",
            icon="signature",
            multiple=True,
            file_filter=FILE_FILTER,
            picker_title="Choose a form",
        )
        self.view = PageView()
        self.inline_editor: InlineTextEditor | None = None
        self.workspace = self._build_workspace(theme)
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self.workspace)
        left.addWidget(self.stack, 1)

        self.status = QLabel()
        self.status.setProperty("role", "caption")
        left.addWidget(self.status)

        self.side_scroll = SideColumn(SIDE_WIDTH + 14)
        self.side = self.side_scroll.column
        columns.addWidget(self.side_scroll)

        file_card = Card(theme)
        heading = QLabel("Document")
        heading.setProperty("role", "section")
        file_card.body.addWidget(heading)
        self.file_label = QLabel("No form open yet.")
        self.file_label.setProperty("role", "muted")
        self.file_label.setWordWrap(True)
        file_card.body.addWidget(self.file_label)
        self.open_button = QPushButton("Open a form…")
        file_card.body.addWidget(self.open_button)
        self.side.addWidget(file_card)

        self.panel = ItemPanel(theme)
        self.side.addWidget(self.panel)
        self.compress_card = CompressCard(theme, presets.presets, region)
        self.side.addWidget(self.compress_card)
        self.result_card = PdfResultCard(theme)
        self.result_card.create_button.setText("Create signed PDF")
        self.result_card.create_button.setToolTip("Draw everything onto a new copy of the form")
        self.side.addWidget(self.result_card)
        self.side.addStretch(1)

        # ----- signals -----------------------------------------------------------
        self.drop_zone.filesChosen.connect(self._open_first)
        self.open_button.clicked.connect(self.browse)
        self.view.pageClicked.connect(self._on_page_clicked)
        self.view.textEditRequested.connect(self.edit_text_inline)
        self.view.zoomChanged.connect(lambda _z: self.inline_editor is not None and self.inline_editor.reposition())
        self.view.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))
        self.panel.changeRequested.connect(self.change_item)
        self.panel.deleteRequested.connect(self.delete_selected)
        self.loader.finished.connect(self._on_opened)
        self.loader.failed.connect(lambda m: self.show_banner(m, "danger"))
        self.renderer.finished.connect(self._on_rendered)
        self.renderer.failed.connect(lambda m: self.show_banner(m, "danger"))
        self.signer.finished.connect(self._on_signature_ready)
        self.signer.failed.connect(lambda m: self.show_banner(m, "danger"))
        self.processor.finished.connect(self._on_created)
        self.processor.failed.connect(self.result_card.show_error)
        self.result_card.createRequested.connect(self.create_pdf)
        self.result_card.cancelRequested.connect(self._cancel_create)
        self.compress_card.changed.connect(self._mark_stale)
        self.undo.indexChanged.connect(self._mark_stale)
        self._progress.changed.connect(self.result_card.set_progress)
        theme.themeChanged.connect(self._paint_icons)
        self._paint_icons(theme.tokens)
        self._update_controls()

    # ----- layout ----------------------------------------------------------------
    def _build_workspace(self, theme: ThemeManager) -> QWidget:
        card = Card(theme)
        card.body.setContentsMargins(10, 10, 10, 10)
        card.body.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons: dict[str, QToolButton] = {}
        for name, icon, tip in TOOLS:
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setProperty("icon_name", icon)
            self.tool_group.addButton(button)
            self.tool_buttons[name] = button
            toolbar.addWidget(button)
            if name == "select":
                toolbar.addSpacing(8)
        self.tool_buttons["select"].setChecked(True)
        self.tool_group.buttonClicked.connect(self._on_tool_clicked)
        self.signature_menu = QMenu(self)
        self.place_signature_action = self.signature_menu.addAction("Place my signature")
        self.choose_signature_action = self.signature_menu.addAction("Choose a signature image…")
        self.last_signature_action = self.signature_menu.addAction("Use my signature from the Signature page")
        self.place_signature_action.triggered.connect(lambda: self.set_tool("signature"))
        self.choose_signature_action.triggered.connect(self.choose_signature)
        self.last_signature_action.triggered.connect(self.use_last_signature)

        toolbar.addStretch(1)
        self.undo_action = self.undo.createUndoAction(self, "Undo")
        self.redo_action = self.undo.createRedoAction(self, "Redo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        for action, icon in ((self.undo_action, "undo-2"), (self.redo_action, "redo-2")):
            action.setData(icon)
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(action)
            button = QToolButton()
            button.setDefaultAction(action)
            button.setAutoRaise(True)
            toolbar.addWidget(button)
        card.body.addLayout(toolbar)
        card.body.addWidget(self.view, 1)

        nav = QHBoxLayout()
        self.prev_button = QToolButton()
        self.prev_button.setAutoRaise(True)
        self.prev_button.setToolTip("Previous page")
        self.page_label = QLabel()
        self.page_label.setProperty("role", "body")
        self.next_button = QToolButton()
        self.next_button.setAutoRaise(True)
        self.next_button.setToolTip("Next page")
        self.zoom_out_button = QToolButton()
        self.zoom_out_button.setAutoRaise(True)
        self.zoom_out_button.setToolTip("Zoom out (Ctrl + scroll)")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setProperty("role", "caption")
        self.zoom_in_button = QToolButton()
        self.zoom_in_button.setAutoRaise(True)
        self.zoom_in_button.setToolTip("Zoom in (Ctrl + scroll)")
        self.fit_button = QPushButton("Fit width")
        self.fit_button.setProperty("variant", "ghost")
        for widget in (self.prev_button, self.page_label, self.next_button):
            nav.addWidget(widget)
        nav.addStretch(1)
        for widget in (self.zoom_out_button, self.zoom_label, self.zoom_in_button, self.fit_button):
            nav.addWidget(widget)
        card.body.addLayout(nav)

        self.prev_button.clicked.connect(lambda: self.show_page(self.current - 1))
        self.next_button.clicked.connect(lambda: self.show_page(self.current + 1))
        self.zoom_in_button.clicked.connect(self.view.zoom_in)
        self.zoom_out_button.clicked.connect(self.view.zoom_out)
        self.fit_button.clicked.connect(self.view.fit_page_width)

        for key, slot in (
            (QKeySequence.StandardKey.Delete, self.delete_selected),
            (QKeySequence(Qt.Key.Key_Escape), lambda: self.set_tool("select")),
        ):
            shortcut = QShortcut(QKeySequence(key), card)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        for key, dx, dy in ((Qt.Key.Key_Left, -1, 0), (Qt.Key.Key_Right, 1, 0), (Qt.Key.Key_Up, 0, -1), (Qt.Key.Key_Down, 0, 1)):
            for modifier, step in ((Qt.KeyboardModifier.NoModifier, 1), (Qt.KeyboardModifier.ShiftModifier, 10)):
                shortcut = QShortcut(QKeySequence(modifier.value | key.value), self.view)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(lambda dx=dx * step, dy=dy * step: self.nudge(dx, dy))
        return card

    def _paint_icons(self, tokens: Tokens) -> None:
        SignItem.accent = QColor(tokens.accent)
        for scene in self.scenes.values():
            scene.update()
        dpr = self.devicePixelRatioF()
        for button in self.tool_buttons.values():
            button.setIcon(make_icon(button.property("icon_name"), tokens.text, 18, dpr))
        for action in (self.undo_action, self.redo_action):
            action.setIcon(make_icon(action.data(), tokens.text, 18, dpr))
        for button, icon in (
            (self.prev_button, "chevron-left"), (self.next_button, "chevron-right"),
            (self.zoom_in_button, "zoom-in"), (self.zoom_out_button, "zoom-out"),
        ):  # fmt: skip
            button.setIcon(make_icon(icon, tokens.text, 18, dpr))

    # ----- opening ------------------------------------------------------------------
    def browse(self) -> None:
        paths = ask_open_files(self, "Choose a form", FILE_FILTER)
        if paths:
            self._open_first(paths)

    def ask_password(self, file_name: str, wrong: bool) -> str | None:
        """Ask for a PDF password (tests replace this)."""
        return ask_password(self, file_name, wrong)

    def _open_first(self, paths: list[Path]) -> None:
        usable = [Path(p) for p in paths if Path(p).suffix.lower() in ACCEPTED]
        if not usable:
            self.show_banner("Choose a PDF or a photo of a form.", "warning")
            return
        if len(usable) > 1:
            self.show_banner(f"Fill & Sign works on one document at a time; opened {usable[0].name}.", "info")
        else:
            self.hide_banner()
        self.open_file(usable[0])

    def open_file(self, path: Path, password: str | None = None) -> None:
        self.status.setText(f"Opening {path.name}…")

        def job(_token: CancelToken):
            try:
                source = load_source(path, password)
            except PasswordRequiredError:
                return _NeedsPassword(path, wrong=False)
            except WrongPasswordError:
                return _NeedsPassword(path, wrong=True)
            if not source.is_pdf:  # a photo of a form: make it a PDF page first
                built = build_pdf([source], [PageRef(0, 0)], f"{path.stem}.pdf")
                source = Source(path, path.name, pdf=open_pdf_bytes(built.data, path.name), data=built.data)
            sizes = [displayed_size(page) for page in source.pdf.pdf.pages]  # type: ignore[union-attr]
            return path, source, sizes

        self.loader.submit(job)

    def _on_opened(self, payload) -> None:  # noqa: ANN001
        if isinstance(payload, _NeedsPassword):
            password = self.ask_password(payload.path.name, payload.wrong)
            if password:
                self.open_file(payload.path, password)
            else:
                self.status.setText("")
                self.show_banner(f"{payload.path.name} wasn't opened (no password).", "info")
            return
        path, source, sizes = payload
        self.renderer.cancel()
        self.processor.cancel()
        self.close_inline_editor()
        for scene in self.scenes.values():
            scene.deleteLater()
        self.scenes.clear()
        self.undo.clear()
        self.source, self.page_sizes = source, list(sizes)
        self.current = 0
        pages = f"{len(sizes)} page" + ("" if len(sizes) == 1 else "s")
        self.file_label.setText(f"{source.name}\n{pages}")
        if source.warnings:
            self.show_banner(" ".join(source.warnings), "warning")
        self.stack.setCurrentWidget(self.workspace)
        self.show_page(0)
        self.view.fit_page_width()
        self.view.scroll_to_top()
        self._mark_stale()
        log.info("Fill & Sign opened %s (%s)", path.name, pages)

    # ----- pages ------------------------------------------------------------------------
    def scene_for(self, index: int) -> PageScene:
        scene = self.scenes.get(index)
        if scene is None:
            w, h = self.page_sizes[index]
            scene = PageScene(index, w, h)
            scene.selectionChanged.connect(lambda s=scene: self._on_selection(s))
            scene.moveFinished.connect(self._on_move_finished)
            self.scenes[index] = scene
        return scene

    def show_page(self, index: int) -> None:
        if self.source is None or not 0 <= index < len(self.page_sizes):
            return
        if index != self.current:
            self.close_inline_editor()
        self.current = index
        scene = self.scene_for(index)
        if self.view.scene() is not scene:
            self.view.setScene(scene)
            if self.view.fit_width:
                self.view.fit_page_width()
            self.view.scroll_to_top()
        if not scene.rendered:
            source = self.source
            self.renderer.submit(lambda _t: (index, render_page(source.data, source.password, index)))
        self._on_selection(scene)
        self._update_controls()

    def _on_rendered(self, payload: tuple[int, QImage]) -> None:
        index, image = payload
        scene = self.scenes.get(index)
        if scene is not None and not image.isNull():
            scene.set_picture(image)

    def current_scene(self) -> PageScene | None:
        return self.scenes.get(self.current)

    def _show_item(self, item: SignItem) -> None:
        scene = item.scene()
        if isinstance(scene, PageScene) and scene.index != self.current:
            self.show_page(scene.index)

    # ----- tools & placing -----------------------------------------------------------------
    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.tool_buttons[tool].setChecked(True)
        self.view.placing = tool != "select"
        self.view.setCursor(Qt.CursorShape.CrossCursor if self.view.placing else Qt.CursorShape.ArrowCursor)
        hints = {
            "select": "Click an item to change it; drag to move; drag its corner to resize.",
            "text": "Click where the text should start.",
            "date": "Click where the date should go.",
            "tick": "Click the box to tick.",
            "cross": "Click the box to cross.",
            "signature": "Click where your signature should go.",
            "cover": "Click the top-left of the area to hide.",
        }
        self.status.setText(hints[tool])

    def _on_tool_clicked(self, button: QToolButton) -> None:
        name = next(k for k, b in self.tool_buttons.items() if b is button)
        if name == "signature":
            self.tool_buttons[self.tool].setChecked(True)  # until a signature is ready
            self.place_signature_action.setEnabled(self.signature_png is not None)
            self.last_signature_action.setEnabled(self.last_signature is not None)
            self.signature_menu.popup(button.mapToGlobal(button.rect().bottomLeft()))
            return
        self.set_tool(name)

    def make_item(self, tool: str) -> SignItem:
        if tool == "text":
            return TextItem("Your text")
        if tool == "date":
            return TextItem(date_style="DD/MM/YYYY")
        if tool in ("tick", "cross"):
            return MarkItem(ItemKind.TICK if tool == "tick" else ItemKind.CROSS)
        if tool == "signature":
            if self.signature_png is None:
                raise RuntimeError("No signature chosen")
            return ImageItem(self.signature_png)
        return CoverItem()

    def place(self, tool: str, point: QPointF) -> SignItem | None:
        """Put a new item with its top-left corner at ``point`` (page points)."""
        scene = self.current_scene()
        if scene is None:
            return None
        item = self.make_item(tool)
        if tool in ("tick", "cross"):  # centre marks on the click: you click the box
            point = point - QPointF(item.size[0] / 2, item.size[1] / 2)
        scene.add_sign_item(item)
        item.setPos(item._clamped(point))
        scene.removeItem(item)
        self.undo.push(AddRemoveCommand(f"Add {tool}", scene, [item], True, self._show_item))
        scene.clearSelection()
        item.setSelected(True)
        self.set_tool("select")
        if isinstance(item, TextItem) and not item.is_date:
            self.edit_text_inline(item)
        return item

    def edit_text_inline(self, item: TextItem) -> InlineTextEditor:
        """Type straight onto the page (double-click a text item, or place one)."""
        self.close_inline_editor()
        scene = item.scene()
        if isinstance(scene, PageScene) and scene.index != self.current:
            self.show_page(scene.index)
        scene = item.scene()
        if scene is not None:
            scene.clearSelection()
        item.setSelected(True)
        editor = InlineTextEditor(self.view, item, QColor(self.theme.tokens.danger))
        editor.textEdited.connect(lambda text, it=item: self.change_item(it, "text", text))
        editor.finished.connect(lambda _ok, ed=editor: self._on_inline_closed(ed))
        self.inline_editor = editor
        return editor

    def close_inline_editor(self) -> None:
        if self.inline_editor is not None:
            self.inline_editor.close_editor(accept=True)

    def _on_inline_closed(self, editor: InlineTextEditor) -> None:
        if self.inline_editor is editor:
            self.inline_editor = None
            self.view.setFocus()

    def _on_page_clicked(self, point: QPointF) -> None:
        if self.tool != "select":
            self.place(self.tool, point)

    def all_items(self) -> list[tuple[int, SignItem]]:
        return [(index, item) for index, scene in sorted(self.scenes.items()) for item in scene.sign_items()]

    def selected_items(self) -> list[SignItem]:
        scene = self.current_scene()
        return [item for item in scene.sign_items() if item.isSelected()] if scene else []

    # ----- editing ------------------------------------------------------------------------
    def change_item(self, item: SignItem, name: str, value: object) -> None:
        before = {item: item.state()}
        if isinstance(item, TextItem):
            if name == "text":
                item.set_text(str(value))
            elif name == "font_size":
                item.set_font_size(float(value))  # type: ignore[arg-type]
            elif name == "colour":
                item.set_colour(value)  # type: ignore[arg-type]
            elif name == "date_style":
                item.set_date_style(str(value))
        elif isinstance(item, MarkItem):
            if name == "size":
                item.set_size(float(value), float(value))  # type: ignore[arg-type]
            elif name == "colour":
                item.set_colour(value)  # type: ignore[arg-type]
        elif isinstance(item, ImageItem) and name == "width":
            w, h = item.size
            item.set_size(float(value), float(value) * h / w)  # type: ignore[arg-type]
        after = {item: item.state()}
        if after != before:
            self.undo.push(SnapshotCommand(f"Change {name}", before, after, self._show_item, merge_key=(id(item), name)))

    def delete_selected(self) -> None:
        scene, items = self.current_scene(), self.selected_items()
        if scene is not None and items:
            self.undo.push(AddRemoveCommand("Delete", scene, items, False, self._show_item))
            self.panel.show_item(None)

    def nudge(self, dx: float, dy: float) -> None:
        items = self.selected_items()
        if not items:
            return
        before = {item: item.state() for item in items}
        for item in items:
            item.setPos(item.pos() + QPointF(dx, dy))
        after = {item: item.state() for item in items}
        self.undo.push(SnapshotCommand("Move", before, after, self._show_item, merge_key="nudge"))

    def _on_move_finished(self, before: dict, after: dict) -> None:
        self.undo.push(SnapshotCommand("Move", before, after, self._show_item))

    def _on_selection(self, scene: PageScene) -> None:
        if scene is not self.current_scene():
            return
        try:
            selected = [item for item in scene.sign_items() if item.isSelected()]
        except RuntimeError:  # scene being deleted
            return
        self.panel.show_item(selected[0] if len(selected) == 1 else None)

    # ----- signatures -------------------------------------------------------------------------
    def set_last_signature(self, data: bytes) -> None:
        """The newest result from the Signature page (offered in the menu)."""
        self.last_signature = data

    def choose_signature(self) -> None:
        paths = ask_open_files(self, "Choose your signature image", SIGN_FILTER)
        if not paths:
            return
        try:
            data = read_bytes(paths[0], MAX_FILE_BYTES)
        except DoclyError as exc:
            self.show_banner(str(exc), "danger")
            return
        self.load_signature(data)

    def use_last_signature(self) -> None:
        if self.last_signature is not None:
            self.load_signature(self.last_signature)

    def load_signature(self, data: bytes) -> None:
        """Make ``data`` see-through (in the background), then switch to the signature tool."""
        self.status.setText("Preparing your signature…")
        self.signer.submit(lambda _t: prepare_signature(data))

    def _on_signature_ready(self, png: bytes) -> None:
        self.signature_png = png
        self.set_tool("signature")

    # ----- creating -------------------------------------------------------------------------------
    def create_pdf(self) -> None:
        if self.source is None:
            return
        self.close_inline_editor()
        items = [item.to_fill(index) for index, item in self.all_items()]
        if not items:
            self.result_card.show_error("Add something to the page first: pick a tool and click the page.")
            return
        source, shrink, progress = self.source, self.compress_card.settings(), self._progress

        def job(token: CancelToken) -> PdfResult:
            result = fill_pdf(source, items, cancel=token)
            if shrink.active:
                result = apply_to_result(
                    result, shrink.target_bytes, shrink.min_bytes, shrink.grayscale, token,
                    lambda d, t: progress.changed.emit(d, t),
                )  # fmt: skip
            return result

        self.result_card.show_busy("Drawing onto a new copy of the form…")
        self.side_scroll.ensureWidgetVisible(self.result_card, 0, 0)
        self.processor.submit(job)

    def _on_created(self, result: PdfResult) -> None:
        if self.source is not None:
            self.result_card.show_results([result], self.source.path or Path(self.source.name))
            self.side_scroll.ensureWidgetVisible(self.result_card, 0, 0)

    def _cancel_create(self) -> None:
        self.processor.cancel()
        self._mark_stale()

    def _mark_stale(self, *_args: object) -> None:
        try:
            self._show_idle()
        except RuntimeError:  # the window is closing and its widgets are already gone
            pass

    def _show_idle(self) -> None:
        if self.processor.busy:
            return
        if self.source is None:
            self.result_card.show_idle("Open a form to begin.", can_create=False)
            return
        count = len(self.all_items())
        message = "Nothing added yet." if count == 0 else f"{count} item{'s' if count != 1 else ''} on the form."
        self.result_card.show_idle(message, can_create=count > 0)

    # ----- page-level drop ----------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = paths_from_mime(event.mimeData())
        event.acceptProposedAction()
        if paths:
            self._open_first(paths)

    def show_banner(self, text: str, kind: str = "danger") -> None:
        self.banner.show_message(text, kind)

    def hide_banner(self) -> None:
        self.banner.hide()

    def _update_controls(self) -> None:
        has = self.source is not None
        if not has:
            self.stack.setCurrentWidget(self.drop_zone)
        total = len(self.page_sizes)
        self.page_label.setText(f"Page {self.current + 1} of {total}" if has else "")
        self.prev_button.setEnabled(has and self.current > 0)
        self.next_button.setEnabled(has and self.current < total - 1)
        self.open_button.setText("Open another form…" if has else "Open a form…")

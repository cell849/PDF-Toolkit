"""Tool library and focused workspaces; conversion behavior lives in MainWindow."""

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from local_pdf_toolkit.ui.design import apply_theme

CATEGORIES = (
    "All tools",
    "Convert PDFs",
    "Images",
    "Organize",
    "Optimize",
    "Office",
    "Privacy",
    "Security",
)


def category(spec):
    operation = spec.operation_id
    if operation in ("file.rename_copies", "document.details"):
        return "Organize"
    if operation.startswith("metadata."):
        return "Privacy"
    if operation == "pdf.compress":
        return "Optimize"
    if operation in ("pdf.protect", "pdf.unlock", "pdf.remove_metadata", "pdf.redact"):
        return "Security"
    if operation.startswith("image."):
        return "Images"
    if operation.startswith("office.") or operation in (
        "pdf.to_docx",
        "pdf.to_xlsx",
        "pdf.to_pptx",
    ):
        return "Office"
    if operation.startswith("pdf.to_"):
        return "Convert PDFs"
    return "Organize"


def label(text, role=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(True)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    if primary:
        widget.setObjectName("primary")
    return widget


def panel():
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)
    return frame, layout


def tool_description(spec):
    descriptions = {
        "image.compare_formats": "Compare JPEG, PNG and WebP sizes and appearance",
        "pdf.organize_visual": "Arrange, rotate, remove and insert pages visually",
        "pdf.compare": "Highlight visual differences between two PDFs",
        "pdf.normalize_pages": "Fit selected pages to DIN or custom paper sizes",
        "file.rename_copies": "Preview numbered names and save separate copies",
        "document.details": "View fonts, page sizes, encryption and attachments",
        "image.to_pdf": "Combine ordered images into a PDF",
        "pdf.merge": "Join PDFs without rasterizing pages",
        "pdf.split": "Save selected page ranges as separate PDFs",
        "pdf.extract": "Save a copy of selected pages",
        "pdf.reorder": "Change the page order in a new copy",
        "pdf.delete": "Remove selected pages from a copy",
        "pdf.crop": "Trim page margins; this does not redact content",
        "pdf.rotate": "Turn selected pages",
        "pdf.number": "Add visible page numbers",
        "pdf.watermark": "Add a visible text watermark",
        "pdf.protect": "Encrypt a PDF with a password",
        "pdf.unlock": "Remove encryption using the correct password",
        "pdf.flatten": "Make form and annotation appearances permanent",
        "pdf.remove_metadata": "Remove PDF document properties",
        "pdf.compress": "Reduce file size with clear quality controls",
        "office.to_pdf": "Render local Office documents as PDFs",
        "pdf.ocr": "Make scanned pages searchable using local OCR",
        "pdf.redact": "Permanently mask areas and rebuild pages as images",
        "pdf.to_docx": "Export selectable text into editable paragraphs",
        "pdf.to_xlsx": "Export detected tables into a spreadsheet",
        "pdf.to_pptx": "Export pages as image slides",
        "metadata.inspect": "Inspect metadata and compare cleaned files",
        "metadata.neutral_text": "Make a neutral-name copy; text contents remain",
    }
    if spec.operation_id in descriptions:
        return descriptions[spec.operation_id]
    if spec.operation_id.startswith("metadata.clean"):
        return "Remove supported metadata from a separate copy"
    if spec.operation_id.startswith("image.to_"):
        return "Resize, convert and target a file size"
    if spec.operation_id in ("pdf.to_jpeg", "pdf.to_png"):
        return "Render PDF pages into images at your chosen resolution"
    if spec.operation_id.startswith("pdf.to_"):
        return "Export existing text from PDF pages"
    return category(spec)


class ToolText(QLabel):
    """Measure wrapped card text with the same font and width used to paint it."""

    def heightForWidth(self, width):
        metrics = self.fontMetrics()
        rect = metrics.boundingRect(
            QRect(0, 0, max(1, width), 1_000_000),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )
        return max(metrics.height(), rect.height()) + 1


class ToolCard(QPushButton):
    """Size the whole card from its wrapped content rather than empty button text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setSizePolicy(policy)

    def minimumSizeHint(self):
        return self.layout().totalMinimumSize().expandedTo(QSize(210, 164))

    def sizeHint(self):
        return QSize(260, self.heightForWidth(260)).expandedTo(self.minimumSizeHint())

    @staticmethod
    def _content_height(widget, width):
        return (
            widget.heightForWidth(width)
            if widget.hasHeightForWidth()
            else widget.sizeHint().height()
        )

    def heightForWidth(self, width):
        content = self.layout()
        margins = content.contentsMargins()
        available = max(1, width - margins.left() - margins.right())
        # Measure labels directly: Qt's layout height cache can retain earlier
        # wrapping metrics after a stylesheet/font change on Windows.
        height = margins.top() + margins.bottom()
        height += max(0, content.count() - 1) * content.spacing()
        for index in range(content.count()):
            text = content.itemAt(index).widget()
            height += self._content_height(text, available)
        return max(164, height)

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and self.layout() is not None:
            self._sync_height()
        return result

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.layout() is not None:
            self._sync_height()

    def _sync_height(self):
        content = self.layout()
        margins = content.contentsMargins()
        available = max(1, self.width() - margins.left() - margins.right())
        for index in range(content.count()):
            text = content.itemAt(index).widget()
            text.setFixedHeight(self._content_height(text, available))
        height = self.heightForWidth(self.width())
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
            if self.parentWidget() is not None:
                self.parentWidget().update_row_heights()


class ToolLibrary(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.cards = []
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.grid.setContentsMargins(0, 0, 16, 0)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.columns = 0
        self._visible_indices = None
        for index, spec in enumerate(window._operations):
            card = ToolCard(self)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.clicked.connect(lambda checked=False, i=index: window._select_tool(i))
            card.setObjectName("toolCard")
            card.setMinimumHeight(164)
            card.setMinimumWidth(210)
            card.setAccessibleName(spec.label)
            card.setToolTip(f"Open {spec.label}")
            content = QVBoxLayout(card)
            content.setContentsMargins(18, 18, 18, 18)
            content.setSpacing(8)
            content.setAlignment(Qt.AlignmentFlag.AlignTop)
            badge = label(
                "META"
                if spec.operation_id.startswith("metadata.")
                else spec.output_formats[0].value.upper(),
                "badge",
            )
            badge.setWordWrap(False)
            header = QWidget()
            header.setObjectName("inlineControl")
            header_row = QHBoxLayout(header)
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.addWidget(badge)
            header_row.addStretch()
            from local_pdf_toolkit.ui.controls import InfoButton

            explanation = " ".join(spec.limitations)
            engine = required_engine(spec)
            if engine and engine.lower() not in explanation.lower():
                explanation = f"Requires separately installed {engine}. " + explanation
            info = InfoButton(explanation)
            info.setAccessibleName(f"About {spec.label}")
            info_size = info.sizePolicy()
            info_size.setRetainSizeWhenHidden(True)
            info.setSizePolicy(info_size)
            header_row.addWidget(info)
            info.setVisible(bool(explanation))
            content.addWidget(header)
            title = ToolText(spec.label.replace(" / resize / compress", ""))
            title.setObjectName("section")
            title.setWordWrap(True)
            title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            content.addWidget(title)
            subtitle = tool_description(spec)
            card.setAccessibleDescription(subtitle)
            description = ToolText(subtitle)
            description.setObjectName("muted")
            description.setWordWrap(True)
            description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            content.addWidget(description)
            for child in card.findChildren(QLabel):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                child.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            self.cards.append(card)
        self.reflow()

    def reflow(self):
        indices = tuple(
            index
            for index in range(len(self.cards))
            if not self.window.operation_list.item(index).isHidden()
        )
        columns = max(1, min(3, self.width() // 260))
        if indices == self._visible_indices and columns == self.columns:
            return
        selection_changed = indices != self._visible_indices
        self._visible_indices = indices
        if selection_changed and hasattr(self.window, "library_scroll"):
            self.window.library_scroll.verticalScrollBar().setValue(0)
        for row in range(self.grid.rowCount()):
            self.grid.setRowMinimumHeight(row, 0)
        while self.grid.count():
            self.grid.takeAt(0)
        visible = []
        for index, card in enumerate(self.cards):
            show = not self.window.operation_list.item(index).isHidden()
            card.setVisible(show)
            if show:
                visible.append(card)
        self.columns = columns
        # Qt omits gaps for empty columns; reserve their space so a short
        # category keeps the same column width as the full library.
        missing_gaps = max(0, columns - len(visible))
        self.grid.setContentsMargins(0, 0, 16 + missing_gaps * self.grid.spacing(), 0)
        for index, card in enumerate(visible):
            self.grid.addWidget(card, index // self.columns, index % self.columns)
        for col in range(3):
            self.grid.setColumnMinimumWidth(col, 1 if col < self.columns else 0)
            self.grid.setColumnStretch(col, 1 if col < self.columns else 0)
        self.update_row_heights()

    def update_row_heights(self):
        if not self.grid.count():
            self.updateGeometry()
            return
        # Measure every tool at the current column width so switching categories
        # does not change card heights, even when longer descriptions are hidden.
        width = self.grid.itemAt(0).widget().width()
        height = max(card.heightForWidth(width) for card in self.cards)
        rows = (self.grid.count() + self.columns - 1) // self.columns
        for row in range(rows):
            self.grid.setRowMinimumHeight(row, height)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if max(1, min(3, self.width() // 260)) != self.columns:
            self.reflow()


class CategoryOverview(QWidget):
    """Show three columns when possible, reducing them for larger text or narrow windows."""

    def __init__(self, window):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setContentsMargins(0, 0, 22, 0)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.buttons = {}
        for name in CATEGORIES[1:]:
            card = button(name, lambda checked=False, n=name: window._browse_tools(n))
            card.setMinimumHeight(64)
            card.setAccessibleName(f"Browse {name}")
            self.buttons[name] = card
        self.browse = button("Browse all tools", lambda: window._browse_tools("All tools"))
        self.columns = 0
        self.reflow()

    def reflow(self):
        minimum = max(160, *(card.sizeHint().width() for card in self.buttons.values()))
        columns = max(1, min(3, (self.width() + 14) // (minimum + 14)))
        if columns == self.columns:
            return
        self.columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        self.grid.addWidget(self.browse, 0, 0, 1, columns)
        for index, card in enumerate(self.buttons.values()):
            self.grid.addWidget(card, 1 + index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


def build_window(w):
    w.resize(1380, 860)
    w.setMinimumSize(760, 620)
    w._operations = w.registry.list_operations()
    w._category = "All tools"
    w._overview = True
    # This selection model is shared by cards, search, options and keyboard actions.
    w.operation_list = QListWidget(w)
    w.operation_list.addItems([spec.label for spec in w._operations])
    w.operation_list.hide()
    root = QSplitter()
    w.library_splitter = root
    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    sidebar.setMinimumWidth(180)
    sidebar.setMaximumWidth(250)
    w.sidebar = sidebar
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(10, 18, 10, 14)
    side.setSpacing(12)
    w.sidebar_layout = side
    w.sidebar_header = QWidget()
    w.sidebar_header.setObjectName("inlineControl")
    sidebar_header = QHBoxLayout(w.sidebar_header)
    sidebar_header.setContentsMargins(0, 0, 0, 0)
    w.sidebar_brand = label("PDF Toolkit", "section")
    sidebar_header.addWidget(w.sidebar_brand, 1)
    from local_pdf_toolkit.ui.sidebar import CategoryNavigation, ChevronButton, SidebarToggle

    w.sidebar_toggle = SidebarToggle()
    w.sidebar_toggle.setObjectName("sidebarToggle")
    w.sidebar_toggle.clicked.connect(lambda: w._set_sidebar_collapsed(not w.navigation.collapsed))
    w.sidebar_toggle.setAccessibleName("Collapse sidebar")
    sidebar_header.addWidget(w.sidebar_toggle, alignment=Qt.AlignmentFlag.AlignHCenter)
    side.addWidget(w.sidebar_header)
    w.navigation = CategoryNavigation()
    w.navigation.setObjectName("navigation")
    w.navigation.setAccessibleName("Tool categories")
    w.navigation.addItems(CATEGORIES)
    w.navigation.refresh_icons()
    side.addWidget(w.navigation)
    root.addWidget(sidebar)
    canvas = QWidget()
    canvas.setObjectName("canvas")
    outer = QVBoxLayout(canvas)
    outer.setContentsMargins(22, 20, 0, 16)
    outer.setSpacing(16)
    bar = QHBoxLayout()
    bar.setContentsMargins(0, 0, 22, 0)
    w.back_button = ChevronButton("Home")
    w.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
    w.back_button.clicked.connect(w._show_library)
    w.back_button.setMinimumHeight(36)
    bar.addWidget(w.back_button)
    w.library_title = label("All tools", "title")
    bar.addWidget(w.library_title)
    bar.addStretch()
    w.settings_toggle = QPushButton("Options")
    w.settings_toggle.setCheckable(True)
    w.settings_toggle.setChecked(True)
    w.settings_toggle.setAccessibleName("Show options and output")
    w.settings_toggle.setToolTip("Show or hide options and output (Ctrl+Shift+B)")
    w.settings_toggle.toggled.connect(lambda checked: w.settings_action.setChecked(checked))
    bar.addWidget(w.settings_toggle)
    w.search = QLineEdit()
    w.search.setPlaceholderText("Search tools")
    w.search.setAccessibleName("Search tools")
    w.search.setClearButtonEnabled(True)
    w.search.setMaximumWidth(330)
    bar.addWidget(w.search, 1)
    # Give the toolbar controls the same height, while allowing larger text to
    # increase the row rather than clipping a fixed-height control.
    for control in (w.back_button, w.settings_toggle, w.search):
        policy = control.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        control.setSizePolicy(policy)
        control.setMinimumHeight(36)
    outer.addLayout(bar)
    w.pages = QStackedWidget()
    outer.addWidget(w.pages, 1)
    w.dashboard = QWidget()
    home = QVBoxLayout(w.dashboard)
    home.setContentsMargins(0, 0, 0, 0)
    home.setSpacing(12)
    w.library_count = label(f"{len(w._operations)} tools · Choose one to get started", "eyebrow")
    home.addWidget(w.library_count)
    w.home_views = QStackedWidget()
    overview = CategoryOverview(w)
    w.category_buttons = overview.buttons
    w.home_views.addWidget(overview)
    w.library = ToolLibrary(w)
    library_scroll = QScrollArea()
    w.library_scroll = library_scroll
    library_scroll.setWidgetResizable(True)
    library_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    library_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    library_scroll.setWidget(w.library)
    w.home_views.addWidget(library_scroll)
    home.addWidget(w.home_views, 1)
    w.library_title.setText("Choose a category")
    w.library_count.hide()
    if not w._operations:
        home.addWidget(label("No conversion tools available yet.", "muted"))
    w.pages.addWidget(w.dashboard)
    w.workspace = QWidget()
    work = QVBoxLayout(w.workspace)
    work.setContentsMargins(0, 0, 0, 0)
    work.setSpacing(12)
    w.tool_title = label("Choose a tool", "title")
    work.addWidget(w.tool_title)
    w.tool_hint = label("Add your files, choose your options, and save a new copy.", "muted")
    work.addWidget(w.tool_hint)
    w.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
    w.workspace_splitter.setObjectName("workspaceSplitter")
    w.workspace_splitter.setChildrenCollapsible(False)
    w.workspace_splitter.setHandleWidth(6)
    files_panel, files_layout = panel()
    files_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    files_layout.setContentsMargins(14, 16, 14, 16)
    row = QHBoxLayout()
    w.file_heading = label("Files", "section")
    row.addWidget(w.file_heading)
    row.addStretch()
    w.clear_button = button("×", w._clear)
    w.clear_button.setFixedSize(36, 36)
    w.clear_button.setAccessibleName("Clear all files")
    w.clear_button.setToolTip("Clear all files")
    row.addWidget(w.clear_button)
    files_layout.addLayout(row)
    w.add_button = button("Add…", w._choose_files)
    w.add_button.setAccessibleName("Add files")
    files_layout.addWidget(w.add_button)
    w.drop_hint = label("Drop files here", "muted")
    w.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.drop_hint.setMinimumHeight(110)
    files_layout.addWidget(w.drop_hint, 1)
    w.files = QListWidget()
    w.files.setAccessibleName("Input files, order and job results")
    w.files.setMinimumHeight(100)
    w.files.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    w.files.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.files.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.files.itemDoubleClicked.connect(w._open_result)
    w.files.currentRowChanged.connect(w._sync_comparison)
    w.files.hide()
    from local_pdf_toolkit.ui.controls import ChoiceBox

    w.batch_filter = ChoiceBox()
    w.batch_filter.setAccessibleName("Filter batch files")
    for caption, key in (
        ("All files", "all"),
        ("Failed", "failed"),
        ("Saved", "saved"),
        ("Pending", "pending"),
        ("Cancelled", "cancelled"),
    ):
        w.batch_filter.addItem(caption, key)
    w.batch_filter.currentIndexChanged.connect(lambda _: w._apply_batch_filter())
    w.batch_filter.hide()
    files_layout.addWidget(w.batch_filter)
    files_layout.addWidget(w.files, 1)
    w.preview_button = button("Preview", w._open_preview)
    w.preview_button.setAccessibleName("Preview selected file")
    w.preview_button.setToolTip("Show the selected document in the preview pane")
    files_layout.insertWidget(2, w.preview_button)
    file_actions = QGridLayout()
    file_actions.setSpacing(6)
    w.up_button = button("↑", lambda: w._move(-1))
    w.up_button.setAccessibleName("Move file up")
    w.up_button.setToolTip("Move file up")
    w.down_button = button("↓", lambda: w._move(1))
    w.down_button.setAccessibleName("Move file down")
    w.down_button.setToolTip("Move file down")
    w.remove_button = button("Remove", w._remove)
    w.cancel_selected = button("Cancel", w._cancel_one)
    w.cancel_selected.setAccessibleName("Cancel selected file")
    w.cancel_selected.setToolTip("Cancel selected file")
    file_actions.addWidget(w.up_button, 0, 0)
    file_actions.addWidget(w.down_button, 0, 1)
    file_actions.addWidget(w.remove_button, 1, 0, 1, 2)
    file_actions.addWidget(w.cancel_selected, 2, 0, 1, 2)
    files_layout.addLayout(file_actions)
    w.files_scroll = QScrollArea()
    w.files_scroll.setWidgetResizable(True)
    w.files_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.files_scroll.setMinimumWidth(180)
    w.files_scroll.setWidget(files_panel)
    w.workspace_splitter.addWidget(w.files_scroll)
    w.preview_host = QWidget()
    w.preview_host.setObjectName("previewHost")
    w.preview_host.setMinimumWidth(220)
    preview_layout = QVBoxLayout(w.preview_host)
    preview_layout.setContentsMargins(0, 0, 0, 0)
    preview_layout.setSpacing(8)
    w.selected_outcome = label("", "muted")
    w.selected_outcome.setAccessibleName("Selected file outcome")
    w.selected_outcome.hide()
    preview_layout.addWidget(w.selected_outcome)
    w.workspace_splitter.addWidget(w.preview_host)
    w.settings_panel = QWidget()
    w.settings_panel.setObjectName("settingsPanel")
    settings = QVBoxLayout(w.settings_panel)
    settings.setContentsMargins(0, 0, 16, 0)
    settings.setSpacing(14)
    from local_pdf_toolkit.ui.inspector import FormBody, InspectorSection, OptionLabel

    w.options_widget = FormBody()
    w.form = w.options_widget.form
    w.options_section = InspectorSection("Options", w.options_widget)
    w.options_heading = w.options_section.button
    w.notice = w.options_section.help
    settings.addWidget(w.options_section)
    w.advanced_widget = FormBody()
    w.advanced_form = w.advanced_widget.form
    w.advanced_section = InspectorSection("Advanced", w.advanced_widget)
    w.advanced_toggle = w.advanced_section.button
    w.advanced_toggle.setAccessibleName("Advanced options")
    w.advanced_section.hide()
    settings.addWidget(w.advanced_section)
    output_body = QWidget()
    output_body.setObjectName("options")
    output_layout = QVBoxLayout(output_body)
    output_layout.setContentsMargins(0, 0, 0, 0)
    output_layout.setSpacing(10)
    output_layout.addWidget(label("Folder"))
    w.destination = QLineEdit()
    w.destination.setPlaceholderText("Choose folder")
    w.destination.setAccessibleName("Output folder")
    output_layout.addWidget(w.destination)
    w.browse = button("Browse…", w._choose_directory)
    w.browse.setAccessibleName("Choose output folder")
    output_layout.addWidget(w.browse)
    output_layout.addWidget(
        OptionLabel(
            "Filename",
            "Leave blank for automatic names. The format extension is added automatically; "
            "existing files are never replaced.",
        )
    )
    w.output_name = QLineEdit()
    w.output_name.setPlaceholderText("Automatic name")
    w.output_name.setAccessibleName("Output name")
    w.output_name.textEdited.connect(w._settings_changed)
    output_layout.addWidget(w.output_name)
    w.open_button = button("Open folder", w._open_directory)
    w.open_button.setAccessibleName("Open output folder")
    output_layout.addWidget(w.open_button)
    w.report_button = button("View report", w._open_report)
    w.report_button.setAccessibleName("View cleaning report")
    w.report_button.setEnabled(False)
    w.report_button.hide()
    output_layout.addWidget(w.report_button)
    w.output_section = InspectorSection("Save copy", output_body)
    settings.addWidget(w.output_section)
    settings.addStretch()
    w.settings_scroll = QScrollArea()
    w.settings_scroll.setWidgetResizable(True)
    w.settings_scroll.setWidget(w.settings_panel)
    # On very small windows or with enlarged text, keep every section reachable.
    w.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    w.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    # Leave room for option captions, their help buttons, and the scrollbar.
    w.settings_scroll.setMinimumWidth(252)
    w.workspace_splitter.addWidget(w.settings_scroll)
    w.workspace_splitter.setStretchFactor(0, 0)
    w.workspace_splitter.setStretchFactor(1, 1)
    w.workspace_splitter.setStretchFactor(2, 0)
    w.workspace_splitter.setSizes([230, 520, 310])
    work.addWidget(w.workspace_splitter, 1)
    w.result_banner, result_layout = panel()
    w.result_banner.setObjectName("resultBanner")
    result_layout.setContentsMargins(16, 12, 16, 12)
    result_layout.setSpacing(7)
    w.result_title = label("Ready to make a new copy", "resultTitle")
    w.result_detail = label("Add files and choose where to save them.", "muted")
    w.result_title.setAccessibleName("Result status")
    w.result_detail.setAccessibleName("Result details")
    result_layout.addWidget(w.result_title)
    result_layout.addWidget(w.result_detail)
    result_actions = QHBoxLayout()
    w.result_open = button(
        "Open result",
        lambda: w._open_result(w.files.currentItem())
        if w.files.currentItem() is not None
        else None,
    )
    w.result_compare = button("Compare", w._open_comparison)
    w.result_compare.setAccessibleName("Compare original and converted file")
    w.compare_button = w.result_compare
    w.result_retry = button("Retry failed", w._retry)
    w.retry_button = w.result_retry

    w.result_adjust = button("Adjust options", w._adjust_settings)
    w.result_metadata = button("View metadata", w._open_metadata_values)
    w.result_metadata.hide()
    for control in (
        w.result_open,
        w.result_metadata,
        w.result_compare,
        w.result_retry,
        w.result_adjust,
    ):
        result_actions.addWidget(control)
    result_actions.addStretch()
    result_layout.addLayout(result_actions)
    w.result_open.setEnabled(False)
    w.result_compare.setEnabled(False)
    w.result_compare.hide()
    w.result_retry.hide()
    work.addWidget(w.result_banner)
    w.pages.addWidget(w.workspace)
    w.progress = QProgressBar()
    w.progress.setRange(0, 100)
    w.progress.setValue(0)
    w.progress.setTextVisible(False)
    outer.addWidget(w.progress)
    footer = QHBoxLayout()
    footer.setContentsMargins(0, 0, 22, 0)
    w.feedback = label("Ready when you are.", "muted")
    w.feedback.setAccessibleName("Conversion progress and feedback")
    footer_text = QVBoxLayout()
    footer_text.setContentsMargins(0, 0, 0, 0)
    footer_text.setSpacing(4)
    w.summary = label("", "summary")
    w.summary.setAccessibleName("Conversion summary")
    footer_text.addWidget(w.summary)
    footer_text.addWidget(w.feedback)
    footer.addLayout(footer_text, 1)
    w.cancel_button = button("Cancel", w._cancel)
    w.cancel_button.setEnabled(False)
    w.start_button = button("Run tool", w._start, primary=True)
    footer.addWidget(w.cancel_button)
    footer.addWidget(w.start_button)
    outer.addLayout(footer)
    root.addWidget(canvas)
    root.setSizes([190, 1190])
    root.setCollapsible(0, False)
    root.setCollapsible(1, False)
    w.setCentralWidget(root)
    w.drop_overlay = label("Drop files to add them", "dropOverlay")
    w.drop_overlay.setParent(canvas)
    w.drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.drop_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    w.drop_overlay.setAccessibleName("Drop files to add them")
    w.drop_overlay.hide()
    w.search.textChanged.connect(w._filter_tools)
    w.navigation.currentRowChanged.connect(w._category_changed)
    w.navigation.itemClicked.connect(w._sidebar_clicked)
    w.navigation.activate_requested.connect(w._sidebar_activated)
    w.navigation.setCurrentRow(0)
    w.operation_list.currentRowChanged.connect(w._options)
    w.operation_list.setCurrentRow(0 if w._operations else -1)
    w._options(w.operation_list.currentRow())
    w.statusBar().messageChanged.connect(w._show_status)
    w.statusBar().hide()
    w.statusBar().showMessage("Choose a tool to get started. Files are processed locally.")
    w.back_button.hide()
    w.start_button.setVisible(False)
    w.settings_toggle.setVisible(False)
    w.cancel_button.setVisible(False)
    w.pages.currentChanged.connect(lambda _: sync_workspace(w))
    w._sync_files()
    add_menus(w)
    sync_workspace(w)
    apply_theme(w)
    # Color changes follow the operating system, without an app-specific toggle.
    from PySide6.QtWidgets import QApplication

    QApplication.styleHints().colorSchemeChanged.connect(w._appearance_changed)


def sync_workspace(w):
    active = w.pages.currentWidget() == w.workspace
    w.back_button.setVisible(active)
    w.library_title.setVisible(not active)
    w.start_button.setVisible(active)
    w.cancel_button.setVisible(active and w._active)
    w.summary.setVisible(active)
    w.feedback.setVisible(
        active and bool(w.feedback.text()) and w.feedback.text() != w.result_title.text()
    )
    w.progress.setVisible(active and w._active)
    w.settings_toggle.setVisible(active)
    w.back_button.setText("Home" if active else "Tool library")


def add_menus(w):
    file_menu = w.menuBar().addMenu("&File")
    w.file_menu = file_menu
    from local_pdf_toolkit.ui.start_menu import add_shortcut, available

    for attribute, label, location in (
        ("start_menu_action", "Add to Start menu…", "start_menu"),
        ("desktop_shortcut_action", "Add Desktop shortcut…", "desktop"),
    ):
        action = QAction(label, w)
        setattr(w, attribute, action)
        action.setEnabled(available())
        if not available():
            action.setToolTip("Available in the Windows app download")
        action.triggered.connect(lambda checked=False, where=location: add_shortcut(w, where))
        file_menu.addAction(action)
    file_menu.addSeparator()
    tools_menu = w.menuBar().addMenu("&Tools")
    w.tools_menu = tools_menu
    view_menu = w.menuBar().addMenu("&View")
    w.view_menu = view_menu
    for title, shortcut, callback in (
        (
            "Paste files",
            QKeySequence.StandardKey.Paste,
            lambda: getattr(w, "_paste_files", lambda: None)(),
        ),
        (
            "Undo file change",
            QKeySequence.StandardKey.Undo,
            lambda: getattr(w, "_undo_file_change", lambda: None)(),
        ),
        ("Add files…", QKeySequence.StandardKey.Open, w._choose_files),
        ("Choose output folder…", "Ctrl+Shift+O", w._choose_directory),
        ("Run tool", "Ctrl+Return", w._start),
        ("Cancel batch", "Escape", w._cancel),
        ("Close", QKeySequence.StandardKey.Close, w.close),
    ):
        action = QAction(title, w)
        action.setShortcut(shortcut)
        action.triggered.connect(callback)
        file_menu.addAction(action)
    w.tool_category_menus = {name: tools_menu.addMenu(name) for name in CATEGORIES[1:]}
    for index, spec in enumerate(w._operations):
        action = QAction(spec.label, w)
        action.triggered.connect(lambda checked=False, i=index: w._select_tool(i))
        w.tool_category_menus[category(spec)].addAction(action)
    search = QAction("Find a tool", w)
    search.setShortcut(QKeySequence.StandardKey.Find)
    search.triggered.connect(w.search.setFocus)
    view_menu.addAction(search)
    library = QAction("Tool library", w)
    library.setShortcut("Alt+Left")
    library.triggered.connect(w._show_library)
    view_menu.addAction(library)
    sidebar_action = QAction("Expand sidebar", w)
    w.sidebar_action = sidebar_action
    sidebar_action.setCheckable(True)
    sidebar_action.setChecked(True)
    sidebar_action.setShortcut("Ctrl+B")
    sidebar_action.toggled.connect(lambda expanded: w._set_sidebar_collapsed(not expanded))
    view_menu.addAction(sidebar_action)
    settings_action = QAction("Show options and output", w)
    w.settings_action = settings_action
    settings_action.setCheckable(True)
    settings_action.setChecked(True)
    settings_action.setShortcut("Ctrl+Shift+B")
    settings_action.toggled.connect(w.settings_scroll.setVisible)
    settings_action.toggled.connect(w.settings_toggle.setChecked)
    view_menu.addAction(settings_action)
    availability = QAction("Tool availability…", w)
    availability.triggered.connect(lambda: getattr(w, "_show_availability", lambda: None)())
    tools_menu.addSeparator()
    tools_menu.addAction(availability)
    recovery = QAction("Clean up interrupted jobs…", w)
    w.recovery_action = recovery
    recovery.triggered.connect(lambda: w._show_recovery())
    tools_menu.addAction(recovery)
    queue_menu = w.menuBar().addMenu("&Queue")
    w.queue_menu = queue_menu
    for title, callback in (
        ("Move up", lambda: w._move(-1)),
        ("Move down", lambda: w._move(1)),
        ("Remove selected", w._remove),
        ("Retry failed", w._retry),
        ("Cancel selected", w._cancel_one),
        (
            "Open result",
            lambda: w._open_result(w.files.currentItem())
            if w.files.currentItem() is not None
            else None,
        ),
        ("Open output folder", w._open_directory),
        ("View cleaning report", w._open_report),
        ("Preview selected", w._open_preview),
        ("Compare before / after", w._open_comparison),
    ):
        action = QAction(title, w)
        action.triggered.connect(callback)
        queue_menu.addAction(action)


def matches_search(spec, text):
    """Match familiar task words, allowing multiword searches in any order."""
    aliases = {
        "pdf.to_jpeg": "jpg picture photo export extract pages render",
        "pdf.to_png": "picture photo export extract pages render",
        "pdf.merge": "combine join concatenate",
        "pdf.split": "separate extract pages",
        "pdf.compress": "shrink reduce smaller size optimize optimise",
        "pdf.remove_metadata": "privacy clean erase author properties",
        "pdf.protect": "password encrypt lock security",
        "pdf.unlock": "password decrypt security",
        "pdf.redact": "black out hide sensitive erase privacy",
        "pdf.ocr": "scan searchable recognize recognise text",
    }
    words = " ".join(
        (
            spec.label,
            spec.operation_id.replace("_", " "),
            category(spec),
            aliases.get(spec.operation_id, ""),
        )
    )
    if spec.operation_id.startswith("image.to_"):
        words += " photo picture"
        if spec.operation_id != "image.to_pdf":
            words += " resize dimensions scale shrink compress target size"
    if spec.operation_id.startswith("metadata."):
        words += " privacy clean remove erase author properties exif gps location"
    words = words.casefold()
    return all(token in words for token in text.casefold().split())


def search_score(spec, text):
    """Prefer a named tool before broader task synonyms in search selection."""
    query = " ".join(text.casefold().split())
    title = " ".join(spec.label.casefold().split())
    if query and query == title:
        return 3
    if query and all(token in title for token in query.split()):
        return 2
    return int(matches_search(spec, text))


def required_engine(spec):
    """Describe optional local dependencies without probing or starting them."""
    return {
        "office.to_pdf": "LibreOffice",
        "pdf.ocr": "Tesseract",
        "metadata.clean_media": "FFmpeg",
    }.get(spec.operation_id)

"""Tool library and focused workspaces; conversion behavior lives in MainWindow."""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
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
        "metadata.inspect": "Compare detected fields without revealing private values",
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


class ToolCard(QPushButton):
    """Size the whole card from its wrapped content rather than empty button text."""

    def __init__(self):
        super().__init__()
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setSizePolicy(policy)

    def minimumSizeHint(self):
        return self.layout().totalMinimumSize().expandedTo(QSize(210, 164))

    def sizeHint(self):
        return QSize(260, self.heightForWidth(260)).expandedTo(self.minimumSizeHint())

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
            height += (
                text.heightForWidth(available)
                if text.hasHeightForWidth()
                else text.sizeHint().height()
            )
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
            text.setFixedHeight(
                text.heightForWidth(available)
                if text.hasHeightForWidth()
                else text.sizeHint().height()
            )
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
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.columns = 0
        for index, spec in enumerate(window._operations):
            card = ToolCard()
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.clicked.connect(lambda checked=False, i=index: window._select_tool(i))
            card.setObjectName("toolCard")
            card.setMinimumHeight(164)
            card.setMinimumWidth(210)
            card.setAccessibleName(spec.label)
            card.setToolTip(" ".join(spec.limitations) or f"Open {spec.label}")
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
            content.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)
            title = label(spec.label.replace(" / resize / compress", ""), "section")
            content.addWidget(title)
            subtitle = tool_description(spec)
            card.setAccessibleDescription(subtitle)
            content.addWidget(label(subtitle, "muted"))
            engine = required_engine(spec)
            if engine:
                dependency = label(f"Requires {engine}", "engineBadge")
                dependency.setAccessibleName(f"Requires separately installed {engine}")
                content.addWidget(dependency)
            for child in card.findChildren(QLabel):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                child.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            self.cards.append(card)
        self.reflow()

    def reflow(self):
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
        self.columns = max(1, min(3, self.width() // 260))
        for index, card in enumerate(visible):
            self.grid.addWidget(card, index // self.columns, index % self.columns)
        for col in range(3):
            self.grid.setColumnStretch(col, 1 if col < self.columns else 0)
        self.update_row_heights()

    def update_row_heights(self):
        heights = {}
        for index in range(self.grid.count()):
            row = self.grid.getItemPosition(index)[0]
            card = self.grid.itemAt(index).widget()
            heights[row] = max(heights.get(row, 0), card.minimumHeight())
        for row, height in heights.items():
            self.grid.setRowMinimumHeight(row, height)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if max(1, min(3, self.width() // 260)) != self.columns:
            self.reflow()


def build_window(w):
    w.resize(1380, 860)
    w.setMinimumSize(760, 620)
    w._operations = w.registry.list_operations()
    w._category = "All tools"
    # This selection model is shared by cards, search, options and keyboard actions.
    w.operation_list = QListWidget(w)
    w.operation_list.addItems([spec.label for spec in w._operations])
    w.operation_list.hide()
    root = QSplitter()
    w.library_splitter = root
    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    sidebar.setMinimumWidth(170)
    sidebar.setMaximumWidth(250)
    w.sidebar = sidebar
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(18, 26, 18, 20)
    side.setSpacing(18)
    side.addWidget(label("PDF Toolkit", "section"))
    side.addSpacing(6)
    side.addWidget(label("Library", "eyebrow"))
    w.navigation = QListWidget()
    w.navigation.setObjectName("navigation")
    w.navigation.setAccessibleName("Tool categories")
    w.navigation.addItems(CATEGORIES)
    side.addWidget(w.navigation)
    side.addWidget(label("Processed on your computer", "muted"))
    root.addWidget(sidebar)
    canvas = QWidget()
    canvas.setObjectName("canvas")
    outer = QVBoxLayout(canvas)
    outer.setContentsMargins(22, 20, 22, 16)
    outer.setSpacing(16)
    bar = QHBoxLayout()
    w.back_button = button("‹  All tools", w._show_library)
    bar.addWidget(w.back_button)
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
    outer.addLayout(bar)
    w.pages = QStackedWidget()
    outer.addWidget(w.pages, 1)
    w.dashboard = QWidget()
    home = QVBoxLayout(w.dashboard)
    home.setContentsMargins(0, 0, 0, 0)
    home.setSpacing(12)
    w.library_title = label("All tools", "title")
    home.addWidget(w.library_title)
    w.library_count = label(f"{len(w._operations)} tools · Choose one to get started", "eyebrow")
    home.addWidget(w.library_count)
    w.library = ToolLibrary(w)
    library_scroll = QScrollArea()
    library_scroll.setWidgetResizable(True)
    library_scroll.setWidget(w.library)
    home.addWidget(library_scroll, 1)
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
    w.clear_button.setAccessibleName("Clear all files")
    w.clear_button.setToolTip("Clear all files")
    row.addWidget(w.clear_button)
    files_layout.addLayout(row)
    w.add_button = button("Add…", w._choose_files)
    w.add_button.setAccessibleName("Add files")
    files_layout.addWidget(w.add_button)
    w.drop_hint = label("Drop files here.\nOriginals are always preserved.", "muted")
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
    preview_layout.setSpacing(0)
    w.workspace_splitter.addWidget(w.preview_host)
    w.settings_panel = QWidget()
    w.settings_panel.setObjectName("settingsPanel")
    settings = QVBoxLayout(w.settings_panel)
    settings.setContentsMargins(0, 0, 0, 0)
    settings.setSpacing(14)
    options_panel, options_layout = panel()
    options_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    options_layout.setContentsMargins(16, 18, 16, 18)
    w.options_heading = label("Options", "section")
    options_layout.addWidget(w.options_heading)
    w.options_widget = QWidget()
    w.options_widget.setObjectName("options")
    options_body = QVBoxLayout(w.options_widget)
    options_body.setContentsMargins(0, 0, 0, 0)
    options_body.setSpacing(12)
    options_body.setAlignment(Qt.AlignmentFlag.AlignTop)
    basic = QWidget()
    basic.setObjectName("options")
    w.form = QFormLayout(basic)
    w.form.setContentsMargins(0, 0, 0, 0)
    w.form.setSpacing(10)
    w.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    w.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    options_body.addWidget(basic)
    w.advanced_toggle = QPushButton("▸ Advanced")
    w.advanced_toggle.setCheckable(True)
    w.advanced_toggle.setObjectName("disclosure")
    w.advanced_toggle.setAccessibleName("Show advanced options")
    options_body.addWidget(w.advanced_toggle)
    w.advanced_widget = QWidget()
    w.advanced_widget.setObjectName("options")
    w.advanced_form = QFormLayout(w.advanced_widget)
    w.advanced_form.setContentsMargins(0, 0, 0, 0)
    w.advanced_form.setSpacing(10)
    w.advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    w.advanced_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    w.advanced_widget.hide()
    w.advanced_toggle.toggled.connect(w.advanced_widget.setVisible)
    w.advanced_toggle.toggled.connect(
        lambda expanded: w.advanced_toggle.setText("▾ Advanced" if expanded else "▸ Advanced")
    )
    w.advanced_toggle.toggled.connect(
        lambda expanded: w.advanced_toggle.setAccessibleName(
            "Hide advanced options" if expanded else "Show advanced options"
        )
    )
    options_body.addWidget(w.advanced_widget)
    options_layout.addWidget(w.options_widget)
    w.notice = label("", "muted")
    options_layout.addWidget(w.notice)
    settings.addWidget(options_panel)
    output_panel, output_layout = panel()
    output_layout.setContentsMargins(16, 18, 16, 18)
    output_layout.addWidget(label("Save a new copy", "section"))
    w.destination = QLineEdit()
    w.destination.setPlaceholderText("Choose an output folder")
    w.destination.setAccessibleName("Output folder")
    output_layout.addWidget(w.destination)
    w.browse = button("Browse…", w._choose_directory)
    w.browse.setAccessibleName("Choose output folder")
    output_layout.addWidget(w.browse)
    output_layout.addWidget(label("Output name"))
    w.output_name = QLineEdit()
    w.output_name.setPlaceholderText("Automatic name")
    w.output_name.setAccessibleName("Output name")
    w.output_name.textEdited.connect(w._settings_changed)
    output_layout.addWidget(w.output_name)
    output_layout.addWidget(label("The file extension is chosen automatically.", "muted"))
    w.open_button = button("Open folder", w._open_directory)
    w.open_button.setAccessibleName("Open output folder")
    w.open_button.setToolTip("Open the output folder")
    output_layout.addWidget(w.open_button)
    w.report_button = button("View report", w._open_report)
    w.report_button.setAccessibleName("View cleaning report")
    w.report_button.setEnabled(False)
    w.report_button.hide()
    output_layout.addWidget(w.report_button)
    settings.addWidget(output_panel)
    settings.addStretch()
    w.settings_scroll = QScrollArea()
    w.settings_scroll.setWidgetResizable(True)
    w.settings_scroll.setWidget(w.settings_panel)
    w.settings_scroll.setMinimumWidth(230)
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
    for control in (w.result_open, w.result_compare, w.result_retry, w.result_adjust):
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
    w.start_button.setVisible(active)
    w.cancel_button.setVisible(active and w._active)
    w.summary.setVisible(active)
    w.feedback.setVisible(
        active and bool(w.feedback.text()) and w.feedback.text() != w.result_title.text()
    )
    w.progress.setVisible(active and w._active)
    w.settings_toggle.setVisible(active)
    w.back_button.setText("‹  All tools" if active else "Tool library")


def add_menus(w):
    file_menu = w.menuBar().addMenu("&File")
    w.file_menu = file_menu
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
    sidebar_action = QAction("Show sidebar", w)
    w.sidebar_action = sidebar_action
    sidebar_action.setCheckable(True)
    sidebar_action.setChecked(True)
    sidebar_action.setShortcut("Ctrl+B")
    sidebar_action.toggled.connect(w.sidebar.setVisible)
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

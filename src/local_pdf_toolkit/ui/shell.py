"""Tool library and focused workspaces; conversion behavior lives in MainWindow."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
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
    if operation.startswith("metadata."):
        return "Privacy"
    if operation == "pdf.compress":
        return "Optimize"
    if operation in ("pdf.protect", "pdf.unlock", "pdf.remove_metadata"):
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


class ToolLibrary(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.cards = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.columns = 0
        for index, spec in enumerate(window._operations):
            card = button("", lambda checked=False, i=index: window._select_tool(i))
            card.setObjectName("toolCard")
            card.setMinimumHeight(164)
            card.setMinimumWidth(210)
            card.setAccessibleName(spec.label)
            card.setToolTip(" ".join(spec.limitations) or f"Open {spec.label}")
            content = QVBoxLayout(card)
            content.setContentsMargins(18, 18, 18, 18)
            badge = label(
                "META"
                if spec.operation_id.startswith("metadata.")
                else spec.output_formats[0].value.upper(),
                "badge",
            )
            badge.setMaximumWidth(74)
            content.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)
            title = label(spec.label.replace(" / resize / compress", ""), "section")
            content.addWidget(title)
            subtitle = (
                "Resize, convert & target a file size"
                if spec.operation_id.startswith("image.to_") and spec.operation_id != "image.to_pdf"
                else category(spec)
            )
            content.addWidget(label(subtitle, "muted"))
            for child in card.findChildren(QLabel):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.cards.append(card)
        self.reflow()

    def reflow(self):
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if max(1, min(3, self.width() // 260)) != self.columns:
            self.reflow()


def build_window(w):
    w.resize(1160, 850)
    w.setMinimumSize(760, 620)
    w._operations = w.registry.list_operations()
    w._category = "All tools"
    # This selection model is shared by cards, search, options and keyboard actions.
    w.operation_list = QListWidget(w)
    w.operation_list.addItems([spec.label for spec in w._operations])
    w.operation_list.hide()
    root = QSplitter()
    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    sidebar.setMinimumWidth(170)
    sidebar.setMaximumWidth(250)
    w.sidebar = sidebar
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(18, 26, 18, 20)
    side.setSpacing(18)
    side.addWidget(label("PDF Toolkit", "section"))
    side.addWidget(label("A place for your documents.", "muted"))
    side.addSpacing(16)
    side.addWidget(label("LIBRARY", "eyebrow"))
    w.navigation = QListWidget()
    w.navigation.setObjectName("navigation")
    w.navigation.setAccessibleName("Tool categories")
    w.navigation.addItems(CATEGORIES)
    side.addWidget(w.navigation)
    side.addWidget(label("ON YOUR COMPUTER", "eyebrow"))
    side.addWidget(label("Local processing.\nYour files stay yours.", "muted"))
    root.addWidget(sidebar)
    canvas = QWidget()
    canvas.setObjectName("canvas")
    outer = QVBoxLayout(canvas)
    outer.setContentsMargins(28, 24, 28, 20)
    outer.setSpacing(20)
    bar = QHBoxLayout()
    w.back_button = button("‹  All tools", w._show_library)
    bar.addWidget(w.back_button)
    bar.addStretch()
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
    home.setSpacing(18)
    w.library_title = label("Your document workspace.", "title")
    home.addWidget(w.library_title)
    home.addWidget(label("Convert, organize and refine. Everything happens locally.", "muted"))
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
    work.setSpacing(18)
    w.tool_title = label("Choose a tool", "title")
    work.addWidget(w.tool_title)
    w.tool_hint = label("Add your files, choose your options, and save a new copy.", "muted")
    work.addWidget(w.tool_hint)
    body = QWidget()
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(18)
    files_panel, files_layout = panel()
    row = QHBoxLayout()
    w.file_heading = label("Files", "section")
    row.addWidget(w.file_heading)
    row.addStretch()
    w.add_button = button("Add files…", w._choose_files)
    w.clear_button = button("Clear", w._clear)
    row.addWidget(w.clear_button)
    row.addWidget(w.add_button)
    files_layout.addLayout(row)
    w.drop_hint = label(
        "Drop documents here, or use Add files.\nOriginals are always preserved.", "muted"
    )
    w.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.drop_hint.setMinimumHeight(70)
    files_layout.addWidget(w.drop_hint)
    w.files = QListWidget()
    w.files.setAccessibleName("Input files, order and job results")
    w.files.setMinimumHeight(100)
    w.files.setMaximumHeight(190)
    w.files.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    w.files.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.files.itemDoubleClicked.connect(w._open_result)
    w.files.hide()
    files_layout.addWidget(w.files)
    file_actions = QGridLayout()
    w.up_button = button("Move up", lambda: w._move(-1))
    w.down_button = button("Move down", lambda: w._move(1))
    w.remove_button = button("Remove", w._remove)
    w.retry_button = button("Retry failed", w._retry)
    w.cancel_selected = button("Cancel selected", w._cancel_one)
    for index, control in enumerate(
        (w.up_button, w.down_button, w.remove_button, w.retry_button, w.cancel_selected)
    ):
        file_actions.addWidget(control, index // 3, index % 3)
    files_layout.addLayout(file_actions)
    body_layout.addWidget(files_panel)
    options_panel, options_layout = panel()
    w.options_heading = label("Options", "section")
    options_layout.addWidget(w.options_heading)
    w.options_widget = QWidget()
    w.options_widget.setObjectName("options")
    w.form = QFormLayout(w.options_widget)
    w.form.setContentsMargins(0, 0, 0, 0)
    w.form.setSpacing(12)
    w.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    w.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    options_layout.addWidget(w.options_widget)
    w.notice = label("", "muted")
    options_layout.addWidget(w.notice)
    body_layout.addWidget(options_panel)
    output_panel, output_layout = panel()
    output_layout.addWidget(label("Save a new copy", "section"))
    output_row = QHBoxLayout()
    w.destination = QLineEdit()
    w.destination.setPlaceholderText("Choose an output folder")
    w.destination.setAccessibleName("Output folder")
    w.browse = button("Choose…", w._choose_directory)
    output_row.addWidget(w.destination, 1)
    output_row.addWidget(w.browse)
    output_layout.addLayout(output_row)
    w.open_button = button("Open output folder", w._open_directory)
    output_actions = QHBoxLayout()
    output_actions.addWidget(w.open_button)
    w.report_button = button("View cleaning report", w._open_report)
    w.report_button.setEnabled(False)
    w.report_button.hide()
    output_actions.addWidget(w.report_button)
    output_actions.addStretch()
    output_layout.addLayout(output_actions)
    body_layout.addWidget(output_panel)
    body_layout.addStretch()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(body)
    work.addWidget(scroll, 1)
    w.pages.addWidget(w.workspace)
    w.progress = QProgressBar()
    w.progress.setRange(0, 100)
    w.progress.setValue(0)
    w.progress.setTextVisible(False)
    outer.addWidget(w.progress)
    footer = QHBoxLayout()
    w.feedback = label("Ready when you are.", "muted")
    w.feedback.setAccessibleName("Conversion progress and feedback")
    footer.addWidget(w.feedback, 1)
    w.cancel_button = button("Cancel", w._cancel)
    w.cancel_button.setEnabled(False)
    w.start_button = button("Run tool", w._start, primary=True)
    footer.addWidget(w.cancel_button)
    footer.addWidget(w.start_button)
    outer.addLayout(footer)
    root.addWidget(canvas)
    root.setSizes([200, 960])
    root.setCollapsible(0, False)
    root.setCollapsible(1, False)
    w.setCentralWidget(root)
    w.search.textChanged.connect(w._filter_tools)
    w.navigation.currentRowChanged.connect(w._category_changed)
    w.navigation.setCurrentRow(0)
    w.operation_list.currentRowChanged.connect(w._options)
    w.operation_list.setCurrentRow(0 if w._operations else -1)
    w._options(w.operation_list.currentRow())
    w.statusBar().messageChanged.connect(w.feedback.setText)
    w.statusBar().hide()
    w.statusBar().showMessage("Choose a tool to get started. Files are processed locally.")
    w.back_button.hide()
    w.start_button.setVisible(False)
    w.cancel_button.setVisible(False)
    w.pages.currentChanged.connect(lambda _: sync_workspace(w))
    w._sync_files()
    add_menus(w)
    apply_theme(w)
    # Color changes follow the operating system, without an app-specific toggle.
    from PySide6.QtWidgets import QApplication

    QApplication.styleHints().colorSchemeChanged.connect(w._appearance_changed)


def sync_workspace(w):
    active = w.pages.currentWidget() == w.workspace
    w.back_button.setVisible(active)
    w.start_button.setVisible(active)
    w.cancel_button.setVisible(active)
    w.back_button.setText("‹  All tools" if active else "Tool library")


def add_menus(w):
    file_menu = w.menuBar().addMenu("&File")
    tools_menu = w.menuBar().addMenu("&Tools")
    view_menu = w.menuBar().addMenu("&View")
    for title, shortcut, callback in (
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
    for index, spec in enumerate(w._operations):
        action = QAction(spec.label, w)
        action.triggered.connect(lambda checked=False, i=index: w._select_tool(i))
        tools_menu.addAction(action)
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
    queue_menu = w.menuBar().addMenu("&Queue")
    for title, callback in (
        ("Move up", lambda: w._move(-1)),
        ("Move down", lambda: w._move(1)),
        ("Remove selected", w._remove),
        ("Retry failed", w._retry),
        ("Cancel selected", w._cancel_one),
        ("Open output folder", w._open_directory),
        ("View cleaning report", w._open_report),
    ):
        action = QAction(title, w)
        action.triggered.connect(callback)
        queue_menu.addAction(action)

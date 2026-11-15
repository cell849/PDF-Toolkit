"""Quiet document surfaces with system appearance and native window chrome."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Semantic roles, kept here so controls, lists and popups share one vocabulary.
LIGHT = {
    "base": "#f5f6f8",
    "sidebar": "#eceff3",
    "surface": "#ffffff",
    "text": "#20242c",
    "secondary": "#596272",
    "border": "#cdd3de",
    "accent": "#075bac",
    "selection": "#e5effb",
    "primary_text": "#ffffff",
}
DARK = {
    "base": "#191c21",
    "sidebar": "#20242b",
    "surface": "#252a32",
    "text": "#f1f3f7",
    "secondary": "#b6bfce",
    "border": "#495261",
    "accent": "#90c2ff",
    "selection": "#193e68",
    "primary_text": "#132138",
}


def apply_theme(window, dark=None):
    if dark is None:
        dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    c = DARK if dark else LIGHT
    base, sidebar, surface, text, secondary, border, accent, selection, primary_text = (
        c[key]
        for key in (
            "base",
            "sidebar",
            "surface",
            "text",
            "secondary",
            "border",
            "accent",
            "selection",
            "primary_text",
        )
    )
    from local_pdf_toolkit.ui.icons import resource_path

    chevron = resource_path("chevron-dark.svg" if dark else "chevron-light.svg").as_posix()
    check = resource_path("check-dark.svg" if dark else "check-light.svg").as_posix()
    error, error_bg = ("#ffb4ab", "#3c2526") if dark else ("#b42318", "#fff1ef")
    success, success_bg = ("#a5dfb6", "#20382a") if dark else ("#24683b", "#effaf2")
    partial_bg = "#3a3020" if dark else "#fff7e6"
    palette = window.palette()
    for role, color in (
        (QPalette.ColorRole.Window, base),
        (QPalette.ColorRole.Base, surface),
        (QPalette.ColorRole.AlternateBase, sidebar),
        (QPalette.ColorRole.Button, surface),
        (QPalette.ColorRole.WindowText, text),
        (QPalette.ColorRole.Text, text),
        (QPalette.ColorRole.ButtonText, text),
        (QPalette.ColorRole.Highlight, selection),
        (QPalette.ColorRole.HighlightedText, text),
        (QPalette.ColorRole.PlaceholderText, secondary),
        (QPalette.ColorRole.ToolTipBase, surface),
        (QPalette.ColorRole.ToolTipText, text),
    ):
        palette.setColor(role, QColor(color))
    window.setPalette(palette)
    # Preserve the user's system font; only hierarchy changes its relative size.
    system_size = QApplication.font().pointSizeF()
    body_size = max(10.0, system_size) * float(window.property("textScale") or 1.0)
    window.setStyleSheet(f"""
        QMainWindow, QScrollArea, QWidget#canvas {{ background: {base}; color: {text}; }}
        QWidget {{ background: {base}; color: {text}; font-size: {body_size}pt; }}
        QFrame#sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
        QFrame#panel, QPushButton#toolCard, QFrame#resultBanner {{
            background: {surface}; border: 1px solid {border}; border-radius: 12px;
        }}
        QFrame#resultBanner {{ border: 2px solid {border}; }}
        QFrame#resultBanner[state="error"] {{ background: {error_bg}; border-color: {error}; }}
        QFrame#resultBanner[state="partial"] {{ background: {partial_bg}; border-color: {error}; }}
        QFrame#resultBanner[state="success"] {{ background: {success_bg};
            border-color: {success}; }}
        QLabel {{ background: transparent; border: none; }}
        QWidget#options, QWidget#inlineControl, QSlider, QCheckBox {{
            background: transparent;
        }}
        QLabel#title {{ font-size: {body_size + 11}pt; font-weight: 650; }}
        QLabel#section {{ font-size: {body_size + 2}pt; font-weight: 600; }}
        QLabel#resultTitle, QLabel#summary {{ font-weight: 600; }}
        QLabel#muted {{ color: {secondary}; }}
        QLabel#eyebrow {{ color: {secondary}; font-size: {body_size}pt; font-weight: 600; }}
        QLabel#engineBadge {{ color: {secondary}; font-size: {body_size}pt;
            padding: 4px 0; font-weight: 600;
        }}
        QLabel#dropOverlay {{ background: {selection}; color: {accent};
            border: 3px solid {accent}; border-radius: 12px;
            font-size: {body_size + 8}pt; font-weight: 600;
        }}
        QLabel#badge {{ background: {selection}; color: {accent}; border-radius: 8px;
            padding: 8px; font-weight: 700;
        }}
        QPushButton {{ background: {surface}; border: 1px solid {border};
            border-radius: 7px; padding: 7px 10px; font-weight: 500;
        }}
        QPushButton:hover {{ border-color: {accent}; background: {selection}; }}
        QPushButton:pressed {{ background: {selection}; border-color: {accent}; }}
        QPushButton:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QComboBox:focus {{ border: 2px solid {accent}; }}
        QPushButton#primary {{ background: {accent}; color: {primary_text};
            border-color: {accent}; font-weight: 650; padding: 10px 18px;
        }}
        QPushButton:disabled {{ color: {secondary}; background: {sidebar};
            border-color: {border};
        }}
        QPushButton#disclosure {{ text-align: left; background: transparent;
            border-color: transparent; padding-left: 0; font-weight: 600;
        }}
        QPushButton#disclosure:checked {{ color: {accent}; }}
        QPushButton#disclosure:focus {{ border-color: {accent}; }}
        QPushButton#toolCard {{ text-align: left; padding: 0; }}
        QPushButton#toolCard:hover {{ background: {surface}; border: 2px solid {accent}; }}
        QListWidget, QListView {{ background: {surface}; color: {text};
            border: 1px solid {border}; border-radius: 7px; padding: 4px; outline: 0;
        }}
        QListWidget::item, QListView::item {{ padding: 8px; border-radius: 5px; }}
        QListWidget::item:selected, QListView::item:selected {{
            background: {selection}; color: {text};
        }}
        QListWidget::item:hover, QListView::item:hover {{ background: {selection}; }}
        QListWidget::item:focus {{ border: 1px solid {accent}; }}
        QListWidget#navigation {{ background: transparent; border: 0; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {surface};
            color: {text}; border: 1px solid {border}; border-radius: 7px;
            padding: 6px 8px; min-height: 20px; selection-background-color: {selection};
            selection-color: {text};
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; height: 0; }}
        QComboBox {{ padding-right: 26px; }}
        QComboBox::drop-down {{ width: 24px; border: 0; }}
        QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 10px; }}
        QTabBar {{ background: transparent; }}
        QTabBar::tab {{ background: {sidebar}; color: {secondary}; padding: 8px 18px;
            border: 1px solid {border}; border-radius: 7px; margin-right: 3px; }}
        QTabBar::tab:selected {{ background: {selection}; color: {text}; border-color: {accent}; }}
        QTabBar::tab:disabled {{ color: {secondary}; }}
        QComboBox QAbstractItemView {{ background: {surface}; color: {text};
            border: 1px solid {border}; selection-background-color: {selection};
            selection-color: {text}; outline: 0;
        }}
        QCheckBox {{ spacing: 8px; padding: 5px 0; }}
        QCheckBox:focus {{ outline: 1px solid {accent}; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {secondary};
            border-radius: 4px; background: {surface}; }}
        QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent};
            image: url("{check}"); }}
        QCheckBox::indicator:disabled {{ border-color: {border}; }}
        QSlider:focus {{ border: 0; outline: none; }}
        QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ width: 16px; margin: -6px 0;
            background: {surface}; border: 1px solid {accent}; border-radius: 8px;
        }}
        QSlider:focus::handle:horizontal {{ border: 2px solid {accent}; }}
        QProgressBar {{ background: {sidebar}; border: 0; border-radius: 3px;
            min-height: 6px; max-height: 6px;
        }}
        QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
        QScrollArea {{ border: 0; }}
        QScrollBar:vertical {{ background: {base}; width: 10px; margin: 0; }}
        QScrollBar:horizontal {{ background: {base}; height: 10px; margin: 0; }}
        QScrollBar::handle {{ background: {border}; border-radius: 5px;
            min-height: 24px; min-width: 24px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QSplitter::handle {{ background: {base}; }}
        QSplitter::handle:hover {{ background: {border}; }}
        QStatusBar {{ background: {base}; color: {secondary}; }}
        QMenuBar, QMenu {{ background: {surface}; color: {text}; }}
        QMenu {{ padding: 5px; border: 1px solid {border}; border-radius: 8px; }}
        QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: 4px; }}
        QMenu::separator {{ height: 1px; background: {border}; margin: 4px 7px; }}
        QMenu::item:selected {{ background: {selection}; }}
        QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; }}
    """)

"""Apple-inspired desktop surfaces, using native Qt controls and system appearance."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(window, dark=None):
    if dark is None:
        dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    colors = (
        ("#18191c", "#222328", "#292b31", "#f5f5f7", "#b8bcc7", "#454854", "#83b7ff", "#153d70")
        if dark
        else (
            "#f5f5f7",
            "#eceef2",
            "#ffffff",
            "#1d1d1f",
            "#606574",
            "#d7dae2",
            "#005bb5",
            "#e3efff",
        )
    )
    base, sidebar, surface, text, secondary, border, accent, selection = colors
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
        (QPalette.ColorRole.HighlightedText, accent),
    ):
        palette.setColor(role, QColor(color))
    window.setPalette(palette)
    window.setStyleSheet(f"""
        QMainWindow, QScrollArea, QWidget#canvas {{ background: {base}; color: {text}; }}
        QWidget {{ background: {base}; color: {text}; font-size: 13px; }}
        QFrame#sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
        QFrame#panel, QPushButton#toolCard {{ background: {surface};
            border: 1px solid {border};
            border-radius: 14px;
            }}
        QLabel {{ background: transparent; border: none; }}
        QWidget#options {{ background: transparent; }}
        QLabel#title {{ font-size: 30px; font-weight: 650; }}
        QLabel#section {{ font-size: 17px; font-weight: 600; }}
        QLabel#muted {{ color: {secondary}; }}
        QLabel#eyebrow {{ color: {secondary}; font-size: 11px; font-weight: 600; }}
        QLabel#badge {{ background: {selection};
            color: {accent};
            border-radius: 10px;
            padding: 9px;
            font-weight: 700;
            }}
        QPushButton {{ background: {surface};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px 12px;
            font-weight: 500;
            }}
        QPushButton:hover {{ border-color: {accent}; background: {selection}; }}
        QPushButton:pressed {{ background: {selection}; border-color: {accent}; }}
        QPushButton:focus, QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border: 2px solid {accent};
            }}
        QPushButton#primary {{ background: {accent};
            color: {"#101826" if dark else "#ffffff"};
            border-color: {accent};
            font-weight: 650;
            }}
        QPushButton:disabled {{ color: {secondary};
            background: {sidebar};
            border-color: {border};
            }}
        QPushButton#toolCard {{ text-align: left; padding: 0; }}
        QPushButton#toolCard:hover {{ background: {surface}; border: 2px solid {accent}; }}
        QListWidget {{ background: {surface};
            border: 1px solid {border};
            border-radius: 9px;
            padding: 4px;
            outline: 0;
            }}
        QListWidget::item {{ padding: 9px; border-radius: 6px; }}
        QListWidget::item:selected {{ background: {selection}; color: {accent}; }}
        QListWidget::item:focus {{ border: 1px solid {accent}; }}
        QListWidget#navigation {{ background: transparent; border: 0; }}
        QLineEdit, QSpinBox, QComboBox {{ background: {surface};
            color: {text};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px;
            min-height: 18px;
            selection-background-color: {accent};
            }}
        QComboBox QAbstractItemView {{ background: {surface};
            color: {text};
            selection-background-color: {selection};
            }}
        QCheckBox {{ spacing: 8px; padding: 6px 0; }}
        QProgressBar {{ background: {sidebar};
            border: 0;
            border-radius: 4px;
            min-height: 7px;
            max-height: 7px;
            }}
        QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
        QScrollArea {{ border: 0; }}
        QScrollBar:vertical {{ background: {base}; width: 12px; margin: 0; }}
        QScrollBar:horizontal {{ background: {base}; height: 12px; margin: 0; }}
        QScrollBar::handle {{ background: {border};
            border-radius: 5px; min-height: 24px; min-width: 24px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QSplitter::handle {{ background: {border}; width: 1px; }}
        QStatusBar {{ background: {base}; color: {secondary}; }}
        QMenuBar, QMenu {{ background: {surface}; color: {text}; }}
        QMenu::item:selected {{ background: {selection}; }}
    """)

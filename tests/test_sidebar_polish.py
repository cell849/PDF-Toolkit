from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QStyleOptionViewItem

from local_pdf_toolkit.ui.design import DARK, LIGHT, apply_theme
from local_pdf_toolkit.ui.sidebar import CategoryNavigation


def test_navigation_cells_stay_aligned_across_selection_and_collapse(qapp):
    nav = CategoryNavigation()
    nav.setObjectName("navigation")
    nav.addItems(["Home", "Convert", "Images"])
    nav.refresh_icons()
    nav.resize(220, 200)
    nav.show()
    qapp.processEvents()
    try:
        for collapsed in (False, True):
            nav.set_collapsed(collapsed)
            qapp.processEvents()
            rects = [nav.visualItemRect(nav.item(i)) for i in range(nav.count())]
            cells = []
            for rect in rects:
                option = QStyleOptionViewItem()
                option.rect = rect
                cells.append(nav.itemDelegate().icon_rect(option))
            assert all(cell.width() == cell.height() == 40 for cell in cells)
            assert len({cell.x() for cell in cells}) == 1
            assert len({rect.height() for rect in rects}) == 1
            nav.setCurrentRow(2)
            qapp.processEvents()
            assert rects == [nav.visualItemRect(nav.item(i)) for i in range(nav.count())]
            assert all(nav.item(i).toolTip() == nav.item(i).text() for i in range(nav.count()))
    finally:
        nav.close()
        nav.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_navigation_accent_tracks_light_and_dark_theme(qapp):
    nav = CategoryNavigation()
    nav.setProperty("textScale", 1.0)
    try:
        for dark, colors in ((False, LIGHT), (True, DARK)):
            apply_theme(nav, dark=dark)
            assert nav.palette().color(QPalette.ColorRole.Link) == QColor(colors["accent"])
            assert nav.palette().color(QPalette.ColorRole.Highlight) == QColor(colors["selection"])
    finally:
        nav.close()
        nav.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_selected_icon_and_cell_border_in_real_window(qapp):
    from local_pdf_toolkit.app import build_registry
    from local_pdf_toolkit.ui.main_window import MainWindow

    window = MainWindow(build_registry())
    window.show()
    try:
        apply_theme(window, dark=True)
        window._set_sidebar_collapsed(True, remember=False)
        window.navigation.setCurrentRow(1)
        qapp.processEvents()
        nav = window.navigation
        rect = nav.visualItemRect(nav.item(1))
        image = nav.viewport().grab().toImage()
        ratio = image.devicePixelRatio()
        pixels = [
            image.pixelColor(x, y)
            for x in range(int(rect.left() * ratio), int(rect.right() * ratio))
            for y in range(int(rect.top() * ratio), int(rect.bottom() * ratio))
        ]
        assert any(p.red() > 220 and 130 < p.green() < 200 and p.blue() < 120 for p in pixels)
        assert any(p.red() >= 100 and p.green() >= 150 and p.blue() >= 210 for p in pixels)
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_selected_icon_oranges_contrast_with_selection_fills():
    def luminance(value):
        channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    for orange, colors in (("#a54600", LIGHT), ("#ffad59", DARK)):
        foreground, background = sorted((luminance(orange), luminance(colors["selection"])))
        assert (background + 0.05) / (foreground + 0.05) >= 3

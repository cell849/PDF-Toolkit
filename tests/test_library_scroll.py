"""Library scroll bounds track the cards currently displayed."""

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.main_window import MainWindow


def settle(qapp):
    for _ in range(12):
        qapp.processEvents()


def assert_scroll_bounds(window):
    library = window.library
    cards = [card for card in library.cards if card.isVisible()]
    scroll = window.library_scroll
    if cards:
        last_bottom = max(card.geometry().bottom() + 1 for card in cards)
        # A resizable scroll widget fills the viewport even with few cards.
        expected_height = max(last_bottom, scroll.viewport().height())
        assert abs(library.height() - expected_height) <= 2
    else:
        assert library.height() <= scroll.viewport().height() + 2


def test_library_scroll_tracks_filter_and_resize(qapp):
    window = MainWindow(build_registry())
    window.resize(760, 700)
    window.show()
    window._browse_tools("All tools")
    try:
        settle(qapp)
        assert_scroll_bounds(window)
        bar = window.library_scroll.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(bar.maximum())
        window._show_library()
        window._browse_tools("All tools")
        settle(qapp)
        assert bar.value() == 0
        bar.setValue(bar.maximum())
        window._browse_tools("Convert PDFs")
        settle(qapp)
        assert bar.value() == 0
        assert_scroll_bounds(window)
        window.search.setText("no such tool 12345")
        settle(qapp)
        assert_scroll_bounds(window)
        window.search.clear()
        window._browse_tools("All tools")
        for width in (1600, 760):
            window.resize(width, 700)
            settle(qapp)
            assert_scroll_bounds(window)
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.main_window import MainWindow


def test_application_registry_and_all_option_forms(qapp):
    registry = build_registry()
    operations = registry.list_operations()
    assert len(operations) >= 25
    assert registry.get("image.to_pdf").spec.input_mode == "multiple"
    assert registry.get("pdf.merge").spec.input_mode == "multiple"
    assert registry.get("pdf.to_docx")
    assert registry.get("office.to_pdf")
    window = MainWindow(registry)
    try:
        for index, spec in enumerate(operations):
            window.operation_list.setCurrentRow(index)
            assert set(window._editors) == {definition.name for definition in spec.options}
            values = {name: getter() for name, getter in window._editors.items()}
            assert values == {d.name: d.default for d in spec.options}
    finally:
        window.close()

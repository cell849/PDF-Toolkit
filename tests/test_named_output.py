import json
import os
import pickle
from pathlib import Path

import pytest

from local_pdf_toolkit.converters.named_output import NamedOutputConverter, normalize_base_name
from local_pdf_toolkit.core.contracts import CancellationToken, ConverterSpec, Progress
from local_pdf_toolkit.core.errors import ConversionError
from local_pdf_toolkit.core.formats import FileFormat


class OutputDouble:
    """Produce real disposable outputs while preserving the supplied source."""

    spec = ConverterSpec("test.named", "Named test", (FileFormat.TXT,), (FileFormat.PDF,))

    def __init__(self, outputs=("document.pdf",)):
        self.outputs = outputs
        self.directory = None

    def validate_input(self, path):
        return FileFormat.TXT

    def validate_options(self, options):
        return {"validated": True}

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.directory = Path(output_dir)
        assert self.directory.parent == Path(input_path).parent
        paths = []
        for name in self.outputs:
            path = self.directory / name
            path.write_bytes(
                b'{"policy":"Keep report bytes unchanged"}'
                if name.endswith(".json")
                else b"completed output"
            )
            paths.append(path)
        progress(Progress(1, 1))
        return tuple(paths)


def run(source, delegate, base_name="chosen", token=None):
    return NamedOutputConverter(delegate, base_name).convert(
        source, source.parent, {}, lambda _: None, token or CancellationToken()
    )


def test_named_output_is_picklable_forwards_contract_and_preserves_original(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"original source")
    delegate = OutputDouble()
    adapter = pickle.loads(pickle.dumps(NamedOutputConverter(delegate, "Chosen.PDF")))
    assert adapter.spec == delegate.spec
    assert adapter.validate_input(source) == FileFormat.TXT
    assert adapter.validate_options({}) == {"validated": True}
    (output,) = adapter.convert(source, tmp_path, {}, lambda _: None, CancellationToken())
    assert output.name == "Chosen.pdf"
    assert output.read_bytes() == b"completed output"
    assert source.read_bytes() == b"original source"
    assert not adapter.delegate.directory.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Chosen.pdf", "source.txt"]


def test_document_report_and_multiple_page_names_are_predictable(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original")
    document, report = run(source, OutputDouble(("random.pdf", "random.report.json")))
    assert (document.name, report.name) == ("chosen.pdf", "chosen.report.json")
    assert json.loads(report.read_bytes()) == {"policy": "Keep report bytes unchanged"}
    assert report.read_bytes() == b'{"policy":"Keep report bytes unchanged"}'
    pages = run(source, OutputDouble(("random-01.png", "random-02.png")), "pages")
    assert [path.name for path in pages] == ["pages-1.png", "pages-2.png"]


def test_existing_outputs_are_preserved_without_partial_publication(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original")
    existing = tmp_path / "chosen.report.json"
    existing.write_text("existing report")
    with pytest.raises(ConversionError, match="already exists") as error:
        run(source, OutputDouble(("random.pdf", "random.report.json")))
    assert error.value.code == "output_error"
    assert existing.read_text() == "existing report"
    assert not (tmp_path / "chosen.pdf").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["chosen.report.json", "source.txt"]


def test_mid_publish_failure_rolls_back_every_new_output(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("original")
    original_link = os.link

    def fail_second_publication(source_path, destination, *args, **kwargs):
        destination = Path(destination)
        if destination.parent == tmp_path and destination.name == "chosen-2.png":
            raise OSError("Simulated filesystem failure")
        return original_link(source_path, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", fail_second_publication)
    with pytest.raises(ConversionError, match="Cannot write"):
        run(source, OutputDouble(("one.png", "two.png")))
    assert [path.name for path in tmp_path.iterdir()] == ["source.txt"]


def test_cancel_during_publication_rolls_back_and_removes_temporary_outputs(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("original")
    token = CancellationToken()
    original_link = os.link

    def cancel_after_first_publication(source_path, destination, *args, **kwargs):
        result = original_link(source_path, destination, *args, **kwargs)
        if Path(destination).parent == tmp_path:
            token.cancel()
        return result

    monkeypatch.setattr(os, "link", cancel_after_first_publication)
    with pytest.raises(ConversionError) as error:
        run(source, OutputDouble(("one.png", "two.png")), token=token)
    assert error.value.code == "cancelled"
    assert [path.name for path in tmp_path.iterdir()] == ["source.txt"]


def test_cancellation_before_delegate_does_not_create_outputs(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original")
    token = CancellationToken()
    token.cancel()
    delegate = OutputDouble()
    with pytest.raises(ConversionError) as error:
        run(source, delegate, token=token)
    assert error.value.code == "cancelled" and delegate.directory is None
    assert [path.name for path in tmp_path.iterdir()] == ["source.txt"]


@pytest.mark.parametrize(
    "base_name",
    [
        "",
        "../escape",
        "folder/file",
        "folder\\file",
        "CON",
        "con.pdf",
        "NUL.txt",
        "COM1",
        "lpt9.other",
        "name.",
        "name ",
        " name",
        "line\nfeed",
        "bad:name",
        "a" * 201,
    ],
)
def test_invalid_windows_names_are_rejected(base_name):
    with pytest.raises(ConversionError) as error:
        NamedOutputConverter(OutputDouble(), base_name)
    assert error.value.code == "invalid_options"


def test_only_declared_extensions_are_normalized(tmp_path):
    assert normalize_base_name("Picture.JPG", (FileFormat.JPEG,)) == "Picture"
    assert normalize_base_name("Picture.tif", (FileFormat.TIFF,)) == "Picture"
    assert normalize_base_name("invoice.exe", (FileFormat.PDF,)) == "invoice.exe"
    source = tmp_path / "source.txt"
    source.write_text("original")
    (output,) = run(source, OutputDouble(), "invoice.exe")
    assert output.name == "invoice.exe.pdf"

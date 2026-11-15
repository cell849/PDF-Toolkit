import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from local_pdf_toolkit.converters.pptx_metadata import PKG, PptxMetadataConverter, R
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError

PRIVATE = "PrivateOwnerCanary7834"


def rewrite(path, transform):
    with zipfile.ZipFile(path) as source:
        parts = {n: source.read(n) for n in source.namelist()}
    transform(parts)
    with zipfile.ZipFile(path, "w") as target:
        target.comment = PRIVATE.encode()
        for name, data in parts.items():
            entry = zipfile.ZipInfo(name, (2025, 3, 4, 12, 0, 0))
            entry.comment = PRIVATE.encode()
            target.writestr(entry, data)


@pytest.fixture
def deck(tmp_path):
    path = tmp_path / f"{PRIVATE}.pptx"
    document = Presentation()
    document.core_properties.author = PRIVATE
    document.core_properties.last_modified_by = PRIVATE
    document.core_properties.title = PRIVATE
    slide = document.slides.add_slide(document.slide_layouts[6])
    shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    shape.name = PRIVATE
    shape.text = "Visible slide content"
    slide.notes_slide.notes_text_frame.text = PRIVATE
    image = Image.new("RGB", (12, 10), "red")
    exif = Image.Exif()
    exif[315] = PRIVATE
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    stream.seek(0)
    slide.shapes.add_picture(stream, Inches(1), Inches(3))
    document.save(path)

    def inject(parts):
        parts["ppt/theme/theme1.xml"] = parts["ppt/theme/theme1.xml"].replace(
            b"Office Theme", PRIVATE.encode()
        )
        parts["ppt/comments/comment1.xml"] = (
            f'<p:cmLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">{PRIVATE}</p:cmLst>'.encode()
        )
        parts["ppt/commentAuthors.xml"] = PRIVATE.encode()
        rel = etree.fromstring(parts["ppt/slides/_rels/slide1.xml.rels"])
        etree.SubElement(
            rel,
            f"{{{PKG}}}Relationship",
            Id="rIdPrivateComments",
            Type=R + "/comments",
            Target="../comments/comment1.xml",
        )
        parts["ppt/slides/_rels/slide1.xml.rels"] = etree.tostring(rel)

    rewrite(path, inject)
    return path


def clean(deck, tmp_path, token=None, progress=lambda _: None):
    return PptxMetadataConverter().convert(
        deck, tmp_path, {}, progress, token or CancellationToken()
    )


def test_clean_properties_notes_comments_media_and_zip_without_changing_visible_content(
    deck, tmp_path
):
    before = deck.read_bytes()
    result, report = clean(deck, tmp_path)
    assert deck.read_bytes() == before
    assert PRIVATE not in result.name
    presentation = Presentation(result)
    assert len(presentation.slides) == 1
    assert presentation.slides[0].shapes[0].text == "Visible slide content"
    assert presentation.slides[0].shapes[0].left == Inches(1)
    assert presentation.slides[0].shapes[0].width == Inches(5)
    with zipfile.ZipFile(result) as archive:
        assert not archive.comment
        for entry in archive.infolist():
            assert not entry.comment and not entry.extra
            assert entry.date_time == (1980, 1, 1, 0, 0, 0)
            assert not entry.filename.startswith(("docProps/", "ppt/notes", "ppt/comments"))
            data = archive.read(entry)
            if entry.filename.startswith("ppt/media/"):
                with Image.open(io.BytesIO(data)) as image:
                    assert not image.getexif()
            else:
                assert PRIVATE.encode() not in data
    summary = json.loads(report.read_text())
    assert summary["slides"] == 1 and summary["removed_parts"] > 0
    assert PRIVATE not in report.read_text()
    again, _ = clean(deck, tmp_path)
    assert again != result


@pytest.mark.parametrize(
    "name",
    [
        "ppt/embeddings/oleObject1.bin",
        "ppt/charts/chart1.xml",
        "ppt/media/image.svg",
        "customXml/item1.xml",
        "_xmlsignatures/sig1.xml",
    ],
)
def test_unknown_active_or_complex_parts_rejected(deck, tmp_path, name):
    rewrite(deck, lambda parts: parts.update({name: b"unsupported"}))
    with pytest.raises(ConversionError, match="unsupported parts"):
        clean(deck, tmp_path)
    assert list(tmp_path.iterdir()) == [deck]


def test_external_link_rejected(deck, tmp_path):
    def inject(parts):
        name = "ppt/slides/_rels/slide1.xml.rels"
        root = etree.fromstring(parts[name])
        etree.SubElement(
            root,
            f"{{{PKG}}}Relationship",
            Id="rIdExt",
            Type=R + "/hyperlink",
            Target="https://example.com/private",
            TargetMode="External",
        )
        parts[name] = etree.tostring(root)

    rewrite(deck, inject)
    with pytest.raises(ConversionError, match="External links"):
        clean(deck, tmp_path)
    assert list(tmp_path.iterdir()) == [deck]


def test_cancel_no_partial_presentation(deck, tmp_path):
    token = CancellationToken()
    with pytest.raises(ConversionCancelled):
        clean(deck, tmp_path, token, lambda _: token.cancel())
    assert list(tmp_path.iterdir()) == [deck]


def test_collision_never_overwrites(deck, tmp_path, monkeypatch):
    from local_pdf_toolkit.converters import pptx_metadata

    monkeypatch.setattr(pptx_metadata, "uuid4", lambda: SimpleNamespace(hex="0" * 32))
    existing = tmp_path / ("clean-presentation-" + "0" * 12 + ".pptx")
    existing.write_bytes(b"keep")
    with pytest.raises(ConversionError):
        clean(deck, tmp_path)
    assert existing.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_bad_zip_duplicate_and_xml_entities_are_rejected(deck, tmp_path):
    from local_pdf_toolkit.converters import pptx_metadata

    with pytest.raises(ConversionError):
        pptx_metadata._xml(b'<!DOCTYPE x [<!ENTITY e "private">]><x>&e;</x>')
    with zipfile.ZipFile(deck, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr("ppt/presentation.xml", b"bad")
    with pytest.raises(ConversionError, match="Duplicate"):
        clean(deck, tmp_path)
    unknown = tmp_path / "unsupported.doc"
    unknown.write_bytes(b"not PPTX")
    with pytest.raises(ConversionError):
        clean(unknown, tmp_path)


def test_media_filenames_relationship_ids_and_custom_show_labels_neutralized(deck, tmp_path):
    def inject(parts):
        old_name = next(name for name in parts if name.startswith("ppt/media/"))
        new_name = "ppt/media/" + PRIVATE + ".jpg"
        parts[new_name] = parts.pop(old_name)
        for name in list(parts):
            if name.endswith(".rels"):
                parts[name] = parts[name].replace(
                    Path(old_name).name.encode(), Path(new_name).name.encode()
                )
        source = "ppt/presentation.xml"
        tree = etree.fromstring(parts[source])
        namespace = tree.tag.split("}")[0] + "}"
        custom = etree.SubElement(tree, namespace + "custShowLst")
        etree.SubElement(custom, namespace + "custShow", name=PRIVATE, id="0")
        parts[source] = etree.tostring(tree)
        for name in list(parts):
            if name.endswith((".xml", ".rels")):
                parts[name] = parts[name].replace(b'="rId', b'="PrivateIdentifier')

    rewrite(deck, inject)
    result, report = clean(deck, tmp_path)
    with zipfile.ZipFile(result) as package:
        assert all(PRIVATE not in name for name in package.namelist())
        for name in package.namelist():
            if name.endswith((".xml", ".rels")):
                data = package.read(name)
                assert PRIVATE.encode() not in data and b"PrivateIdentifier" not in data
    assert PRIVATE not in report.read_text()

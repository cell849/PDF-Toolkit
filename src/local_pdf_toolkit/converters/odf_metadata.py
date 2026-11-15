"""Metadata removal for editable ODT/ODS/ODP with conservative embedded content."""

import io
import posixpath
import re
from uuid import uuid4

from lxml import etree
from PIL import Image

from local_pdf_toolkit.converters.image_metadata import clean_image_bytes
from local_pdf_toolkit.converters.metadata_package import (
    parse_xml_parts,
    publish_package,
    read_package,
    reject,
    translate_errors,
    xml_bytes,
)
from local_pdf_toolkit.converters.office_metadata import MEDIA_MIME
from local_pdf_toolkit.core.contracts import ConverterSpec, Progress
from local_pdf_toolkit.core.formats import FileFormat

OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
XLINK = "http://www.w3.org/1999/xlink"
MIMES = {
    FileFormat.ODT: "application/vnd.oasis.opendocument.text",
    FileFormat.ODS: "application/vnd.oasis.opendocument.spreadsheet",
    FileFormat.ODP: "application/vnd.oasis.opendocument.presentation",
}


def clean_odf(parts, token, progress):
    if not {"mimetype", "content.xml", "META-INF/manifest.xml"} <= parts.keys():
        reject("Not a supported OpenDocument package.")
    mime = parts["mimetype"].decode("ascii")
    kind = next((kind for kind, value in MIMES.items() if value == mime), None)
    if kind is None:
        reject("Only ODT/ODS/ODP are supported; templates and flat XML formats are not.")
    roots = parse_xml_parts(parts)
    manifest = roots["META-INF/manifest.xml"]
    if manifest.tag != "{" + MANIFEST + "}manifest" or any(
        etree.QName(e).localname == "encryption-data" for e in manifest.iter()
    ):
        reject("Encrypted or invalid OpenDocument manifests are unsupported.")
    if roots["content.xml"].tag != "{" + OFFICE + "}document-content":
        reject("Invalid OpenDocument content.")
    body = roots["content.xml"].find("{" + OFFICE + "}body")
    expected = {
        FileFormat.ODT: "text",
        FileFormat.ODS: "spreadsheet",
        FileFormat.ODP: "presentation",
    }[kind]
    if body is None or len(body) != 1 or body[0].tag != "{" + OFFICE + "}" + expected:
        reject("OpenDocument content does not match its declared type.")
    removed = {"meta.xml", "settings.xml", "manifest.rdf"}
    output, media, mime_map = {"mimetype": parts["mimetype"]}, {}, {}
    for name, data in parts.items():
        token.raise_if_cancelled()
        if name in removed or name.startswith(("Thumbnails/", "Configurations2/")):
            continue
        if name in ("mimetype", "content.xml", "styles.xml", "META-INF/manifest.xml"):
            continue
        if name.startswith("Pictures/"):
            cleaned = clean_image_bytes(data)
            with Image.open(io.BytesIO(cleaned)) as image:
                extension, image_mime = MEDIA_MIME[image.format]
            new_name = f"Pictures/image{len(media) + 1:04d}.{extension}"
            media[name] = new_name
            output[new_name] = cleaned
            mime_map[new_name] = image_mime
            continue
        reject(
            "Unsupported OpenDocument parts: objects, fonts, scripts, "
            "signatures or other attachments."
        )
    for name in ("content.xml", "styles.xml"):
        if name not in roots:
            continue
        root = roots[name]
        if name == "styles.xml" and root.tag != "{" + OFFICE + "}document-styles":
            reject("Invalid OpenDocument styles.")
        for element in list(root.iter()):
            if element is not root and root not in element.iterancestors():
                continue
            q = etree.QName(element)
            local, namespace = q.localname, q.namespace or ""
            if local in (
                "scripts",
                "event-listeners",
                "forms",
                "object",
                "object-ole",
                "plugin",
                "floating-frame",
                "dde-links",
                "dde-link",
            ) or local in ("dde-source", "script"):
                reject("Scripts, forms, linked or embedded objects are unsupported.")
            if local in (
                "annotation",
                "meta",
                "settings",
                "annotation-end",
                "tracked-changes",
                "change-start",
                "change-end",
                "change",
            ) or namespace in (
                "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
                "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
                "http://purl.org/dc/elements/1.1/",
            ):
                if element.getparent() is not None:
                    element.getparent().remove(element)
                continue
            if (
                namespace == "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
                and local in ("title", "desc")
            ):
                element.getparent().remove(element)
                continue
            if not (
                namespace.startswith("urn:oasis:names:tc:opendocument:xmlns:")
                or namespace in (XLINK, "http://www.w3.org/1998/Math/MathML")
            ):
                reject("Unsupported OpenDocument extension XML.")
            for key in list(element.attrib):
                attr = etree.QName(key)
                if attr.namespace and not (
                    attr.namespace.startswith("urn:oasis:names:tc:opendocument:xmlns:")
                    or attr.namespace in (XLINK, "http://www.w3.org/XML/1998/namespace")
                ):
                    reject("Unsupported extension attributes in OpenDocument content.")
                if attr.localname in ("protection-key", "protection-key-digest-algorithm") or (
                    attr.localname == "protected" and element.get(key) in ("true", "1")
                ):
                    reject("Protected OpenDocument content must be unprotected before cleaning.")
                if attr.localname in (
                    "creator",
                    "date",
                    "initial-creator",
                    "editing-cycles",
                    "editing-duration",
                ):
                    del element.attrib[key]
                elif attr.localname == "formula" and re.search(
                    r"(?:WEBSERVICE|HYPERLINK|DDE|RTD|IMAGE)\s*\(|https?://|file:",
                    element.get(key),
                    re.I,
                ):
                    reject("External spreadsheet formulas are unsupported.")
                elif key == "{" + XLINK + "}href":
                    target = element.get(key)
                    if target.startswith("#"):
                        continue
                    from urllib.parse import unquote

                    target = posixpath.normpath(unquote(target))
                    if target not in media:
                        reject("External/non-image links are unsupported; remove them first.")
                    element.set(key, media[target])
            if namespace == TEXT and local == "variable-set":
                reject("User variables may contain private values; review them before cleaning.")
        output[name] = xml_bytes(
            root,
            {
                "of": "urn:oasis:names:tc:opendocument:xmlns:of:1.2",
                "oooc": "http://openoffice.org/2004/calc",
            },
        )
        mime_map[name] = "text/xml"
        progress(Progress(1 if name == "content.xml" else 2, 2))
    index = etree.Element("{" + MANIFEST + "}manifest", nsmap={"manifest": MANIFEST})
    index.set("{" + MANIFEST + "}version", "1.2")
    for name, part_mime in [("/", mime), *sorted(mime_map.items())]:
        entry = etree.SubElement(index, "{" + MANIFEST + "}file-entry")
        entry.set("{" + MANIFEST + "}full-path", name)
        entry.set("{" + MANIFEST + "}media-type", part_mime)
    output["META-INF/manifest.xml"] = xml_bytes(index)
    return output, kind


class OdfMetadataConverter:
    spec = ConverterSpec(
        "metadata.clean_odf",
        "Clean OpenDocument metadata",
        tuple(MIMES),
        tuple(MIMES),
        limitations=(
            "Cleans ODT/ODS/ODP properties, comments, tracked-change history, view/settings "
            "data, thumbnails, ZIP fields and supported embedded-image metadata. Current "
            "document content and normal styles remain; change history is removed.",
            "Visible content, hidden content, style/object labels, named ranges and filesystem "
            "data can still identify people. Linked, active, protected, embedded-object or "
            "unsupported packages are rejected. Images are re-encoded; color may change.",
        ),
    )

    def validate_options(self, options):
        if options:
            reject("This cleaner has no options.")
        return {}

    @translate_errors
    def validate_input(self, path):
        parts = read_package(path)
        data = parts.get("mimetype", b"").decode("ascii")
        roots = parse_xml_parts(parts)
        if (
            "content.xml" not in roots
            or "META-INF/manifest.xml" not in roots
            or roots["content.xml"].tag != "{" + OFFICE + "}document-content"
        ):
            reject("Invalid OpenDocument structure.")
        for kind, mime in MIMES.items():
            if data == mime:
                return kind
        reject("Not an ODT/ODS/ODP package.")

    @translate_errors
    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.validate_options(options)
        cancel_token.raise_if_cancelled()
        parts, kind = clean_odf(read_package(input_path), cancel_token, progress)
        name = f"clean-office-{uuid4().hex[:12]}.{kind.value}"
        report = {
            "tool": self.spec.operation_id,
            "policy": "OpenDocument metadata/history removed; images rebuilt; ZIP fields reset.",
            "policy_categories": [
                "document properties",
                "comments/change history",
                "view settings",
                "thumbnails",
                "embedded image metadata",
                "ZIP fields",
            ],
            "limits": "Visible/hidden content, style/object labels and filesystem data remain. "
            "No anonymity guarantee. Unsupported packages are rejected.",
        }

        def verify(path):
            actual = read_package(path)
            if any(n in actual for n in ("meta.xml", "settings.xml", "manifest.rdf")):
                reject("Metadata parts remain.")
            # Structural validation of the actual written package, without encoding images again.
            roots = parse_xml_parts(actual)
            if roots["content.xml"].tag != "{" + OFFICE + "}document-content":
                reject("Output validation failed.")

        return publish_package(parts, output_dir, name, report, cancel_token, verify, MIMES[kind])

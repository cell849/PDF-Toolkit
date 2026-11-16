"""Conservative editable Word/Excel package cleaning with explicit exclusions."""

import io
import posixpath
import re
from pathlib import Path
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
from local_pdf_toolkit.converters.pptx_metadata import (
    CT,
    PKG,
    R,
    _source_for_relationship,
    _target,
)
from local_pdf_toolkit.core.contracts import ConverterSpec, Progress
from local_pdf_toolkit.core.formats import FileFormat

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
V = "urn:schemas-microsoft-com:vml"
X = "urn:schemas-microsoft-com:office:excel"
OO = "urn:schemas-microsoft-com:office:office"
NAMESPACES = {
    W,
    "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "http://schemas.microsoft.com/office/word/2010/wordml",
    S,
    A,
    WP,
    PIC,
    R,
    MC,
    "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "http://www.w3.org/XML/1998/namespace",
}
MEDIA_MIME = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "TIFF": ("tiff", "image/tiff"),
    "BMP": ("bmp", "image/bmp"),
    "GIF": ("gif", "image/gif"),
}
WORD_TYPES = {
    "document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "styles": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
    "settings": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
    "webSettings": "application/vnd.openxmlformats-officedocument.wordprocessingml.webSettings+xml",
    "fonts": "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
    "numbering": "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
    "footnotes": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
    "endnotes": "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
    "hdr": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
    "ftr": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
}
EXCEL_TYPES = {
    "workbook": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    "worksheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
    "styleSheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
    "sst": "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml",
    "wsDr": "application/vnd.openxmlformats-officedocument.drawing+xml",
}


def local_name(node):
    return etree.QName(node).localname


def clean_ooxml(parts, kind, token, progress):
    folder, main = ("word", "document") if kind == FileFormat.DOCX else ("xl", "workbook")
    main_name = f"{folder}/{main}.xml"
    if not {"[Content_Types].xml", "_rels/.rels", main_name} <= parts.keys():
        reject("The package does not match the selected Office format.")
    roots = parse_xml_parts(parts)
    if roots[main_name].tag != f"{{{W if folder == 'word' else S}}}{main}":
        reject("Only standard DOCX/XLSX packages are supported.")
    types = roots["[Content_Types].xml"]
    expected = WORD_TYPES["document"] if folder == "word" else EXCEL_TYPES["workbook"]
    if not any(
        e.get("PartName") == "/" + main_name and e.get("ContentType") == expected for e in types
    ):
        reject("Templates, macro-enabled and nonstandard Office packages are unsupported.")
    removed = set()
    comments_vml = set()
    for name, data in parts.items():
        token.raise_if_cancelled()
        if (
            name.startswith(("docProps/", "customXml/"))
            or re.fullmatch(r"word/(?:comments[^/]*|people)\.xml", name)
            or name.startswith(
                ("xl/comments/", "xl/threadedComments/", "xl/persons/", "xl/printerSettings/")
            )
            or name in ("xl/calcChain.xml", "word/stylesWithEffects.xml")
        ):
            removed.add(name)
            continue
        if name.endswith(".vml"):
            root = roots.get(name)
            if root is None:
                from local_pdf_toolkit.converters.pptx_metadata import _xml

                root = _xml(data)
            clients = root.findall(".//{" + X + "}ClientData")
            if not clients or any(c.get("ObjectType") != "Note" for c in clients):
                reject("Non-comment VML drawings are unsupported.")
            # Controls, pictures or unknown XML must not masquerade as comment VML.
            if any(etree.QName(e).namespace not in (None, V, X, OO) for e in root.iter()):
                reject("Unknown VML content is unsupported.")
            removed.add(name)
            comments_vml.add(name)
            continue
        if name in ("[Content_Types].xml", "_rels/.rels") or name.endswith(".rels"):
            continue
        word_path = re.fullmatch(
            r"word/(?:document|styles|stylesWithEffects|settings|webSettings|fontTable|numbering|footnotes|endnotes|header\d+|footer\d+)\.xml",
            name,
        )
        excel_path = re.fullmatch(
            r"xl/(?:workbook|styles|sharedStrings|worksheets/sheet\d+|drawings/drawing\d+)\.xml",
            name,
        )
        theme_path = re.fullmatch(r"(?:word|xl)/theme/theme\d+\.xml", name)
        if (
            (folder == "word" and word_path)
            or (folder == "xl" and excel_path)
            or (theme_path and name.startswith(folder + "/"))
        ):
            continue
        if name.startswith(folder + "/media/") and Path(name).suffix.lower() in (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".tif",
            ".tiff",
            ".bmp",
            ".gif",
        ):
            continue
        reject(
            "Unsupported Office parts: charts, SmartArt, objects, fonts, custom XML, "
            "macros, signatures or other media. No output was cleaned."
        )
    for name in parts:
        if name.endswith(".rels") and name != "_rels/.rels":
            source = _source_for_relationship(name)
            if source not in parts:
                reject("Relationship part has no owning document.")
            if source in removed:
                removed.add(name)
    media = {}
    data_out = {}
    for index, name in enumerate(sorted(n for n in parts if n.startswith(folder + "/media/")), 1):
        token.raise_if_cancelled()
        data = clean_image_bytes(parts[name])
        with Image.open(io.BytesIO(data)) as image:
            extension, _ = MEDIA_MIME[image.format]
        media[name] = f"{folder}/media/image{index:04d}.{extension}"
        data_out[media[name]] = data
    ids, dropped = {}, {}
    allowed_rel = {
        "officeDocument",
        "styles",
        "stylesWithEffects",
        "settings",
        "webSettings",
        "fontTable",
        "numbering",
        "footnotes",
        "endnotes",
        "header",
        "footer",
        "theme",
        "image",
        "hyperlink",
        "worksheet",
        "sharedStrings",
        "drawing",
    }
    for name, root in roots.items():
        if name in removed or not name.endswith(".rels"):
            continue
        if root.tag != f"{{{PKG}}}Relationships":
            reject("Invalid relationships XML.")
        source = _source_for_relationship(name)
        ids[source], dropped[source] = {}, set()
        clean_root = etree.Element(root.tag)
        seen = set()
        for relation in root:
            old = relation.get("Id")
            if not old or old in seen or relation.tag != f"{{{PKG}}}Relationship":
                reject("Invalid relationship identifier.")
            seen.add(old)
            if relation.get("TargetMode", "").lower() == "external":
                reject("External document links are unsupported; remove them first.")
            target = _target(source, relation.get("Target", ""))
            if target not in parts:
                reject("A document relationship points to a missing part.")
            if target in removed:
                dropped[source].add(old)
                continue
            relation_type = relation.get("Type", "")
            if (
                not relation_type.startswith(R + "/")
                or relation_type.rsplit("/", 1)[-1] not in allowed_rel
            ):
                reject("Unsupported Office relationship type.")
            new_id = "rId" + str(len(ids[source]) + 1)
            ids[source][old] = new_id
            etree.SubElement(
                clean_root,
                relation.tag,
                Id=new_id,
                Type=relation_type,
                Target=posixpath.relpath(
                    media.get(target, target), posixpath.dirname(source) or "."
                ),
            )
        data_out[name] = xml_bytes(clean_root)
    # Changes are accepted: deleted/moved-from text is dropped, inserted/moved-to
    # text kept. This is explicit in the UI policy; originals remain unchanged.
    deleted = {
        "del",
        "moveFrom",
        "pPrChange",
        "rPrChange",
        "sectPrChange",
        "tblPrChange",
        "tblGridChange",
        "trPrChange",
        "tcPrChange",
        "numberingChange",
        "cellDel",
        "cellIns",
        "cellMerge",
        "commentRangeStart",
        "commentRangeEnd",
        "commentReference",
        "proofErr",
        "rsids",
        "docVars",
        "mailMerge",
        "attachedTemplate",
        "trackRevisions",
        "fileSharing",
        "fileVersion",
    }
    revision_wrappers = {"ins", "moveTo"}
    for count, (name, root) in enumerate(roots.items(), 1):
        if name in removed or name.endswith(".rels") or name == "[Content_Types].xml":
            continue
        token.raise_if_cancelled()
        for element in list(root.iter()):
            if element is not root and root not in element.iterancestors():
                continue
            local = local_name(element)
            ns = etree.QName(element).namespace
            if local in ("docId", "shapeDefaults"):
                if element.getparent() is not None:
                    element.getparent().remove(element)
                    continue
            if ns == W and (
                (
                    local in ("del", "ins")
                    and element.getparent() is not None
                    and local_name(element.getparent()) == "trPr"
                )
                or local in ("cellDel", "cellIns", "cellMerge")
            ):
                reject("Accept table-structure revisions in Word before cleaning this document.")
            if ns == W and local in ("documentProtection", "writeProtection"):
                reject("Protected Word documents must be unprotected before cleaning.")
            if (
                ns == W
                and local in ("vanish", "webHidden")
                and element.get("{" + W + "}val", "1") not in ("0", "false")
            ):
                reject("Hidden Word text must be reviewed or removed before cleaning.")
            if (
                ns == S
                and local in ("row", "col", "definedName")
                and element.get("hidden", "0") in ("1", "true")
            ):
                reject("Hidden Excel rows, columns or names must be reviewed before cleaning.")
            if ns == W and local.startswith(
                ("moveFromRange", "moveToRange", "customXmlInsRange", "customXmlDelRange")
            ):
                element.getparent().remove(element)
                continue
            if ns == MC and local == "AlternateContent":
                reject("Office compatibility/alternate-content blocks are unsupported.")
            if ns == W and local in ("dataBinding", "sdt"):
                reject("Content controls/data-bound content must be detached before cleaning.")
            element.attrib.pop("{" + MC + "}Ignorable", None)
            if ns not in NAMESPACES:
                if local == "extLst":
                    element.getparent().remove(element)
                    continue
                reject("Unsupported extension XML in Office content.")
            if (ns == W and local in deleted) or (
                ns == S and local in {"fileSharing", "fileVersion"}
            ):
                element.getparent().remove(element)
                continue
            if local in {"extLst", "custDataLst"}:
                element.getparent().remove(element)
                continue
            if ns == W and local in revision_wrappers:
                parent = element.getparent()
                index = parent.index(element)
                for child in list(element):
                    parent.insert(index, child)
                    index += 1
                parent.remove(element)
                continue
            if local in ("workbookProtection", "sheetProtection"):
                private_hash = any(
                    "password" in key.lower()
                    or "hashvalue" in key.lower()
                    or "saltvalue" in key.lower()
                    for key in element.attrib
                )
                locks = (
                    ("sheet",)
                    if local == "sheetProtection"
                    else ("lockStructure", "lockWindows", "lockRevision")
                )
                if private_hash or any(
                    element.get(key, "0").lower() in ("1", "true") for key in locks
                ):
                    reject("Protected worksheets/workbooks must be unprotected before cleaning.")
                element.getparent().remove(element)
                continue
            if ns == S and local == "sheet" and element.get("state", "visible") != "visible":
                reject("Hidden worksheets are unsupported; review or remove them first.")
            if (
                ns == S
                and local in ("f", "definedName")
                and re.search(
                    r"(?:WEBSERVICE|HYPERLINK|RTD|DDE|IMAGE)\s*\(|\[", element.text or "", re.I
                )
            ):
                reject("External spreadsheet formulas are unsupported.")
            if ns == W and local in ("instrText", "fldSimple"):
                instruction = (
                    element.get("{" + W + "}instr", "")
                    if local == "fldSimple"
                    else element.text or ""
                )
                if instruction.strip().split(" ")[0].upper() not in (
                    "PAGE",
                    "NUMPAGES",
                    "SECTIONPAGES",
                ):
                    reject("Only page-number Word fields are supported by the cleaner.")
            for attribute in list(element.attrib):
                attr_local = etree.QName(attribute).localname
                if (
                    attr_local.startswith("rsid")
                    or attr_local
                    in (
                        "author",
                        "date",
                        "initials",
                        "descr",
                        "title",
                        "tooltip",
                        "userName",
                        "userId",
                    )
                    or attr_local in ("paraId", "textId", "durableId")
                ):
                    del element.attrib[attribute]
                elif etree.QName(attribute).namespace not in NAMESPACES | {None}:
                    reject("Unsupported extension attributes in Office content.")
            if local in ("docPr", "cNvPr"):
                element.set("name", "Object " + element.get("id", "0"))
            if local in ("theme", "clrScheme", "fontScheme", "fmtScheme"):
                element.set("name", "Clean theme")
            for attribute in ("id", "embed", "link"):
                key = "{" + R + "}" + attribute
                if key in element.attrib:
                    old = element.get(key)
                    if old in dropped.get(name, set()):
                        # legacyDrawing (comment-only VML), print settings, etc.
                        element.getparent().remove(element)
                        break
                    if old not in ids.get(name, {}):
                        reject("Unresolved Office relationship reference.")
                    element.set(key, ids[name][old])
        data_out[name] = xml_bytes(root)
        progress(Progress(count, len(roots)))
    index = etree.Element("{" + CT + "}Types")
    etree.SubElement(
        index,
        "{" + CT + "}Default",
        Extension="rels",
        ContentType="application/vnd.openxmlformats-package.relationships+xml",
    )
    etree.SubElement(index, "{" + CT + "}Default", Extension="xml", ContentType="application/xml")
    for name, data in data_out.items():
        if "/media/" in name:
            with Image.open(io.BytesIO(data)) as image:
                extension, mime = MEDIA_MIME[image.format]
            if not any(e.get("Extension") == extension for e in index):
                etree.SubElement(
                    index, "{" + CT + "}Default", Extension=extension, ContentType=mime
                )
        elif name.endswith(".xml"):
            root = roots[name]
            local = local_name(root)
            if "/theme/" in name:
                mime = "application/vnd.openxmlformats-officedocument.theme+xml"
            else:
                mime = (WORD_TYPES if folder == "word" else EXCEL_TYPES).get(local)
                if mime is None:
                    reject("Unsupported Office content root.")
            etree.SubElement(index, "{" + CT + "}Override", PartName="/" + name, ContentType=mime)
    data_out["[Content_Types].xml"] = xml_bytes(index)
    return data_out


class OfficeMetadataConverter:
    def __init__(self, kind):
        self.kind = kind
        self.spec = ConverterSpec(
            "metadata.clean_" + kind.value,
            "Clean Word metadata (DOCX)"
            if kind == FileFormat.DOCX
            else "Clean Excel metadata (XLSX)",
            (kind,),
            (kind,),
            limitations=(
                "Removes document properties, comments/reviewer records, revision metadata, ZIP "
                "fields and supported embedded-image metadata. "
                + (
                    "Ordinary Word text revisions are accepted "
                    "(deleted text removed, inserted text kept). "
                    "Table-structure revisions and content controls are rejected."
                    if kind == FileFormat.DOCX
                    else "Visible Excel cells, formulas and normal formatting remain."
                ),
                "Visible text/cells, headers/footers, style names, sheet names and named ranges "
                "can still identify people. This is not anonymization. Complex/active/linked "
                "packages, protected or hidden sheets and unsupported media are rejected.",
                "Images are re-encoded; JPEG quality/ICC color and advanced effects may change.",
            ),
        )

    def validate_options(self, options):
        if options:
            reject("This cleaner has no conversion options.")
        return {}

    @translate_errors
    def validate_input(self, path):
        parts = read_package(path)
        main = "word/document.xml" if self.kind == FileFormat.DOCX else "xl/workbook.xml"
        if main not in parts or "[Content_Types].xml" not in parts:
            reject("File does not match this Office tool.")
        from local_pdf_toolkit.converters.pptx_metadata import _xml

        expected = "{" + W + "}document" if self.kind == FileFormat.DOCX else "{" + S + "}workbook"
        if _xml(parts[main]).tag != expected:
            reject("Office XML root does not match the selected format.")
        _xml(parts["[Content_Types].xml"])
        return self.kind

    @translate_errors
    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.validate_options(options)
        cancel_token.raise_if_cancelled()
        parts = clean_ooxml(read_package(input_path), self.kind, cancel_token, progress)
        name = f"clean-office-{uuid4().hex[:12]}.{self.kind.value}"
        report = {
            "tool": self.spec.operation_id,
            "policy": "Office package cleaned; Word revisions accepted; images rebuilt.",
            "policy_categories": [
                "document properties",
                "comments/reviewers",
                "revision identifiers",
                "ZIP fields",
                "embedded image metadata",
                "relationship/media labels",
            ],
            "limits": "Visible content, style/sheet/bookmark labels, named ranges, "
            "headers/footers and "
            "filesystem data remain. Not an anonymity certificate.",
        }

        def verify(path):
            if self.kind == FileFormat.DOCX:
                from docx import Document

                Document(path)
            else:
                from openpyxl import load_workbook

                book = load_workbook(path, data_only=False)
                book.close()

        return publish_package(parts, output_dir, name, report, cancel_token, verify)

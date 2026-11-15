"""Format identifiers, not a file-verification implementation.

Adapters must verify content with signatures and parsers in validate_input().
Extensions alone never establish that a file is valid or supported.
"""

from enum import StrEnum


class FileFormat(StrEnum):
    PDF = "pdf"
    JPEG = "jpeg"
    PNG = "png"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    ODT = "odt"
    ODS = "ods"
    ODP = "odp"
    RTF = "rtf"
    TXT = "txt"
    HTML = "html"
    CSV = "csv"
    EPUB = "epub"
    WEBP = "webp"
    TIFF = "tiff"
    BMP = "bmp"
    GIF = "gif"
    MARKDOWN = "md"
    JSON = "json"
    AVIF = "avif"
    HEIC = "heic"
    MP4 = "mp4"
    MOV = "mov"
    MKV = "mkv"
    WEBM = "webm"
    AVI = "avi"
    MP3 = "mp3"
    M4A = "m4a"
    WAV = "wav"
    FLAC = "flac"
    OGG = "ogg"
    AAC = "aac"

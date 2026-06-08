from pathlib import Path
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile, is_zipfile

from fastapi import HTTPException, UploadFile

from .document_utils import safe_filename

MAX_FILENAME_CHARS = 180
TEXT_LIKE_EXTENSIONS = {".txt", ".md", ".markdown", ".csv"}
ZIP_OFFICE_MARKERS = {
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml",
    ".xlsx": "xl/workbook.xml",
}


def _stream_position(stream: BinaryIO) -> int:
    try:
        return stream.tell()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="上传文件流不可读取") from exc


def _reset_stream(stream: BinaryIO, position: int = 0) -> None:
    try:
        stream.seek(position)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="上传文件流不可复位") from exc


def _read_head(stream: BinaryIO, size: int = 4096) -> bytes:
    position = _stream_position(stream)
    try:
        return stream.read(size) or b""
    finally:
        _reset_stream(stream, position)


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    # Allow empty text uploads to pass this low-level check; document parsing will decide usefulness.
    if not head:
        return True
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            head.decode("gb18030")
            return True
        except UnicodeDecodeError:
            return False


def _validate_zip_office(stream: BinaryIO, ext: str) -> None:
    position = _stream_position(stream)
    try:
        if not is_zipfile(stream):
            raise HTTPException(status_code=400, detail="Office 文件内容与扩展名不匹配")
        _reset_stream(stream, position)
        marker = ZIP_OFFICE_MARKERS[ext]
        with ZipFile(stream) as zf:
            names = set(zf.namelist())
            if marker not in names:
                raise HTTPException(status_code=400, detail="Office 文件结构不完整或类型不匹配")
    except BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Office 文件不是有效的 ZIP/OpenXML 文件") from exc
    finally:
        _reset_stream(stream, position)


def validate_upload_file(file: UploadFile, allowed: set[str], detail: str) -> tuple[str, str]:
    filename = safe_filename(file.filename or "attachment")
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="文件名无效")
    if len(filename) > MAX_FILENAME_CHARS:
        raise HTTPException(status_code=400, detail=f"文件名不能超过 {MAX_FILENAME_CHARS} 个字符")
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=detail)

    head = _read_head(file.file)
    if ext == ".pdf" and not head.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="PDF 文件内容与扩展名不匹配")
    if ext == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="PNG 文件内容与扩展名不匹配")
    if ext in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="JPG 文件内容与扩展名不匹配")
    if ext == ".gif" and not (head.startswith(b"GIF87a") or head.startswith(b"GIF89a")):
        raise HTTPException(status_code=400, detail="GIF 文件内容与扩展名不匹配")
    if ext == ".webp" and not (head.startswith(b"RIFF") and head[8:12] == b"WEBP"):
        raise HTTPException(status_code=400, detail="WEBP 文件内容与扩展名不匹配")
    if ext in ZIP_OFFICE_MARKERS:
        _validate_zip_office(file.file, ext)
    if ext in TEXT_LIKE_EXTENSIONS and not _looks_like_text(head):
        raise HTTPException(status_code=400, detail="文本文件编码或内容无效")

    _reset_stream(file.file, 0)
    return filename, ext

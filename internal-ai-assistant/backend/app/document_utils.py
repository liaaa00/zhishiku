import csv
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import List, Tuple

from pypdf import PdfReader


PageText = Tuple[int | None, str]


def extract_pdf_text(file_path: str) -> List[Tuple[int, str]]:
    reader = PdfReader(file_path)
    pages = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append((idx, text))
    return pages


def read_text_file(file_path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return file_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本文件编码无法识别，请使用 UTF-8 或 GB18030 文本。")


def _xml_text(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""
    parts: list[str] = []
    for elem in root.iter():
        if elem.text:
            parts.append(elem.text)
    return " ".join(p.strip() for p in parts if p and p.strip())


def _slide_number(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _extract_openxml_slides(zf: zipfile.ZipFile) -> List[PageText]:
    names = zf.namelist()
    slide_files = sorted(
        (n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
        key=_slide_number,
    )
    pages: list[PageText] = []
    for idx, name in enumerate(slide_files, start=1):
        try:
            root = ET.fromstring(zf.read(name))
        except ET.ParseError:
            continue
        parts: list[str] = []
        for elem in root.iter():
            if elem.text:
                text = elem.text.strip()
                if text:
                    parts.append(text)
        if parts:
            pages.append((idx, " ".join(parts)))
    return pages


def extract_docx_text(file_path: str) -> List[PageText]:
    """Extract text from modern Word .docx files using the OpenXML zip structure."""
    path = Path(file_path)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        doc_parts = [n for n in names if n.startswith("word/") and n.endswith(".xml") and (n == "word/document.xml" or n.startswith("word/header") or n.startswith("word/footer"))]
        texts = []
        for name in sorted(doc_parts):
            text = _xml_text(zf.read(name))
            if text:
                label = "正文" if name == "word/document.xml" else Path(name).stem
                texts.append(f"[{label}] {text}")
    return [(None, "\n".join(texts))]


def extract_pptx_text(file_path: str) -> List[PageText]:
    """Extract visible text from modern PowerPoint .pptx files."""
    path = Path(file_path)
    with zipfile.ZipFile(path) as zf:
        pages = _extract_openxml_slides(zf)
        if pages:
            return pages
        # Fallback: extract any text runs from slide notes or masters if slides are empty.
        fallback_parts: list[str] = []
        for name in sorted(n for n in zf.namelist() if n.startswith("ppt/" ) and n.endswith(".xml")):
            text = _xml_text(zf.read(name))
            if text:
                fallback_parts.append(f"[{Path(name).stem}] {text}")
        if fallback_parts:
            return [(None, "\n".join(fallback_parts))]
    return []


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except ET.ParseError:
        return []
    values = []
    for si in root:
        values.append(" ".join(t.text or "" for t in si.iter() if t.tag.endswith("}t") or t.tag == "t").strip())
    return values


def _xlsx_sheet_names(zf: zipfile.ZipFile) -> dict[str, str]:
    names: dict[str, str] = {}
    if "xl/workbook.xml" not in zf.namelist():
        return names
    try:
        root = ET.fromstring(zf.read("xl/workbook.xml"))
    except ET.ParseError:
        return names
    for idx, sheet in enumerate([e for e in root.iter() if e.tag.endswith("}sheet") or e.tag == "sheet"], start=1):
        names[f"xl/worksheets/sheet{idx}.xml"] = sheet.attrib.get("name") or f"Sheet{idx}"
    return names


def _cell_text(cell, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    values = [v.text or "" for v in cell.iter() if v.tag.endswith("}v") or v.tag == "v"]
    inline = [t.text or "" for t in cell.iter() if t.tag.endswith("}t") or t.tag == "t"]
    if inline:
        return "".join(inline).strip()
    if not values:
        return ""
    raw = values[0]
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except Exception:
            return raw
    return raw


def extract_xlsx_text(file_path: str) -> List[PageText]:
    """Extract visible cell values from modern Excel .xlsx files."""
    pages: list[PageText] = []
    with zipfile.ZipFile(file_path) as zf:
        shared = _xlsx_shared_strings(zf)
        sheet_names = _xlsx_sheet_names(zf)
        sheet_files = sorted(n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for idx, name in enumerate(sheet_files, start=1):
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError:
                continue
            lines = []
            for row in [e for e in root.iter() if e.tag.endswith("}row") or e.tag == "row"]:
                cells = []
                for cell in [e for e in row if e.tag.endswith("}c") or e.tag == "c"]:
                    value = _cell_text(cell, shared)
                    if value:
                        ref = cell.attrib.get("r", "")
                        cells.append(f"{ref}: {value}" if ref else value)
                if cells:
                    lines.append(" | ".join(cells))
            if lines:
                title = sheet_names.get(name, f"Sheet{idx}")
                pages.append((idx, f"[{title}]\n" + "\n".join(lines)))
    return pages


def extract_csv_text(file_path: str) -> List[PageText]:
    path = Path(file_path)
    text = read_text_file(path)
    rows = []
    try:
        dialect = csv.Sniffer().sniff(text[:4096]) if text.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(text.splitlines(), dialect)
    for idx, row in enumerate(reader, start=1):
        if any(cell.strip() for cell in row):
            rows.append(f"Row {idx}: " + " | ".join(cell.strip() for cell in row))
    return [(None, "\n".join(rows))]


def extract_supported_document(file_path: str) -> List[PageText]:
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf_text(str(path))
    if ext == ".docx":
        return extract_docx_text(str(path))
    if ext == ".pptx":
        return extract_pptx_text(str(path))
    if ext == ".xlsx":
        return extract_xlsx_text(str(path))
    if ext == ".csv":
        return extract_csv_text(str(path))
    if ext in {".txt", ".md", ".markdown"}:
        return [(None, read_text_file(path))]
    raise ValueError("不支持的文件类型")


def chunk_text(text: str, max_chars: int = 1000, overlap: int = 150) -> List[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def safe_filename(filename: str) -> str:
    return Path(filename).name

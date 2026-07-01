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


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref or "")
    if not letters:
        return 0
    value = 0
    for ch in letters.group(0):
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


XlsxRow = tuple[int, dict[int, str]]


def _row_number(row, fallback: int) -> int:
    raw = str(row.attrib.get("r") or "").strip()
    return int(raw) if raw.isdigit() else fallback


def _xlsx_rows(root, shared: list[str]) -> list[XlsxRow]:
    rows: list[XlsxRow] = []
    fallback_row_number = 0
    for row in [e for e in root.iter() if e.tag.endswith("}row") or e.tag == "row"]:
        fallback_row_number += 1
        values: dict[int, str] = {}
        for cell in [e for e in row if e.tag.endswith("}c") or e.tag == "c"]:
            value = _cell_text(cell, shared)
            if value:
                col = _column_index(cell.attrib.get("r", ""))
                if col:
                    values[col] = value
        if values:
            rows.append((_row_number(row, fallback_row_number), values))
    return rows


def _header_start_index(rows: list[XlsxRow]) -> int:
    for idx, (_row_number_value, row) in enumerate(rows[:8]):
        next_row = rows[idx + 1][1] if idx + 1 < len(rows) else {}
        # Skip document titles or instruction rows before the real table header.
        if len(row) <= 1 and len(next_row) >= 2:
            continue
        if len(row) >= 2:
            return idx
    return 0


def _should_use_second_header_row(header1: dict[int, str], header2: dict[int, str]) -> bool:
    if not header1 or not header2:
        return False
    first_cols = len(header1)
    second_cols = len(header2)
    if first_cols <= 1:
        return False
    max_col = max([*header1.keys(), *header2.keys()] or [0])
    if not max_col:
        return False
    first_density = first_cols / max_col
    second_density = second_cols / max_col
    # Use a second header row only when the first row looks like grouped headers.
    # A normal sheet with one header row followed by data should keep the first data row.
    return first_cols < second_cols and first_density < 0.75 and second_density >= 0.5


def _table_headers(rows: list[XlsxRow]) -> tuple[dict[int, str], int]:
    if not rows:
        return {}, 0
    header_start = _header_start_index(rows)
    header1 = rows[header_start][1]
    header2 = rows[header_start + 1][1] if len(rows) > header_start + 1 else {}
    use_second_header = _should_use_second_header_row(header1, header2)
    max_col = max([*header1.keys(), *(header2.keys() if use_second_header else [])] or [0])
    headers: dict[int, str] = {}
    active_group = ""
    for col in range(1, max_col + 1):
        top = _normalize_header(header1.get(col, ""))
        sub = _normalize_header(header2.get(col, "")) if use_second_header else ""
        if top:
            active_group = top
        if use_second_header and sub and active_group and sub != active_group:
            headers[col] = f"{active_group}-{sub}"
        else:
            headers[col] = top or sub or f"列{col}"
    data_start = header_start + (2 if use_second_header else 1)
    return headers, data_start


def _format_table_row(sheet_title: str, row_number: int, row: dict[int, str], headers: dict[int, str]) -> str:
    cells = []
    for col in sorted(row):
        header = headers.get(col, f"列{col}")
        value = str(row[col]).strip()
        if value:
            cells.append(f"{header}={value}")
    return f"表格行 | 工作表={sheet_title} | Excel行={row_number} | " + " | ".join(cells)


def extract_xlsx_text(file_path: str) -> List[PageText]:
    """Extract visible cell values from modern Excel .xlsx files as row-oriented records."""
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
            rows = _xlsx_rows(root, shared)
            if not rows:
                continue
            title = sheet_names.get(name, f"Sheet{idx}")
            headers, data_start = _table_headers(rows)
            header_line = "表头 | " + " | ".join(f"列{col}={header}" for col, header in sorted(headers.items()))
            lines = [f"[{title}]", header_line]
            for row_number, row in rows[data_start:]:
                lines.append(_format_table_row(title, row_number, row, headers))
            pages.append((idx, "\n".join(lines)))
    return pages


def extract_csv_text(file_path: str) -> List[PageText]:
    path = Path(file_path)
    text = read_text_file(path)
    rows = []
    try:
        dialect = csv.Sniffer().sniff(text[:4096]) if text.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = list(csv.reader(text.splitlines(), dialect))
    header = [_normalize_header(cell) or f"列{idx}" for idx, cell in enumerate(reader[0], start=1)] if reader else []
    if header:
        rows.append("表头 | " + " | ".join(f"列{idx}={name}" for idx, name in enumerate(header, start=1)))
    for idx, row in enumerate(reader[1:] if header else reader, start=2 if header else 1):
        if any(cell.strip() for cell in row):
            fields = []
            for col_idx, cell in enumerate(row, start=1):
                value = cell.strip()
                if value:
                    fields.append(f"{header[col_idx - 1] if col_idx <= len(header) else f'列{col_idx}'}={value}")
            rows.append(f"表格行 | CSV行={idx} | " + " | ".join(fields))
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


def _chunk_table_text(text: str, max_chars: int = 1800) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    header_lines = [line for line in lines[:3] if line.startswith("[") or line.startswith("表头")]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        prefix = [] if not chunks and not current else header_lines
        prefix_len = sum(len(item) + 1 for item in prefix)
        line_len = len(line) + 1
        if current and current_len + prefix_len + line_len > max_chars:
            chunks.append("\n".join(prefix + current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join((header_lines if chunks else []) + current))
    return chunks


def chunk_text(text: str, max_chars: int = 1000, overlap: int = 150) -> List[str]:
    raw_text = text.strip()
    if not raw_text:
        return []
    if "\n" in raw_text and ("表格行" in raw_text or "表头" in raw_text or raw_text.startswith("[")):
        return _chunk_table_text(raw_text)
    text = " ".join(raw_text.split())
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

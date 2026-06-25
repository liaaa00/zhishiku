import json
import re
from typing import Iterable

from sqlalchemy.orm import Session

from .models import Document, DocumentTableRow
from .routers.deps import new_id


def _clean(value: str) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def _row_key(sheet_name: str, row_number: int | None, row: dict[str, str]) -> str:
    for key in ("序号", "编号", "工号", "省份", "城市", "姓名", "单位名称", "开设公司名称"):
        value = _clean(row.get(key, ""))
        if value:
            return f"{sheet_name}:{row_number or 0}:{key}={value}"
    if row_number is not None:
        return f"{sheet_name}:{row_number}"
    return f"{sheet_name}:{json.dumps(row, ensure_ascii=False, sort_keys=True)}"


def _split_line_kv(line: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in [item.strip() for item in line.split("|") if item.strip()]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = _clean(key)
        value = _clean(value)
        if key and value and key not in {"表格行", "表头"}:
            result[key] = value
    return result


def _parse_table_line(line: str, current_sheet: str = "") -> tuple[str, int | None, dict[str, str], bool] | None:
    line = line.strip()
    if not line or (not line.startswith("表头") and not line.startswith("表格行")):
        return None
    is_header = line.startswith("表头")
    row = _split_line_kv(line)
    if not row:
        return None
    sheet_name = current_sheet or _clean(row.get("工作表", "")) or "Sheet1"
    row_number: int | None = None
    match = re.search(r"Excel行=(\d+)", line)
    if match:
        row_number = int(match.group(1))
    csv_match = re.search(r"CSV行=(\d+)", line)
    if csv_match:
        row_number = int(csv_match.group(1))
    row.pop("工作表", None)
    row.pop("Excel行", None)
    row.pop("CSV行", None)
    return sheet_name, row_number, row, is_header


def _make_table_row_dict(document: Document, sheet_name: str, row_number: int | None, row: dict[str, str], row_text: str, is_header: bool, source_index: int) -> dict:
    return {
        "id": new_id(),
        "document_id": document.id,
        "sheet_name": sheet_name,
        "row_number": row_number,
        "row_key": _row_key(sheet_name, row_number, row),
        "row_json": json.dumps(row, ensure_ascii=False),
        "row_text": row_text,
        "is_header": is_header,
        "source_chunk_index": source_index,
    }


def extract_table_rows(pages: Iterable[tuple[int | None, str]], document: Document) -> list[dict]:
    rows: list[dict] = []
    source_index = 0
    for _page_number, text in pages:
        if not text or ("表格行" not in text and "表头" not in text):
            continue
        current_sheet = ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                current_sheet = line.strip("[]") or current_sheet
                continue
            parsed = _parse_table_line(line, current_sheet)
            if not parsed:
                continue
            sheet_name, row_number, row, is_header = parsed
            rows.append(_make_table_row_dict(document, sheet_name, row_number, row, _clean(line), is_header, source_index))
            source_index += 1
    return rows


def replace_document_table_rows(db: Session, document: Document, pages: Iterable[tuple[int | None, str]]) -> int:
    rows = extract_table_rows(pages, document)
    db.query(DocumentTableRow).filter(DocumentTableRow.document_id == document.id).delete()
    if not rows:
        db.flush()
        return 0
    db.add_all(DocumentTableRow(**row) for row in rows)
    db.flush()
    return len(rows)

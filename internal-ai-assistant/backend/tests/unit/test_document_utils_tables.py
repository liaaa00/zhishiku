from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.document_utils import extract_xlsx_text
from app.models import Document
from app.table_rows import extract_table_rows


def _write_minimal_xlsx(path: Path, sheet_rows: list[list[str]]) -> None:
    def cell_ref(col_index: int, row_index: int) -> str:
        letters = ""
        value = col_index
        while value:
            value, remainder = divmod(value - 1, 26)
            letters = chr(ord("A") + remainder) + letters
        return f"{letters}{row_index}"

    row_xml = []
    for row_index, values in enumerate(sheet_rows, start=1):
        cells = []
        for col_index, value in enumerate(values, start=1):
            if value == "":
                continue
            ref = cell_ref(col_index, row_index)
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
        if cells:
            row_xml.append(f'<row r="{row_index}">' + "".join(cells) + "</row>")

    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {rows}
  </sheetData>
</worksheet>
""".format(rows="\n".join(row_xml))
    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets><sheet name="网点清单" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>
</workbook>
"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def _rows_from_xlsx(path: Path) -> list[dict[str, str]]:
    pages = extract_xlsx_text(str(path))
    document = Document(id="doc-xlsx", title="xlsx", filename=path.name, storage_path=str(path), source_type="xlsx")
    rows = extract_table_rows(pages, document)
    return [json.loads(row["row_json"]) for row in rows if not row["is_header"]]


def test_xlsx_single_header_keeps_first_data_row(tmp_path: Path) -> None:
    path = tmp_path / "single_header.xlsx"
    _write_minimal_xlsx(
        path,
        [
            ["城市", "公司名称", "状态"],
            ["上海", "上海示例有限公司", "已开通"],
            ["杭州", "杭州示例有限公司", "筹备中"],
        ],
    )

    rows = _rows_from_xlsx(path)

    assert rows == [
        {"城市": "上海", "公司名称": "上海示例有限公司", "状态": "已开通"},
        {"城市": "杭州", "公司名称": "杭州示例有限公司", "状态": "筹备中"},
    ]


def test_xlsx_title_row_is_skipped_before_table_header(tmp_path: Path) -> None:
    path = tmp_path / "title_header.xlsx"
    _write_minimal_xlsx(
        path,
        [
            ["2026 年网点开通清单"],
            ["城市", "公司名称", "状态"],
            ["宁波", "宁波示例有限公司", "已开通"],
        ],
    )

    rows = _rows_from_xlsx(path)

    assert rows == [{"城市": "宁波", "公司名称": "宁波示例有限公司", "状态": "已开通"}]

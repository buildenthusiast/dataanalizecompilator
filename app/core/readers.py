"""Четене на таблици (.xlsx, .xlsm, .xls, .ods) като решетка от стойности.

Резултатът е dict: име на лист -> списък от редове, всеки ред е списък от стойности.
Индексите са 0-базирани (ред 0 = ред 1 в Excel).
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

Grid = dict[str, list[list]]

SUPPORTED_EXT = {".xlsx", ".xlsm", ".xls", ".ods"}

_NUM_RE = re.compile(r"^[+-]?(\d{1,3}([  ]\d{3})+|\d+)([.,]\d+)?$")


def to_number(v):
    """Връща число или None. Приема и текст като '1 234,5'."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s or not _NUM_RE.match(s):
            return None
        s = s.replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def load_grid(path: str | Path) -> Grid:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _load_openpyxl(path)
    if ext == ".xls":
        return _load_xls(path)
    if ext == ".ods":
        return _load_ods(path)
    raise ValueError(f"Неподдържан формат: {path.suffix}")


def sheet_names(path: str | Path) -> list[str]:
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True)
            names = list(wb.sheetnames)
            wb.close()
            return names
        if ext == ".xls":
            return _open_xls(path).sheet_names()
        if ext == ".ods":
            return list(_load_ods(path).keys())
    except Exception:
        return []
    return []


def _load_openpyxl(path: Path) -> Grid:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    out: Grid = {}
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(min_row=1, min_col=1, max_row=ws.max_row,
                                max_col=ws.max_column, values_only=True):
            rows.append(list(row))
        out[ws.title] = rows
    wb.close()
    return out


def _open_xls(path: Path):
    import xlrd
    try:
        return xlrd.open_workbook(path)
    except xlrd.biffh.XLRDError as e:
        if "encrypted" not in str(e).lower():
            raise
    # Файлът е "заключен" с паролата по подразбиране на Excel (само за четене)
    import io
    import msoffcrypto
    with open(path, "rb") as fh:
        office = msoffcrypto.OfficeFile(fh)
        office.load_key(password="VelvetSweatshop")
        buf = io.BytesIO()
        office.decrypt(buf)
    return xlrd.open_workbook(file_contents=buf.getvalue())


def _load_xls(path: Path) -> Grid:
    import xlrd
    wb = _open_xls(path)
    out: Grid = {}
    for sh in wb.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                t = sh.cell_type(r, c)
                v = sh.cell_value(r, c)
                if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    v = None
                elif t == xlrd.XL_CELL_ERROR:
                    v = None
                row.append(v)
            rows.append(row)
        out[sh.name] = rows
    return out


_ODS_NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}


def _q(prefix: str, tag: str) -> str:
    return f"{{{_ODS_NS[prefix]}}}{tag}"


def _load_ods(path: Path) -> Grid:
    """Лек четец на .ods без външни библиотеки (само стойности)."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    out: Grid = {}
    MAX_REPEAT = 2000  # пазим се от "безкрайни" повторени празни редове/колони
    for table in root.iter(_q("table", "table")):
        name = table.get(_q("table", "name"))
        rows: list[list] = []
        for row in table.iter(_q("table", "table-row")):
            rrep = int(row.get(_q("table", "number-rows-repeated"), "1"))
            cells: list = []
            for cell in row:
                if cell.tag not in (_q("table", "table-cell"), _q("table", "covered-table-cell")):
                    continue
                crep = int(cell.get(_q("table", "number-columns-repeated"), "1"))
                vtype = cell.get(_q("office", "value-type"))
                val = None
                if vtype in ("float", "percentage", "currency"):
                    try:
                        val = float(cell.get(_q("office", "value")))
                    except (TypeError, ValueError):
                        val = None
                elif vtype is not None:
                    texts = ["".join(p.itertext()) for p in cell.iter(_q("text", "p"))]
                    val = "\n".join(texts) if texts else None
                cells.extend([val] * min(crep, MAX_REPEAT))
            while cells and cells[-1] is None:
                cells.pop()
            rows.extend([list(cells) for _ in range(min(rrep, MAX_REPEAT))])
        while rows and not rows[-1]:
            rows.pop()
        width = max((len(r) for r in rows), default=0)
        for r in rows:
            r.extend([None] * (width - len(r)))
        out[name] = rows
    return out

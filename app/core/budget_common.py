"""Общи помощни функции за обобщаване на бюджетни приложения."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .readers import Grid, load_grid, to_number

READY_SUFFIX = " ГОТОВИ"
RED_HEX = "FFC7CE"
GREEN_HEX = "C6EFCE"


def ready_folder(root: Path) -> Path:
    return root.parent / f"{root.name}{READY_SUFFIX}"


def iter_files(root: Path, exts=(".xlsx", ".xlsm", ".xls", ".ods")):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("~$"):
            continue
        if any(part.endswith(READY_SUFFIX.strip()) for part in p.relative_to(root).parts[:-1]):
            continue
        if p.suffix.lower() in exts:
            yield p


def open_for_edit(path: Path):
    """Отваря файл за запис. .xls/.ods се превръщат в нов .xlsx със стойностите.
    Връща (workbook, разширение_за_запис)."""
    import openpyxl
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return openpyxl.load_workbook(path, keep_vba=(ext == ".xlsm")), ext
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sname, rows in load_grid(path).items():
        ws = wb.create_sheet(sname[:31])
        for r, row in enumerate(rows, start=1):
            for c, v in enumerate(row, start=1):
                if v is not None:
                    ws.cell(r, c, v)
    return wb, ".xlsx"


def mark(ws, row: int, col: int, text: str, color: str = RED_HEX):
    """Оцветява клетка (1-базирани индекси) и добавя коментар."""
    from openpyxl.comments import Comment
    from openpyxl.styles import PatternFill
    cell = ws.cell(row, col)
    if type(cell).__name__ == "MergedCell":
        return
    cell.fill = PatternFill("solid", start_color=color, end_color=color)
    old = cell.comment.text + "\n" if cell.comment else ""
    cell.comment = Comment(old + text, "Проверка")
    cell.comment.width = 260
    cell.comment.height = 110


def is_formula(v) -> bool:
    return isinstance(v, str) and v.startswith("=")


def sum_grids(grids: list[Grid], cells: dict[str, list[tuple[int, int]]]) -> dict[str, dict[tuple[int, int], float]]:
    """Сумира стойностите на дадени клетки (0-базирани) през няколко файла."""
    out: dict[str, dict[tuple[int, int], float]] = {}
    for sname, coords in cells.items():
        acc = {}
        for (r, c) in coords:
            total = 0.0
            any_val = False
            for g in grids:
                rows = g.get(sname)
                if rows is None:
                    # опит по позиция на листа
                    continue
                if r < len(rows) and c < len(rows[r]):
                    v = to_number(rows[r][c])
                    if v is not None:
                        total += v
                        any_val = True
            if any_val:
                acc[(r, c)] = total
        out[sname] = acc
    return out


def clean_number(v: float):
    if v is None:
        return None
    return int(v) if float(v).is_integer() else round(v, 6)


def safe_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def strip_name(stem: str, patterns: list[str]) -> str:
    s = stem
    for p in patterns:
        s = re.sub(p, " ", s, flags=re.I)
    return " ".join(s.replace("_", " ").split()).strip(" -")

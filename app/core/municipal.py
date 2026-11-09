"""Бюджетни прогнози общини: обобщаване на Приложение 7в от всички общини.

- Числата се сумират ред по ред.
- Средната месечна брутна заплата (СМБРЗ) не се сумира, а се изчислява наново:
  средства за заплати / численост / 12.
- Във файла на всяка община се отбелязва в червено, ако посочената СМБРЗ
  се различава от изчислената с повече от допустимото (по подразбиране 1%).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .budget_common import (RED_HEX, GREEN_HEX, clean_number, copy_sheet, iter_files, mark, number_format_for,
                            open_for_edit, ready_folder, safe_title, sheet_ref, strip_name)
from .readers import load_grid, to_number

AVG_RX = re.compile(r"средна\s+месечна|смбрз", re.I)
HEAD_RX = re.compile(r"^\s*\d+\.\s")
COUNT_RX = re.compile(r"численост", re.I)


def is_7v(p: Path) -> bool:
    return bool(re.search(r"pril[-_ ]*7\s*[вv]|nat[_ ]*delegirani", p.stem, re.I))


def municipality_name(p: Path) -> str:
    n = strip_name(p.stem, [r"pril[-_ ]*7\s*[вv].*$", r"nat[_ ]*delegirani.*$"])
    return n or p.stem


@dataclass
class Layout:
    sheet: str
    label_col: int
    unit_col: int
    value_cols: list[int]
    first_row: int
    rows: list[int]                        # всички редове с показатели
    avg_map: dict[int, tuple[int, int]]    # ред СМБРЗ -> (ред средства, ред численост)
    header_row: int


def parse_layout(grid) -> Layout:
    sheet = list(grid)[0]
    rows = grid[sheet]
    # заглавен ред: "Мерна единица"
    hdr = next(r for r, row in enumerate(rows[:20])
               if any(isinstance(v, str) and "мерна единица" in v.lower() for v in row))
    unit_col = next(c for c, v in enumerate(rows[hdr]) if isinstance(v, str) and "мерна единица" in v.lower())
    label_col = unit_col - 1
    value_cols = [c for c, v in enumerate(rows[hdr]) if c > unit_col and v not in (None, "")]
    data_rows = [r for r in range(hdr + 1, len(rows))
                 if label_col < len(rows[r]) and isinstance(rows[r][label_col], str) and rows[r][label_col].strip()]
    # раздели (започват с "1. ", "2. " ...)
    sections: list[list[int]] = []
    for r in data_rows:
        if HEAD_RX.match(rows[r][label_col]) or not sections:
            sections.append([r])
        else:
            sections[-1].append(r)
    avg_map = {}
    for sec in sections:
        unit = lambda r: str(rows[r][unit_col] or "").strip().lower()  # noqa: E731
        lab = lambda r: rows[r][label_col]  # noqa: E731
        avgs = [r for r in sec if AVG_RX.search(lab(r))]
        sal = [r for r in sec if unit(r) == "евро" and r not in avgs]
        cnt = [r for r in sec if COUNT_RX.search(lab(r))]
        for i, a in enumerate(avgs):
            if i < len(sal) and i < len(cnt):
                avg_map[a] = (sal[i], cnt[i])
    return Layout(sheet, label_col, unit_col, value_cols, hdr + 1, data_rows, avg_map, hdr)


@dataclass
class MunResult:
    name: str
    path: Path
    issues: int = 0
    error: str | None = None


def sheet_title_for(name: str) -> str:
    n = re.sub(r"^\s*община\s+", "", name, flags=re.I).strip()
    return f"ОБЩИНА {n.upper()}"


AVG_MODES = {
    "formula": "изчислена от общите суми (средства / численост / 12)",
    "sum": "сбор от средните заплати на общините (както в досегашния файл)",
}


def run(root: Path, tolerance_pct: float = 1.0, avg_mode: str = "formula",
        log: Callable[[str], None] = print, progress: Callable[[int, int], None] | None = None):
    """Прави един файл: първи лист - обобщение с формули, след него по един лист за всяка община."""
    from openpyxl.styles import Font, PatternFill

    root = Path(root)
    out_root = ready_folder(root)
    files = [p for p in iter_files(root) if is_7v(p)]
    if not files:
        raise RuntimeError("Не са намерени файлове с Приложение 7в в избраната папка.")
    log(f"Намерени файлове 7в: {len(files)}")
    base = next((p for p in files if p.suffix.lower() in (".xlsx", ".xlsm")), files[0])
    base_rows = load_grid(base)[parse_layout(load_grid(base)).sheet]
    lay = parse_layout(load_grid(base))
    results: list[MunResult] = []

    out_wb, ext = open_for_edit(base)
    summary = out_wb.worksheets[0]
    for extra in out_wb.worksheets[1:]:
        out_wb.remove(extra)
    mun_titles: list[str] = []

    for i, p in enumerate(files, start=1):
        if progress:
            progress(i, len(files) + 1)
        res = MunResult(municipality_name(p), p)
        results.append(res)
        try:
            rows = list(load_grid(p).values())[0]
            wb, _ = open_for_edit(p)
            ws = wb.worksheets[0]
            for a, (s_row, n_row) in lay.avg_map.items():
                for c in lay.value_cols:
                    sal = to_number(rows[s_row][c]) if c < len(rows[s_row]) else None
                    cnt = to_number(rows[n_row][c]) if c < len(rows[n_row]) else None
                    rep = to_number(rows[a][c]) if c < len(rows[a]) else None
                    if not cnt:
                        if rep:
                            res.issues += 1
                            mark(ws, a + 1, c + 1, "Има посочена средна заплата, но численост е 0 или празна.")
                        continue
                    calc = (sal or 0) / cnt / 12
                    if rep is None or abs(rep - calc) > max(1.0, abs(calc) * tolerance_pct / 100):
                        res.issues += 1
                        mark(ws, a + 1, c + 1, f"Посочено: {clean_number(rep)}\nИзчислено: {calc:,.2f}\n"
                                               f"(средства {clean_number(sal)} / численост {clean_number(cnt)} / 12)")
            for r in lay.rows:
                fmt = number_format_for(base_rows[r][lay.unit_col])
                for c in lay.value_cols:
                    ws.cell(r + 1, c + 1).number_format = fmt
            title = sheet_title_for(res.name)
            new_ws = copy_sheet(ws, out_wb, title)
            new_ws.sheet_properties.tabColor = "FFC7CE" if res.issues else "92D050"
            mun_titles.append(new_ws.title)
            log(f"  {'✓' if not res.issues else '✗'} {res.name}: "
                + ("ОК" if not res.issues else f"несъответствия в средната заплата: {res.issues}"))
        except Exception as e:  # noqa: BLE001
            res.error = str(e)
            log(f"  ✗ {res.name}: грешка: {e}")

    # обобщаващ лист - само формули, за да се вижда откъде идва всяка стойност
    from openpyxl.utils import get_column_letter
    for r in lay.rows:
        label = str(base_rows[r][lay.label_col] or "")
        fmt = number_format_for(base_rows[r][lay.unit_col])
        is_head = bool(HEAD_RX.match(label)) and not base_rows[r][lay.unit_col]
        for c in lay.value_cols:
            cell = summary.cell(r + 1, c + 1)
            if type(cell).__name__ == "MergedCell":
                continue
            if is_head:
                cell.value = None
                continue
            if r in lay.avg_map and avg_mode == "formula":
                s_row, n_row = lay.avg_map[r]
                col = get_column_letter(c + 1)
                cell.value = f'=IF(N({col}{n_row + 1})=0,"",{col}{s_row + 1}/{col}{n_row + 1}/12)'
            else:
                cell.value = "=" + "+".join(sheet_ref(t, r + 1, c + 1) for t in mun_titles) if mun_titles else None
            cell.number_format = fmt
    for r in range(1, lay.header_row + 1):
        for c in range(1, summary.max_column + 1):
            v = summary.cell(r, c).value
            if isinstance(v, str) and "министерство на здравеопазването" in v.lower() and "обобщено" not in v.lower():
                summary.cell(r, c).value = v.rstrip() + " - обобщено за всички общини"
                break
    summary.title = safe_title(summary.title + " общо", out_wb) if summary.title in mun_titles else summary.title

    # лист с проверките
    chk = out_wb.create_sheet("Проверки")
    chk.append(["Община", "Несъответствия в средната заплата", "Бележка"])
    for c in chk[1]:
        c.font = Font(bold=True)
    for i, r in enumerate(results, start=2):
        chk.cell(i, 1, r.name)
        chk.cell(i, 2, r.issues)
        chk.cell(i, 3, r.error or ("" if not r.issues else "виж червените клетки в листа на общината"))
        color = RED_HEX if (r.issues or r.error) else GREEN_HEX
        chk.cell(i, 2).fill = PatternFill("solid", start_color=color, end_color=color)
    chk.cell(len(results) + 3, 1, "Средна заплата в обобщения лист: " + AVG_MODES.get(avg_mode, avg_mode))
    chk.column_dimensions["A"].width = 30
    chk.column_dimensions["B"].width = 34
    chk.column_dimensions["C"].width = 50

    out_wb.active = 0
    for w in out_wb.worksheets:
        w.sheet_view.tabSelected = w is summary
    out_wb.calculation.fullCalcOnLoad = True
    out = out_root / f"Обобщено Pril-7в всички общини{ext}"
    out_root.mkdir(parents=True, exist_ok=True)
    out_wb.save(out)
    if progress:
        progress(len(files) + 1, len(files) + 1)
    log(f"Готово. Обобщеният файл е: {out}")
    return out, results

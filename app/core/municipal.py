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

from .budget_common import (RED_HEX, GREEN_HEX, clean_number, is_formula, iter_files, mark,
                            open_for_edit, ready_folder, strip_name)
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


def run(root: Path, tolerance_pct: float = 1.0, log: Callable[[str], None] = print,
        progress: Callable[[int, int], None] | None = None):
    from openpyxl.styles import Alignment, Font, PatternFill

    root = Path(root)
    out_root = ready_folder(root)
    files = [p for p in iter_files(root) if is_7v(p)]
    if not files:
        raise RuntimeError("Не са намерени файлове с Приложение 7в в избраната папка.")
    log(f"Намерени файлове 7в: {len(files)}")
    base = next((p for p in files if p.suffix.lower() in (".xlsx", ".xlsm")), files[0])
    lay = parse_layout(load_grid(base))
    grids = []
    results: list[MunResult] = []

    for i, p in enumerate(files, start=1):
        if progress:
            progress(i, len(files) + 1)
        res = MunResult(municipality_name(p), p)
        results.append(res)
        try:
            g = load_grid(p)
            rows = list(g.values())[0]
            grids.append((res.name, rows))
            wb, ext = open_for_edit(p)
            ws = wb.worksheets[0]
            for a, (s, n) in lay.avg_map.items():
                for c in lay.value_cols:
                    sal = to_number(rows[s][c]) if c < len(rows[s]) else None
                    cnt = to_number(rows[n][c]) if c < len(rows[n]) else None
                    rep = to_number(rows[a][c]) if c < len(rows[a]) else None
                    if not cnt:
                        if rep:
                            res.issues += 1
                            mark(ws, a + 1, c + 1, "Има посочена средна заплата, но численост е 0 или празна.")
                        continue
                    calc = (sal or 0) / cnt / 12
                    if rep is None or abs(rep - calc) > max(1.0, abs(calc) * tolerance_pct / 100):
                        res.issues += 1
                        mark(ws, a + 1, c + 1, f"Посочено: {clean_number(rep)}\nИзчислено: {calc:.0f}\n"
                                               f"(средства {clean_number(sal)} / численост {clean_number(cnt)} / 12)")
            dst = (out_root / "Общини" / p.relative_to(root)).with_suffix(ext)
            dst.parent.mkdir(parents=True, exist_ok=True)
            wb.save(dst)
            log(f"  {'✓' if not res.issues else '✗'} {res.name}: "
                + ("ОК" if not res.issues else f"несъответствия в средната заплата: {res.issues}"))
        except Exception as e:  # noqa: BLE001
            res.error = str(e)
            log(f"  ✗ {res.name}: грешка: {e}")

    # обобщен файл
    wb, ext = open_for_edit(base)
    ws = wb.worksheets[0]
    sums: dict[tuple[int, int], float] = {}
    for r in lay.rows:
        if r in lay.avg_map:
            continue
        for c in lay.value_cols:
            vals = [to_number(rows[r][c]) for _n, rows in grids if r < len(rows) and c < len(rows[r])]
            vals = [v for v in vals if v is not None]
            if vals:
                sums[(r, c)] = sum(vals)
            cell = ws.cell(r + 1, c + 1)
            if type(cell).__name__ != "MergedCell" and not is_formula(cell.value):
                cell.value = clean_number(sums.get((r, c))) if (r, c) in sums else None
    for a, (s, n) in lay.avg_map.items():
        for c in lay.value_cols:
            cnt = sums.get((n, c)) or 0
            cell = ws.cell(a + 1, c + 1)
            cell.value = round(sums.get((s, c), 0) / cnt / 12) if cnt else 0
    # заглавие
    for r in range(1, lay.header_row + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and "министерство на здравеопазването" in v.lower():
                ws.cell(r, c).value = v + " - обобщено за всички общини"
                break

    # лист по общини
    det = wb.create_sheet("По общини")
    headers = [str(load_grid(base)[lay.sheet][lay.header_row][c] or "").strip() for c in lay.value_cols]
    det.append(["Показател", "Мерна единица", "Община"] + headers)
    for c in det[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True)
    base_rows = load_grid(base)[lay.sheet]
    for r in lay.rows:
        label = " ".join(str(base_rows[r][lay.label_col]).split())
        unit = base_rows[r][lay.unit_col]
        for name, rows in grids:
            vals = [to_number(rows[r][c]) if r < len(rows) and c < len(rows[r]) else None for c in lay.value_cols]
            if any(vals):
                det.append([label, unit, name] + [clean_number(v) for v in vals])
    for col, w in zip("ABCDEFGH", [60, 16, 22, 14, 14, 14, 14, 14]):
        det.column_dimensions[col].width = w
    det.freeze_panes = "A2"
    det.auto_filter.ref = det.dimensions

    # лист с проверките
    chk = wb.create_sheet("Проверки")
    chk.append(["Община", "Несъответствия в СМБРЗ", "Бележка"])
    for c in chk[1]:
        c.font = Font(bold=True)
    for i, r in enumerate(results, start=2):
        chk.append([r.name, r.issues, r.error or ""])
        color = RED_HEX if (r.issues or r.error) else GREEN_HEX
        chk.cell(i, 2).fill = PatternFill("solid", start_color=color, end_color=color)
    chk.column_dimensions["A"].width = 30
    chk.column_dimensions["B"].width = 24
    chk.column_dimensions["C"].width = 60

    out = out_root / f"Обобщено Pril-7в всички общини{ext}"
    out_root.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    if progress:
        progress(len(files) + 1, len(files) + 1)
    log(f"Готово. Обобщеният файл е: {out}")
    return out, results

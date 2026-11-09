"""Сравнение на годишни отчети на ЛЗБП с предходни години.

Логика:
 1. Обхождат се всички таблици в папката на новата година.
 2. За всяка се определя вид отчет (365БО, Прил. 9, ...) и лечебно заведение.
 3. Търси се същият отчет на същото заведение в папката/папките на старите години.
 4. Сравнява се клетка по клетка (а при хоспитализациите - по "Шифър").
 5. Записва се копие с оцветени разлики и лист "Разлики" в папка "<нова> ГОТОВИ".
"""
from __future__ import annotations

import math
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .readers import SUPPORTED_EXT, Grid, load_grid, sheet_names, to_number

READY_SUFFIX = " ГОТОВИ"
DIFF_SHEET = "Разлики"

# ---------------------------------------------------------------- видове отчети

REPORT_TYPES: list[tuple[str, str, re.Pattern]] = [
    ("HOSP_DAY", "Хоспитализации - дневни", re.compile(r"хоспитализац.*дневн", re.I)),
    ("HOSP_STAT", "Хоспитализации - стационар", re.compile(r"хоспитализац.*стационар", re.I)),
    ("365BO", "Отчет 365БО", re.compile(r"365\s*[BБ]\s*[OО]", re.I)),
    ("365O", "Отчет 365О", re.compile(r"365\s*[OО]", re.I)),
    ("PR9", "Приложение 9", re.compile(r"pr[_\s-]*9(?!\d)", re.I)),
    ("PR11", "Приложение 11", re.compile(r"pr[_\s-]*11(?!\d)", re.I)),
    ("PR1A", "Приложение 1А", re.compile(r"pril[_\s-]*1a", re.I)),
    ("367", "Отчет 367", re.compile(r"(?<!\d)367(?!\d)")),
    ("369", "Отчет 369", re.compile(r"(?<!\d)369(?!\d)")),
    ("370", "Отчет 370", re.compile(r"(?<!\d)370(?!\d)")),
    ("372", "Отчет 372", re.compile(r"(?<!\d)372(?!\d)")),
    ("ZDRAVNI1", "Здравни 1", re.compile(r"zdravni", re.I)),
]
TYPE_LABEL = {k: lbl for k, lbl, _ in REPORT_TYPES}

KEYED_TYPES = {"HOSP_DAY", "HOSP_STAT"}


def detect_type(path: Path) -> str | None:
    name = path.stem
    for key, _lbl, rx in REPORT_TYPES:
        if rx.search(name):
            return key
    # по съдържание
    names = set(sheet_names(path))
    if {"IV.1a.", "V.2a.", "VI.1."} <= names or {"I.", "II.", "IV.1.", "VII.1."} <= names:
        return "365BO"
    if "Хоспитализации" in names:
        return "HOSP_STAT"
    return None


def norm_name(s: str) -> str:
    s = s.casefold().replace("ё", "е")
    s = re.sub(r"[^0-9a-zа-я]+", "", s)
    return s


_CODE_RE = re.compile(r"_13_(\d{3,7})")


def file_code(path: Path) -> str | None:
    m = _CODE_RE.search(path.stem)
    return m.group(1) if m else None


@dataclass
class ReportFile:
    path: Path
    rel: Path               # относителен път спрямо корена
    rtype: str
    facility: str           # име на заведението (папката)
    facility_key: str
    code: str | None
    mtime: float

    @property
    def depth(self) -> int:
        return len(self.rel.parts)


def scan_folder(root: Path, log: Callable[[str], None] | None = None) -> tuple[list[ReportFile], list[Path]]:
    found: list[ReportFile] = []
    skipped: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.endswith(READY_SUFFIX.strip()) and not d.endswith(READY_SUFFIX)]
        for fn in filenames:
            p = Path(dirpath) / fn
            if fn.startswith("~$"):
                continue
            if p.suffix.lower() not in SUPPORTED_EXT:
                continue
            rtype = detect_type(p)
            if rtype is None:
                skipped.append(p)
                continue
            rel = p.relative_to(root)
            if len(rel.parts) > 1:
                facility = rel.parts[-2]
            else:
                # файл директно в корена: името на заведението е в името на файла
                facility = re.sub(r"(vhod_)?365\s*BO[-_\d]*|_13_\d+|\d{4}", " ", p.stem, flags=re.I).strip(" _-") or p.stem
            found.append(ReportFile(p, rel, rtype, facility, norm_name(facility),
                                    file_code(p), p.stat().st_mtime))
    return found, skipped


def find_match(new: ReportFile, olds: list[ReportFile]) -> ReportFile | None:
    same_type = [o for o in olds if o.rtype == new.rtype]
    if not same_type:
        return None

    def pick(cands: list[ReportFile]) -> ReportFile | None:
        if not cands:
            return None
        # 1) същият относителен път, 2) по-плитко ниво, 3) най-нов файл
        exact = [c for c in cands if c.rel.parent == new.rel.parent]
        if exact:
            cands = exact
        return sorted(cands, key=lambda c: (c.depth, -c.mtime))[0]

    by_fac = [o for o in same_type if o.facility_key == new.facility_key]
    if by_fac:
        return pick(by_fac)
    if new.code:
        by_code = [o for o in same_type if o.code == new.code]
        if by_code:
            return pick(by_code)
    # частично съвпадение на името (напр. "МБАЛ ХИГИЯ" и "МБАЛ Хигия - Пазарджик")
    part = [o for o in same_type if o.facility_key and new.facility_key and
            (o.facility_key.startswith(new.facility_key) or new.facility_key.startswith(o.facility_key))]
    return pick(part)


# ---------------------------------------------------------------- сравнение

@dataclass
class Thresholds:
    low: float = 1.0     # под това - без цвят
    mid: float = 5.0     # до това - зелено
    high: float = 10.0   # до това - жълто, над него - червено


COLOR_NONE, COLOR_GREEN, COLOR_YELLOW, COLOR_RED = "", "green", "yellow", "red"
FILL_HEX = {COLOR_GREEN: "C6EFCE", COLOR_YELLOW: "FFEB9C", COLOR_RED: "FFC7CE"}
COLOR_LABEL = {COLOR_GREEN: "зелено", COLOR_YELLOW: "жълто", COLOR_RED: "червено"}


def pct_change(new: float, old: float) -> float:
    if old == 0:
        return 0.0 if new == 0 else math.inf
    return (new - old) / abs(old) * 100.0


def classify(pct: float, t: Thresholds) -> str:
    a = abs(pct)
    if a < t.low:
        return COLOR_NONE
    if a <= t.mid:
        return COLOR_GREEN
    if a <= t.high:
        return COLOR_YELLOW
    return COLOR_RED


@dataclass
class CellDiff:
    sheet: str
    row: int            # 0-базиран в новия файл (-1 = ред липсва в новия)
    col: int
    label: str
    column_label: str
    new: float | None
    olds: list[float | None]   # по една стойност за всяка стара година (в реда на подаване)
    pct: float                 # спрямо първата (последна) стара година
    color: str


def _row_label(row: list, upto: int = 4) -> str:
    parts = []
    for v in row[:upto]:
        if isinstance(v, str) and v.strip() and to_number(v) is None:
            parts.append(" ".join(v.split()))
    return " | ".join(parts)[:120]


def _col_letter(c: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(c + 1)


def _cell(grid_sheet: list[list], r: int, c: int):
    if r < len(grid_sheet) and c < len(grid_sheet[r]):
        return grid_sheet[r][c]
    return None


def _strip_year(s: str) -> str:
    return norm_name(re.sub(r"(?<!\d)(20\d{2}|\d{2})(?!\d)", "", s))


def _match_sheet(name: str, old: Grid, new: Grid | None = None) -> str | None:
    if name in old:
        return name
    n = norm_name(name)
    for k in old:
        if norm_name(k) == n:
            return k
    n = _strip_year(name)
    for k in old:
        if _strip_year(k) == n:
            return k
    # същата позиция, ако двата файла имат еднакъв брой листове
    if new is not None and len(new) == len(old):
        keys = list(new)
        if name in keys:
            return list(old)[keys.index(name)]
    return None


def compare_positional(new: Grid, olds: list[Grid], t: Thresholds) -> list[CellDiff]:
    diffs: list[CellDiff] = []
    for sname, rows in new.items():
        if sname == DIFF_SHEET:
            continue
        old_sheets = []
        for og in olds:
            k = _match_sheet(sname, og, new)
            old_sheets.append(og[k] if k else None)
        if old_sheets[0] is None:
            continue
        nrows = max([len(rows)] + [len(s) for s in old_sheets if s is not None])
        for r in range(nrows):
            nrow = rows[r] if r < len(rows) else []
            ncols = max([len(nrow)] + [len(s[r]) for s in old_sheets if s is not None and r < len(s)])
            for c in range(ncols):
                nv_raw = _cell(rows, r, c)
                ov_raw = _cell(old_sheets[0], r, c)
                nv, ov = to_number(nv_raw), to_number(ov_raw)
                if nv is None and ov is None:
                    continue
                # текст срещу число (заглавия и т.н.) - не сравняваме
                if (nv is None and nv_raw not in (None, "")) or (ov is None and ov_raw not in (None, "")):
                    continue
                pct = pct_change(nv or 0.0, ov or 0.0)
                color = classify(pct, t)
                if not color:
                    continue
                label = _row_label(nrow) or _row_label(old_sheets[0][r] if r < len(old_sheets[0]) else [])
                diffs.append(CellDiff(sname, r, c, label, _col_letter(c), nv,
                                      [to_number(_cell(s, r, c)) if s is not None else None for s in old_sheets],
                                      pct, color))
    return diffs


def _find_key_header(rows: list[list]) -> tuple[int, int] | None:
    for r, row in enumerate(rows[:30]):
        for c, v in enumerate(row):
            if isinstance(v, str) and v.strip().casefold() in ("шифър", "шифър на диагнозата", "код"):
                return r, c
    return None


def compare_keyed(new: Grid, olds: list[Grid], t: Thresholds) -> list[CellDiff]:
    """Сравнение по ключова колона (напр. 'Шифър' при хоспитализациите)."""
    diffs: list[CellDiff] = []
    for sname, rows in new.items():
        hdr = _find_key_header(rows)
        old_sheets = []
        for og in olds:
            k = _match_sheet(sname, og, new)
            old_sheets.append(og[k] if k else None)
        if hdr is None or old_sheets[0] is None:
            diffs.extend(compare_positional({sname: rows}, [{sname: s} if s else {} for s in old_sheets], t))
            continue
        hr, kc = hdr
        headers = [" ".join(str(v).split()) if v is not None else "" for v in rows[hr]]

        def index(sheet_rows):
            h = _find_key_header(sheet_rows)
            if h is None:
                return {}, {}
            r0, kcol = h
            cols = {(" ".join(str(v).split()) if v is not None else ""): i for i, v in enumerate(sheet_rows[r0])}
            idx = {}
            for r in range(r0 + 1, len(sheet_rows)):
                key = sheet_rows[r][kcol] if kcol < len(sheet_rows[r]) else None
                if key not in (None, ""):
                    idx[str(key).strip()] = r
            return idx, cols

        old_idx = [index(s) if s is not None else ({}, {}) for s in old_sheets]
        seen = set()
        for r in range(hr + 1, len(rows)):
            row = rows[r]
            key = row[kc] if kc < len(row) else None
            if key in (None, ""):
                continue
            key = str(key).strip()
            seen.add(key)
            for c, h in enumerate(headers):
                if c == kc or not h:
                    continue
                nv = to_number(row[c] if c < len(row) else None)
                vals = []
                for (idx, cols), s in zip(old_idx, old_sheets):
                    orow = idx.get(key)
                    oc = cols.get(h)
                    vals.append(to_number(s[orow][oc]) if s is not None and orow is not None and oc is not None and oc < len(s[orow]) else None)
                if nv is None and vals[0] is None:
                    continue
                pct = pct_change(nv or 0.0, vals[0] or 0.0)
                color = classify(pct, t)
                if color:
                    diffs.append(CellDiff(sname, r, c, f"{key} {_row_label(row, kc)}".strip(), h, nv, vals, pct, color))
        # редове, които ги има в старата, а липсват в новата година
        idx0, cols0 = old_idx[0]
        s0 = old_sheets[0]
        for key, orow in idx0.items():
            if key in seen:
                continue
            for c, h in enumerate(headers):
                oc = cols0.get(h)
                if c == kc or not h or oc is None or oc >= len(s0[orow]):
                    continue
                ov = to_number(s0[orow][oc])
                if ov:
                    lbl = _row_label(s0[orow], (_find_key_header(s0) or (0, 1))[1])
                    diffs.append(CellDiff(sname, -1, c, f"{key} {lbl} (липсва в новия отчет)".strip(), h, None,
                                          [ov] + [None] * (len(olds) - 1), -100.0, COLOR_RED))
    return diffs


# ---------------------------------------------------------------- запис

def _fmt_pct(p: float) -> str:
    if math.isinf(p):
        return "ново"
    return f"{p:+.1f}%"


def _fmt_num(v) -> str:
    if v is None:
        return "-"
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", " ")
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def write_output(src: Path, dst: Path, diffs: list[CellDiff], old_labels: list[str],
                 new_label: str, grid: Grid | None = None) -> Path:
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill

    ext = src.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        wb = openpyxl.load_workbook(src, keep_vba=(ext == ".xlsm"))
        out_path = dst
    else:
        # .xls / .ods не могат да се запишат директно - правим .xlsx със стойностите
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        grid = grid or load_grid(src)
        for sname, rows in grid.items():
            ws = wb.create_sheet(sname[:31])
            for r, row in enumerate(rows, start=1):
                for c, v in enumerate(row, start=1):
                    if v is not None:
                        ws.cell(r, c, v)
        out_path = dst.with_suffix(".xlsx")

    fills = {k: PatternFill("solid", start_color=v, end_color=v) for k, v in FILL_HEX.items()}
    for d in diffs:
        if d.row < 0 or d.sheet not in wb.sheetnames:
            continue
        ws = wb[d.sheet]
        cell = ws.cell(d.row + 1, d.col + 1)
        if type(cell).__name__ == "MergedCell":
            continue
        cell.fill = fills[d.color]
        lines = [f"{new_label}: {_fmt_num(d.new)}"]
        for lbl, v in zip(old_labels, d.olds):
            lines.append(f"{lbl}: {_fmt_num(v)}")
        lines.append(f"Промяна спрямо {old_labels[0]}: {_fmt_pct(d.pct)}")
        cell.comment = Comment("\n".join(lines), "Сравнение")
        cell.comment.width = 220
        cell.comment.height = 20 * (len(lines) + 1)

    name = DIFF_SHEET
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name)  # в края, за да не се разместят листовете (макросите разчитат на реда им)
    for other in wb.worksheets:
        other.sheet_view.tabSelected = False
    ws.sheet_view.tabSelected = True
    wb.active = len(wb.sheetnames) - 1
    header = ["Лист", "Клетка", "Показател", "Колона", new_label] + old_labels + [f"% спрямо {old_labels[0]}", "Цвят"]
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    order = {COLOR_RED: 0, COLOR_YELLOW: 1, COLOR_GREEN: 2}
    rown = 1
    for d in sorted(diffs, key=lambda d: (order[d.color], -abs(d.pct) if not math.isinf(d.pct) else -1e18)):
        rown += 1
        addr = f"{_col_letter(d.col)}{d.row + 1}" if d.row >= 0 else "-"
        pct_val = "ново" if math.isinf(d.pct) else round(d.pct, 2)
        ws.append([d.sheet, addr, d.label, d.column_label, d.new] + list(d.olds) + [pct_val, COLOR_LABEL[d.color]])
        ws.cell(rown, len(header) - 1).fill = fills[d.color]
        ws.cell(rown, len(header)).fill = fills[d.color]
    widths = [12, 9, 60, 18, 14] + [14] * len(old_labels) + [14, 10]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[_col_letter(i - 1)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


# ---------------------------------------------------------------- цялостен процес

@dataclass
class FileResult:
    new_file: Path
    rtype: str
    facility: str
    matched: list[Path | None] = field(default_factory=list)
    output: Path | None = None
    counts: dict = field(default_factory=dict)
    error: str | None = None


def folder_label(p: Path) -> str:
    m = re.search(r"(19|20)\d{2}", p.name)
    return m.group(0) if m else p.name


def ready_folder(new_root: Path) -> Path:
    return new_root.parent / f"{new_root.name}{READY_SUFFIX}"


def run_comparison(new_root: Path, old_roots: list[Path], t: Thresholds,
                   log: Callable[[str], None] = print,
                   progress: Callable[[int, int], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> tuple[Path, list[FileResult]]:
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    new_root = Path(new_root)
    old_roots = [Path(p) for p in old_roots]
    out_root = ready_folder(new_root)
    new_label = folder_label(new_root)
    old_labels = [folder_label(p) for p in old_roots]

    log(f"Сканиране на {new_root} ...")
    new_files, skipped = scan_folder(new_root)
    old_sets = []
    for p in old_roots:
        log(f"Сканиране на {p} ...")
        old_sets.append(scan_folder(p)[0])
    log(f"Намерени отчети: {len(new_files)} (пропуснати непознати файлове: {len(skipped)})")

    results: list[FileResult] = []
    total = len(new_files)
    for i, nf in enumerate(sorted(new_files, key=lambda f: str(f.rel))):
        if cancelled and cancelled():
            log("Прекъснато.")
            break
        if progress:
            progress(i, total)
        res = FileResult(nf.path, nf.rtype, nf.facility)
        results.append(res)
        matches = [find_match(nf, olds) for olds in old_sets]
        res.matched = [m.path if m else None for m in matches]
        dst = out_root / nf.rel
        if matches[0] is None:
            res.error = "няма съответен отчет в " + old_labels[0]
            log(f"  ⚠ {nf.rel}: {res.error} - копира се без сравнение")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(nf.path, dst)
            res.output = dst
            continue
        try:
            ng = load_grid(nf.path)
            ogs = [load_grid(m.path) if m else {} for m in matches]
            if nf.rtype in KEYED_TYPES:
                diffs = compare_keyed(ng, ogs, t)
            else:
                diffs = compare_positional(ng, ogs, t)
            res.output = write_output(nf.path, dst, diffs, old_labels, new_label, ng)
            res.counts = {c: sum(1 for d in diffs if d.color == c) for c in (COLOR_RED, COLOR_YELLOW, COLOR_GREEN)}
            log(f"  ✓ {nf.rel}  ↔  {matches[0].rel}:  "
                f"червени {res.counts[COLOR_RED]}, жълти {res.counts[COLOR_YELLOW]}, зелени {res.counts[COLOR_GREEN]}")
        except Exception as e:  # noqa: BLE001
            res.error = f"грешка: {e}"
            log(f"  ✗ {nf.rel}: {res.error}")
    if progress:
        progress(total, total)

    # обобщителен файл
    out_root.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Обобщение"
    ws.append(["Заведение", "Отчет", f"Файл {new_label}"] + [f"Файл {l}" for l in old_labels] +
              ["Червени", "Жълти", "Зелени", "Бележка"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in results:
        ws.append([r.facility, TYPE_LABEL.get(r.rtype, r.rtype), str(r.new_file.relative_to(new_root))] +
                  [str(m.relative_to(o)) if m else "-" for m, o in zip(r.matched, old_roots)] +
                  [r.counts.get(COLOR_RED, 0), r.counts.get(COLOR_YELLOW, 0), r.counts.get(COLOR_GREEN, 0),
                   r.error or ""])
        row = ws.max_row
        for col, color in ((4 + len(old_roots), COLOR_RED), (5 + len(old_roots), COLOR_YELLOW), (6 + len(old_roots), COLOR_GREEN)):
            if ws.cell(row, col).value:
                ws.cell(row, col).fill = PatternFill("solid", start_color=FILL_HEX[color], end_color=FILL_HEX[color])
    if skipped:
        ws2 = wb.create_sheet("Пропуснати файлове")
        ws2.append(["Файл (непознат вид отчет)"])
        for p in skipped:
            ws2.append([str(p.relative_to(new_root))])
    for col, w in zip("ABCDEFGHIJ", [40, 26, 60, 60, 10, 10, 10, 40]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    summary = out_root / f"Обобщение на сравнението {new_label} спрямо {', '.join(old_labels)}.xlsx"
    wb.save(summary)
    log(f"Готово. Резултатите са в: {out_root}")
    return summary, results

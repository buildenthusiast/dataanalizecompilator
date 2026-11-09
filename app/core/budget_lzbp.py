"""Бюджетни прогнози ЛЗБП: проверки и обобщаване на приложенията от болниците.

Очаквана структура на входната папка: по една подпапка за всяко лечебно заведение,
в която са приложенията, получени по имейл (4а, 6а, 6б, 6в, 10а, 12б).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .budget_common import (RED_HEX, GREEN_HEX, clean_number, copy_sheet, is_formula, iter_files, mark,
                            open_for_edit, ready_folder, safe_copy, sheet_ref)
from .readers import Grid, load_grid, to_number

TYPES = [
    ("10A", "Приложение 10а", re.compile(r"10\s*[aа](?![a-zа-я])|opr[-_ ]*bal", re.I)),
    ("12B", "Приложение 12б", re.compile(r"12\s*[bб]|zadalzhenia", re.I)),
    ("4A", "Приложение 4а", re.compile(r"(?<!\d)4\s*[aа](?![a-zа-я])|soe[_ ]*fin", re.I)),
    ("6A", "Приложение 6а", re.compile(r"angajimenti|lizing|(?<!\d)6\s*[aа](?![a-zа-я])", re.I)),
    ("6B", "Приложение 6б", re.compile(r"nov[_ ]*dalg|(?<!\d)6\s*[bб](?![a-zа-я])", re.I)),
    ("6V", "Приложение 6в", re.compile(r"lihvi|(?<!\d)6\s*[вv](?![a-zа-я])", re.I)),
]
TYPE_LABEL = {k: l for k, l, _ in TYPES}
OUT_NAME = {
    "10A": "Pril-10a-OPR-BAL-nefinansovi-2026-2028",
    "12B": "Pril-12b-Zadalzhenia i vzemania",
    "4A": "Pril-4a SOE fin res 2026-2028",
    "6A": "Pril-6a-Angajimenti_Lizing_i_dr 2026-2028",
    "6B": "Pril-6б-Prog_nov_dalg_Zaemi 2026-2028",
    "6V": "Pril-6в-Lihvi_po_zaemi 2025-2028",
}
GROUPS = ("ДЛЗБП", "ОЛЗБП")
EXCLUDED = "Не се включва"
TOL = 0.0001
TOL_12B = 1.0   # 12б е в цели хил. евро - допуска се разлика от закръгляне до 1


def detect_type(p: Path) -> str | None:
    for k, _l, rx in TYPES:
        if rx.search(p.stem):
            return k
    return None


@dataclass
class HospitalFiles:
    name: str
    files: dict[str, Path] = field(default_factory=dict)
    extra: list[Path] = field(default_factory=list)


def scan(root: Path) -> list[HospitalFiles]:
    hospitals: dict[str, HospitalFiles] = {}
    for p in iter_files(root):
        rel = p.relative_to(root)
        name = rel.parts[0] if len(rel.parts) > 1 else root.name
        h = hospitals.setdefault(name, HospitalFiles(name))
        t = detect_type(p)
        if t and t not in h.files:
            h.files[t] = p
        else:
            h.extra.append(p)
    return list(hospitals.values())


# ------------------------------------------------------------------ 10а

def _code(v) -> int | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if float(v).is_integer() else None
    if isinstance(v, str) and re.fullmatch(r"\s*\d{4,5}\s*", v):
        return int(v)
    return None


@dataclass
class Form10A:
    opr: str
    bal: str
    years: dict[int, str]                    # колона -> година
    opr_rows: dict[int, int]                 # код -> ред
    bal_rows: dict[int, int]
    name_cell: tuple[int, int] = (3, 0)


def parse_10a(grid: Grid) -> Form10A | None:
    names = list(grid)
    opr = next((n for n in names if "приход" in n.lower()), names[0] if names else None)
    bal = next((n for n in names if "баланс" in n.lower()), names[1] if len(names) > 1 else None)
    if not opr or not bal:
        return None
    years = {}
    for row in grid[opr][:15]:
        for c, v in enumerate(row):
            m = re.fullmatch(r"\s*(20\d{2})\s*(г\.?)?\s*", str(v)) if v is not None else None
            if m:
                years[c] = m.group(1)
        if years:
            break

    def rows_by_code(rows):
        out = {}
        for r, row in enumerate(rows):
            if len(row) > 1:
                code = _code(row[1])
                if code is not None and code not in out:
                    out[code] = r
        return out

    return Form10A(opr, bal, years, rows_by_code(grid[opr]), rows_by_code(grid[bal]))


def _val(grid: Grid, sheet: str, row: int | None, col: int) -> float:
    if row is None:
        return 0.0
    rows = grid[sheet]
    if row < len(rows) and col < len(rows[row]):
        return to_number(rows[row][col]) or 0.0
    return 0.0


@dataclass
class Check:
    title: str
    year: str
    left_label: str
    left: float
    right_label: str
    right: float
    cells: list[tuple[str, str, int, int]]   # (вид файл, лист, ред, колона) 0-базирани
    tol: float = TOL

    @property
    def ok(self) -> bool:
        return abs(self.left - self.right) <= self.tol + 1e-9


def checks_10a(grid: Grid, f: Form10A, grid12: Grid | None = None) -> list[Check]:
    out: list[Check] = []
    o, b = f.opr_rows, f.bal_rows
    for col, year in f.years.items():
        def ov(code): return _val(grid, f.opr, o.get(code), col)
        def bv(code): return _val(grid, f.bal, b.get(code), col)
        if 14400 in o and 5600 in b:
            out.append(Check("ОПР: Печалба - Загуба = Баланс: Текуща печалба (загуба)", year,
                             "ОПР 14400 - 19200", ov(14400) - ov(19200), "Баланс 05600", bv(5600),
                             [("10A", f.opr, o[14400], col), ("10A", f.opr, o.get(19200, o[14400]), col),
                              ("10A", f.bal, b[5600], col)]))
        if 4500 in b and 8500 in b:
            out.append(Check("Баланс: Сума на актива = Сума на пасива", year,
                             "Актив 04500", bv(4500), "Пасив 08500", bv(8500),
                             [("10A", f.bal, b[4500], col), ("10A", f.bal, b[8500], col)]))
        if 14500 in o and 19500 in o:
            out.append(Check("ОПР: Всичко разходи = Всичко приходи", year,
                             "ОПР 14500", ov(14500), "ОПР 19500", ov(19500),
                             [("10A", f.opr, o[14500], col), ("10A", f.opr, o[19500], col)]))
        if grid12 is not None:
            p12 = parse_12b(grid12)
            if p12 and year in p12["years"]:
                c12 = p12["years"][year]
                s12 = p12["sheet"]
                for label, r12, code, title in (("Задължения", p12.get("Задължения"), 7000, "Общо за раздел В (пасив)"),
                                                ("Вземания", p12.get("Вземания"), 3200, "Общо за група II (текущи активи)")):
                    if r12 is None or code not in b:
                        continue
                    out.append(Check(f"12б: {label} = Баланс: {title}", year,
                                     f"12б {label}", _val(grid12, s12, r12, c12), f"Баланс {code:05d}", bv(code),
                                     [("12B", s12, r12, c12), ("10A", f.bal, b[code], col)],
                                     tol=TOL_12B))
    return out


def parse_12b(grid: Grid) -> dict | None:
    if not grid:
        return None
    sheet = list(grid)[0]
    rows = grid[sheet]
    out: dict = {"sheet": sheet, "years": {}}
    for r, row in enumerate(rows[:20]):
        for c, v in enumerate(row):
            if v is None:
                continue
            s = str(v).strip()
            m = re.fullmatch(r"(20\d{2})\s*(г\.?)?", s)
            if m:
                out["years"][m.group(1)] = c
            if s in ("Задължения", "Вземания") and c == 0:
                out[s] = r
    return out


# ------------------------------------------------------------------ запис на проверки

def write_checks_sheet(wb, checks: list[Check], title="Проверки"):
    from openpyxl.styles import Font, PatternFill
    if title in wb.sheetnames:
        del wb[title]
    ws = wb.create_sheet(title)
    ws.append(["Проверка", "Година", "Ляво", "Стойност", "Дясно", "Стойност", "Разлика", "Резултат"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for i, ch in enumerate(checks, start=2):
        ws.append([ch.title, ch.year, ch.left_label, clean_number(ch.left), ch.right_label,
                   clean_number(ch.right), clean_number(ch.left - ch.right), "ОК" if ch.ok else "НЕ СЪВПАДА"])
        color = GREEN_HEX if ch.ok else RED_HEX
        ws.cell(i, 8).fill = PatternFill("solid", start_color=color, end_color=color)
    for col, w in zip("ABCDEFGH", [58, 8, 20, 12, 22, 12, 12, 14]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    return ws


def apply_marks(wb, checks: list[Check], ftype: str):
    for ch in checks:
        if ch.ok:
            continue
        text = (f"{ch.title} ({ch.year} г.)\n{ch.left_label}: {clean_number(ch.left)}\n"
                f"{ch.right_label}: {clean_number(ch.right)}\nРазлика: {clean_number(ch.left - ch.right)}")
        for t, sheet, r, c in ch.cells:
            if t == ftype and sheet in wb.sheetnames:
                mark(wb[sheet], r + 1, c + 1, text)


# ------------------------------------------------------------------ обобщаване

def _data_cells_10a(f: Form10A) -> dict[str, list[tuple[int, int]]]:
    return {f.opr: [(r, c) for r in f.opr_rows.values() for c in f.years],
            f.bal: [(r, c) for r in f.bal_rows.values() for c in f.years]}


def _sum_cells(grids: list[Grid], base_grid: Grid, coords: dict[str, list[tuple[int, int]]]):
    """Сумира по позиция; листовете се съпоставят по ред (първи, втори...)."""
    base_names = list(base_grid)
    out: dict[str, dict[tuple[int, int], float]] = {}
    for sname, cells in coords.items():
        idx = base_names.index(sname)
        acc = {}
        for r, c in cells:
            total, seen = 0.0, False
            for g in grids:
                names = list(g)
                key = sname if sname in g else (names[idx] if idx < len(names) else None)
                if key is None:
                    continue
                rows = g[key]
                if r < len(rows) and c < len(rows[r]):
                    v = to_number(rows[r][c])
                    if v is not None:
                        total += v
                        seen = True
            if seen:
                acc[(r, c)] = total
        out[sname] = acc
    return out


def _write_sums(wb, sums: dict[str, dict[tuple[int, int], float]], base_grid: Grid):
    base_names = list(base_grid)
    for sname, cells in sums.items():
        ws = wb[sname] if sname in wb.sheetnames else wb.worksheets[base_names.index(sname)]
        for (r, c), v in cells.items():
            cell = ws.cell(r + 1, c + 1)
            if type(cell).__name__ == "MergedCell" or is_formula(cell.value):
                continue
            cell.value = clean_number(v)


def _generic_numeric_cells(grids: list[Grid], base_grid: Grid) -> dict[str, list[tuple[int, int]]]:
    """Клетки с числа, които трябва да се сумират (без заглавни редове с години/номера на колони)."""
    out: dict[str, list[tuple[int, int]]] = {}
    for idx, sname in enumerate(base_grid):
        coords: dict[tuple[int, int], list] = {}
        for g in grids:
            names = list(g)
            key = sname if sname in g else (names[idx] if idx < len(names) else None)
            if key is None:
                continue
            for r, row in enumerate(g[key]):
                for c, v in enumerate(row):
                    n = to_number(v) if not isinstance(v, str) else None
                    if n is not None:
                        coords.setdefault((r, c), []).append(n)
        rows = base_grid[sname]
        keep = []
        for (r, c), vals in coords.items():
            row = rows[r] if r < len(rows) else []
            texts = " ".join(str(x) for x in row if isinstance(x, str)).lower()
            if all(float(v).is_integer() and 2000 <= v <= 2100 for v in vals):
                continue  # години в заглавията
            if any(w in texts for w in ("прогноза", "отчет")) and not re.search(r"[а-я]{4,}.*[а-я]{4,}.*[а-я]{4,}", texts.replace("прогноза", "").replace("отчет", "")):
                continue
            if len(vals) == len(grids) and len(set(vals)) == 1 and not any(isinstance(x, str) and len(x) > 3 for x in row[:c]):
                continue  # номера на колони и други еднакви служебни числа
            keep.append((r, c))
        out[sname] = keep
    return out


def _set_name(ws, text: str, grid_rows: list[list], hint_rows=(1, 2, 3, 4, 5)):
    """Записва името на групата там, където е името на заведението."""
    for r, row in enumerate(grid_rows[:8]):
        for c, v in enumerate(row):
            if isinstance(v, str) and "наименование на заемополучателя" in v.lower() and r > 0:
                ws.cell(r, c + 1).value = text   # редът над надписа (1-базиран = r)
                return


def consolidate_list(base: Path, sources: list[Path], dst: Path, title_text: str | None = None) -> Path:
    """Обединява таблици-списъци (напр. 4а) - редовете на всички се подреждат един под друг."""
    from copy import copy
    wb, ext = open_for_edit(base)
    ws = wb.worksheets[0]
    g0 = load_grid(base)
    rows0 = list(g0.values())[0]
    hdr_r, num_c = None, None
    for r, row in enumerate(rows0[:30]):
        for c, v in enumerate(row):
            if isinstance(v, str) and v.strip() == "№":
                hdr_r, num_c = r, c
                break
        if hdr_r is not None:
            break
    if hdr_r is None:
        return consolidate_sheets(sources, dst)
    collected = []
    for src in sources:
        rows = list(load_grid(src).values())[0]
        for r in range(hdr_r + 1, len(rows)):
            row = rows[r]
            body = row[num_c + 1:] if num_c + 1 < len(row) else []
            if any(v not in (None, "") for v in body):
                collected.append(row)
    # изчистване на старите редове
    first = hdr_r + 2
    width = max([len(r) for r in collected] + [ws.max_column])
    for r in range(first, max(ws.max_row, first + len(collected)) + 1):
        for c in range(num_c + 1, width + 1):
            cell = ws.cell(r, c)
            if type(cell).__name__ != "MergedCell":
                cell.value = None
    for i, row in enumerate(collected):
        rr = first + i
        for c in range(num_c, len(row)):
            cell = ws.cell(rr, c + 1)
            if type(cell).__name__ == "MergedCell":
                continue
            v = row[c]
            cell.value = (i + 1) if c == num_c else (clean_number(v) if isinstance(v, float) else v)
            src_style = ws.cell(first, c + 1)
            if rr != first and src_style.has_style:
                cell._style = copy(src_style._style)
    out = dst.with_suffix(ext)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def consolidate_sheets(sources: list[tuple[str, Path]] | list[Path], dst: Path) -> Path:
    """Събира приложенията на всички в един файл - по един лист за всяко заведение."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for item in sources:
        name, path = item if isinstance(item, tuple) else (item.parent.name, item)
        g = load_grid(path)
        rows = list(g.values())[0] if g else []
        title = re.sub(r"[\[\]\*\?/\\:]", " ", name)[:31] or "Лист"
        base, k = title, 2
        while title in wb.sheetnames:
            title = f"{base[:28]} {k}"
            k += 1
        ws = wb.create_sheet(title)
        for r, row in enumerate(rows, start=1):
            for c, v in enumerate(row, start=1):
                if v is not None:
                    ws.cell(r, c, v)
    out = dst.with_suffix(".xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def consolidate_sum(base: Path, sources: list[Path], dst: Path, coords_fn, name_text: str | None,
                    name_fn=None, names: list[str] | None = None) -> tuple[Path, Grid]:
    """Обобщава чрез сумиране. Ако са дадени имена, листовете на всяко заведение се добавят
    в същия файл, а обобщените клетки стават формули, които сочат към тях."""
    grids = [load_grid(s) for s in sources]
    base_grid = load_grid(base)
    coords = coords_fn(grids, base_grid)
    sums = _sum_cells(grids, base_grid, coords)
    wb, ext = open_for_edit(base)
    _write_sums(wb, sums, base_grid)
    if names:
        base_names = list(base_grid)
        # листове на заведенията: titles[i][j] = име на копието на j-тия лист на i-тото заведение
        titles: list[list[str | None]] = []
        for name, src in zip(names, sources):
            swb, _ = open_for_edit(src)
            row_titles = []
            for j, sws in enumerate(swb.worksheets[:len(base_names)]):
                short = re.sub(r"(?i)приходи\s*\+\s*разходи", "ОПР", sws.title)
                t = name if len(base_names) == 1 else f"{name[:20]} - {short[:8]}"
                new_ws = copy_sheet(sws, wb, t)
                new_ws.sheet_properties.tabColor = "92D050"
                row_titles.append(new_ws.title)
            row_titles += [None] * (len(base_names) - len(row_titles))
            titles.append(row_titles)
        for sname, cells in sums.items():
            j = base_names.index(sname)
            ws = wb.worksheets[j]
            for (r, c) in cells:
                cell = ws.cell(r + 1, c + 1)
                if type(cell).__name__ == "MergedCell" or is_formula(cell.value):
                    continue
                refs = [sheet_ref(t[j], r + 1, c + 1) for t in titles if t[j]]
                if refs:
                    cell.value = "=" + "+".join(refs)
        wb.calculation.fullCalcOnLoad = True
    if name_text and name_fn:
        name_fn(wb, base_grid, name_text)
    # обобщена решетка за проверките (вкл. стойностите на формулите)
    summed = {k: [list(r) for r in v] for k, v in base_grid.items()}
    for sname, cells in sums.items():
        for (r, c), v in cells.items():
            summed[sname][r][c] = v
    out = dst.with_suffix(ext)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out, summed


# ------------------------------------------------------------------ цялостен процес

@dataclass
class Result:
    hospital: str
    group: str
    checks_failed: int = 0
    checks_total: int = 0
    notes: list[str] = field(default_factory=list)


def run(root: Path, groups: dict[str, str], rzi_name: str = "РЗИ ПАЗАРДЖИК",
        log: Callable[[str], None] = print, progress: Callable[[int, int], None] | None = None):
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    root = Path(root)
    out_root = ready_folder(root)
    hospitals = scan(root)
    log(f"Намерени заведения: {len(hospitals)}")
    results: list[Result] = []
    steps = len(hospitals) + len(GROUPS)
    step = 0

    # 1) Проверка на всяко заведение поотделно
    for h in hospitals:
        step += 1
        if progress:
            progress(step, steps)
        grp = groups.get(h.name, GROUPS[0])
        res = Result(h.name, grp)
        results.append(res)
        missing = [TYPE_LABEL[k] for k, *_ in TYPES if k not in h.files]
        if missing:
            res.notes.append("липсват: " + ", ".join(missing))
        for t, p in h.files.items():
            if t in ("10A", "12B"):
                continue
            safe_copy(p, out_root / p.relative_to(root))
        for p in h.extra:
            safe_copy(p, out_root / p.relative_to(root))
        p10 = h.files.get("10A")
        p12 = h.files.get("12B")
        try:
            g10 = load_grid(p10) if p10 else None
            g12 = load_grid(p12) if p12 else None
            f10 = parse_10a(g10) if g10 else None
            checks = checks_10a(g10, f10, g12) if f10 else []
            res.checks_total = len(checks)
            res.checks_failed = sum(1 for c in checks if not c.ok)
            if p10:
                wb, ext = open_for_edit(p10)
                apply_marks(wb, checks, "10A")
                write_checks_sheet(wb, checks)
                dst = (out_root / p10.relative_to(root)).with_suffix(ext)
                dst.parent.mkdir(parents=True, exist_ok=True)
                wb.save(dst)
            if p12:
                wb, ext = open_for_edit(p12)
                apply_marks(wb, checks, "12B")
                dst = (out_root / p12.relative_to(root)).with_suffix(ext)
                dst.parent.mkdir(parents=True, exist_ok=True)
                wb.save(dst)
            status = "всички проверки са ОК" if not res.checks_failed else f"НЕСЪОТВЕТСТВИЯ: {res.checks_failed}"
            log(f"  {'✓' if not res.checks_failed else '✗'} {h.name} ({grp}): {status}"
                + (f"; {res.notes[0]}" if res.notes else ""))
        except Exception as e:  # noqa: BLE001
            res.notes.append(f"грешка: {e}")
            log(f"  ✗ {h.name}: грешка: {e}")

    # 2) Обобщени файлове за ДЛЗБП и ОЛЗБП
    summary_dir = out_root / "ОБОБЩЕНИ"
    for grp in GROUPS:
        step += 1
        if progress:
            progress(step, steps)
        members = [h for h in hospitals if groups.get(h.name, GROUPS[0]) == grp]
        if not members:
            continue
        log(f"Обобщаване на {grp} ({len(members)} заведения) ...")
        label = f"{grp} - {rzi_name}"
        g10_sum = None
        g12_sum = None
        out10 = None
        for t, *_ in TYPES:
            srcs = [h.files[t] for h in members if t in h.files]
            names = [h.name for h in members if t in h.files]
            if not srcs:
                continue
            base = next((s for s in srcs if s.suffix.lower() in (".xlsx", ".xlsm")), srcs[0])
            dst = summary_dir / f"{OUT_NAME[t]} {grp}"
            try:
                if t == "10A":
                    def coords10(grids, bg):
                        f = parse_10a(bg)
                        return _data_cells_10a(f)

                    def name10(wb, bg, text):
                        wb.worksheets[0]["A4"] = text
                        if len(wb.worksheets) > 1:
                            wb.worksheets[1]["A4"] = text
                    out10, g10_sum = consolidate_sum(base, srcs, dst, coords10, label, name10, names)
                elif t == "12B":
                    def coords12(grids, bg):
                        p = parse_12b(bg)
                        rows = [p[k] for k in ("Задължения", "Вземания") if k in p]
                        return {p["sheet"]: [(r, c) for r in rows for c in p["years"].values()]}
                    out12, g12_sum = consolidate_sum(base, srcs, dst, coords12, None, None, names)
                elif t == "4A":
                    consolidate_list(base, srcs, dst)
                elif t == "6A":
                    consolidate_sheets([(h.name, h.files[t]) for h in members if t in h.files], dst)
                else:
                    def name6(wb, bg, text):
                        _set_name(wb.worksheets[0], text, list(bg.values())[0])
                    consolidate_sum(base, srcs, dst, _generic_numeric_cells, label, name6, names)
                log(f"  ✓ {TYPE_LABEL[t]} {grp}: обобщени {len(srcs)} файла")
            except Exception as e:  # noqa: BLE001
                log(f"  ✗ {TYPE_LABEL[t]} {grp}: грешка: {e}")
        # проверки на обобщения 10а
        if g10_sum is not None and out10 is not None:
            f = parse_10a(g10_sum)
            checks = checks_10a(g10_sum, f, g12_sum)
            wb = openpyxl.load_workbook(out10, keep_vba=out10.suffix.lower() == ".xlsm")
            apply_marks(wb, checks, "10A")
            write_checks_sheet(wb, checks)
            wb.save(out10)
            bad = sum(1 for c in checks if not c.ok)
            log(f"  {'✓' if not bad else '✗'} Проверки на обобщения 10а {grp}: "
                + ("ОК" if not bad else f"несъответствия: {bad}"))

    # 3) Обобщителен отчет
    out_root.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Обобщение"
    ws.append(["Заведение", "Група", "Проверки", "Несъответствия", "Бележки"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in results:
        ws.append([r.hospital, r.group, r.checks_total, r.checks_failed, "; ".join(r.notes)])
        color = RED_HEX if r.checks_failed else GREEN_HEX
        ws.cell(ws.max_row, 4).fill = PatternFill("solid", start_color=color, end_color=color)
    for col, w in zip("ABCDE", [45, 10, 10, 15, 80]):
        ws.column_dimensions[col].width = w
    summary = out_root / "Обобщение на проверките.xlsx"
    wb.save(summary)
    log(f"Готово. Резултатите са в: {out_root}")
    return summary, results

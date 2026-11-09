"""Екраните на трите задачи."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import annual_compare, budget_lzbp, municipal
from ..settings import Settings
from .widgets import FolderPicker, RunPanel, Worker, hline, legend_label, open_path, title_label


class TaskPage(QWidget):
    finished = Signal(str, str)   # заглавие, съобщение

    title = ""
    subtitle = ""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.worker: Worker | None = None
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 18, 24, 18)
        self.root.addWidget(title_label(self.title, self.subtitle))
        self.root.addWidget(hline())

    def start(self, fn, *args, **kwargs):
        if self.worker and self.worker.isRunning():
            return
        self.panel.log.clear()
        self.panel.open_btn.setEnabled(False)
        self.panel.button.setEnabled(False)
        self.worker = Worker(fn, *args, **kwargs)
        self.worker.log.connect(self.panel.append)
        self.worker.progress.connect(self.panel.set_progress)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def result_folder(self, res) -> Path | None:
        return None

    def _done(self, res):
        self.panel.button.setEnabled(True)
        folder = self.result_folder(res)
        if folder:
            self.panel.result_path = str(folder)
            self.panel.open_btn.setEnabled(True)
            if self.s.get("open_ready_folder"):
                open_path(folder)
        self.finished.emit(self.title, "Обработката завърши успешно.")

    def _failed(self, msg):
        self.panel.button.setEnabled(True)
        self.panel.append("ГРЕШКА: " + msg.splitlines()[0])
        QMessageBox.critical(self, "Грешка", msg)
        self.finished.emit(self.title, "Обработката завърши с грешка.")


# ------------------------------------------------------------------ Годишни отчети

class AnnualPage(TaskPage):
    title = "Годишни отчети ЛЗБП"
    subtitle = ("Сравнява отчетите от новата година с една или няколко предходни години и оцветява разликите. "
                "Резултатът се записва в папка със същото име и добавка „ГОТОВИ“.")

    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        box = QGroupBox("Папки")
        b = QVBoxLayout(box)
        b.addWidget(QLabel("Папка с отчетите за новата година (напр. G:\\ГОДИШНИ ОТЧЕТИ\\2025):"))
        self.new = FolderPicker()
        self.new.set_path(self.s.get_json("annual_new", ""))
        b.addWidget(self.new)
        b.addWidget(QLabel("Папки с предходни години (първата е основната за цветовете):"))
        row = QHBoxLayout()
        self.olds = QListWidget()
        self.olds.setMaximumHeight(90)
        self.olds.setDragDropMode(QAbstractItemView.InternalMove)
        for p in self.s.get_json("annual_old", []):
            self.olds.addItem(p)
        col = QVBoxLayout()
        add = QPushButton("Добави...")
        rem = QPushButton("Премахни")
        add.clicked.connect(self.add_old)
        rem.clicked.connect(lambda: [self.olds.takeItem(self.olds.row(i)) for i in self.olds.selectedItems()])
        col.addWidget(add)
        col.addWidget(rem)
        col.addStretch(1)
        row.addWidget(self.olds, 1)
        row.addLayout(col)
        b.addLayout(row)
        self.legend = legend_label(self.s.get("thr_low"), self.s.get("thr_mid"), self.s.get("thr_high"))
        b.addWidget(self.legend)
        self.root.addWidget(box)
        self.panel = RunPanel("Сравни")
        self.panel.button.clicked.connect(self.run)
        self.root.addWidget(self.panel, 1)
        self.new.changed.connect(self.autofill_old)

    def add_old(self):
        start = str(Path(self.new.path()).parent) if self.new.path() else str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "Папка с предходна година", start)
        if d:
            self.olds.addItem(str(Path(d)))

    def autofill_old(self, p):
        """Ако е избрана папка „2025“, предлага „2024“ до нея."""
        if self.olds.count() or not p:
            return
        path = Path(p)
        if path.name.isdigit():
            prev = path.parent / str(int(path.name) - 1)
            if prev.is_dir():
                self.olds.addItem(str(prev))

    def refresh_legend(self):
        new = legend_label(self.s.get("thr_low"), self.s.get("thr_mid"), self.s.get("thr_high"))
        self.legend.setText(new.text())

    def run(self):
        new = self.new.path()
        olds = [self.olds.item(i).text() for i in range(self.olds.count())]
        if not new or not Path(new).is_dir():
            QMessageBox.warning(self, "Липсва папка", "Изберете папката с отчетите за новата година.")
            return
        if not olds:
            QMessageBox.warning(self, "Липсва папка", "Добавете поне една папка с предходна година.")
            return
        self.s.set_json("annual_new", new)
        self.s.set_json("annual_old", olds)
        t = annual_compare.Thresholds(self.s.get("thr_low"), self.s.get("thr_mid"), self.s.get("thr_high"))
        self.start(annual_compare.run_comparison, Path(new), [Path(o) for o in olds], t)

    def result_folder(self, res):
        summary, _ = res
        return Path(summary).parent


# ------------------------------------------------------------------ Бюджетни прогнози ЛЗБП

class BudgetLzbpPage(TaskPage):
    title = "Бюджетни прогнози ЛЗБП"
    subtitle = ("Проверява Приложение 10а (ОПР срещу Баланс) и 12б и оцветява в червено несъответствията. "
                "Обобщава приложенията на болниците в отделни файлове за ДЛЗБП и ОЛЗБП. "
                "Във входната папка трябва да има по една подпапка за всяко лечебно заведение.")

    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        box = QGroupBox("Входна папка и групи")
        b = QVBoxLayout(box)
        b.addWidget(QLabel("Папка с получените приложения (по една подпапка за всяка болница):"))
        self.folder = FolderPicker()
        self.folder.set_path(self.s.get_json("lzbp_folder", ""))
        self.folder.changed.connect(self.reload)
        b.addWidget(self.folder)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Лечебно заведение", "Група", "Намерени приложения"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(150)
        b.addWidget(self.table)
        self.root.addWidget(box)
        self.panel = RunPanel("Провери и обобщи")
        self.panel.button.clicked.connect(self.run)
        self.root.addWidget(self.panel, 1)
        self.reload(self.folder.path())

    def groups(self) -> dict:
        return self.s.get_json("hospital_groups", {})

    def reload(self, path):
        self.table.setRowCount(0)
        if not path or not Path(path).is_dir():
            return
        saved = self.groups()
        for h in budget_lzbp.scan(Path(path)):
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QTableWidgetItem(h.name)
            self.table.setItem(r, 0, item)
            combo = QComboBox()
            combo.addItems(list(budget_lzbp.GROUPS) + [budget_lzbp.EXCLUDED])
            combo.setCurrentText(saved.get(h.name, budget_lzbp.GROUPS[0]))
            combo.currentTextChanged.connect(self.save_groups)
            self.table.setCellWidget(r, 1, combo)
            found = ", ".join(budget_lzbp.TYPE_LABEL[k].replace("Приложение ", "") for k, *_ in budget_lzbp.TYPES
                              if k in h.files)
            self.table.setItem(r, 2, QTableWidgetItem(found or "няма разпознати приложения"))
        self.table.resizeColumnToContents(1)

    def save_groups(self, *_):
        g = self.groups()
        for r in range(self.table.rowCount()):
            g[self.table.item(r, 0).text()] = self.table.cellWidget(r, 1).currentText()
        self.s.set_json("hospital_groups", g)

    def run(self):
        path = self.folder.path()
        if not path or not Path(path).is_dir():
            QMessageBox.warning(self, "Липсва папка", "Изберете папката с приложенията.")
            return
        self.s.set_json("lzbp_folder", path)
        self.save_groups()
        self.start(budget_lzbp.run, Path(path), self.groups(), self.s.get("rzi_name"))

    def result_folder(self, res):
        summary, _ = res
        return Path(summary).parent


# ------------------------------------------------------------------ Бюджетни прогнози общини

class MunicipalPage(TaskPage):
    title = "Бюджетни прогнози общини"
    subtitle = ("Обобщава Приложение 7в от всички общини в един файл. Средната заплата се изчислява наново "
                "(средства / численост / 12), а във файла на всяка община се оцветява в червено, "
                "ако посочената средна заплата не отговаря на изчислената.")

    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        box = QGroupBox("Входна папка")
        b = QVBoxLayout(box)
        b.addWidget(QLabel("Папка с попълнените Приложения 7в от общините:"))
        self.folder = FolderPicker()
        self.folder.set_path(self.s.get_json("mun_folder", ""))
        b.addWidget(self.folder)
        self.root.addWidget(box)
        self.panel = RunPanel("Обобщи")
        self.panel.button.clicked.connect(self.run)
        self.root.addWidget(self.panel, 1)

    def run(self):
        path = self.folder.path()
        if not path or not Path(path).is_dir():
            QMessageBox.warning(self, "Липсва папка", "Изберете папката с файловете на общините.")
            return
        self.s.set_json("mun_folder", path)
        self.start(municipal.run, Path(path), self.s.get("avg_tolerance_pct"))

    def result_folder(self, res):
        out, _ = res
        return Path(out).parent

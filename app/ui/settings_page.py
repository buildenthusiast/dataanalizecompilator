"""Екран „Настройки“."""
from __future__ import annotations

import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import APP_NAME, VERSION
from ..settings import Settings, autostart_enabled, set_autostart
from .widgets import hline, title_label


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    thresholds_changed = Signal()
    check_updates = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.s = settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(24, 18, 24, 18)
        root.addWidget(title_label("Настройки"))
        root.addWidget(hline())

        # --- общи
        g = QGroupBox("Стартиране и прозорец")
        v = QVBoxLayout(g)
        self.autostart = self._check(v, "Стартирай програмата заедно с Windows", "autostart")
        if sys.platform == "win32":
            self.autostart.setChecked(autostart_enabled())
        self.autostart.toggled.connect(self._autostart)
        self._check(v, "При стартиране с Windows – стартирай скрита до часовника", "start_minimized")
        self._check(v, "При затваряне на прозореца – скрий до часовника (вместо изход)", "minimize_to_tray")
        self._check(v, "Показвай известие, когато обработката приключи", "notify_done")
        self._check(v, "Отваряй папката с резултатите след обработка", "open_ready_folder")
        row = QHBoxLayout()
        row.addWidget(QLabel("Тема:"))
        self.theme = QComboBox()
        self.theme.addItem("Както в Windows", "system")
        self.theme.addItem("Светла", "light")
        self.theme.addItem("Тъмна", "dark")
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.s.get("theme"))))
        self.theme.currentIndexChanged.connect(self._theme)
        row.addWidget(self.theme)
        row.addStretch(1)
        v.addLayout(row)
        root.addWidget(g)

        # --- сравнение
        g = QGroupBox("Годишни отчети – граници на цветовете (промяна в %)")
        f = QFormLayout(g)
        self.low = self._spin(f, "Без цвят под:", "thr_low")
        self.mid = self._spin(f, "Зелено до:", "thr_mid")
        self.high = self._spin(f, "Жълто до (над това – червено):", "thr_high")
        root.addWidget(g)

        # --- бюджет
        g = QGroupBox("Бюджетни прогнози")
        f = QFormLayout(g)
        self.rzi = QLineEdit(self.s.get("rzi_name"))
        self.rzi.editingFinished.connect(lambda: self.s.set("rzi_name", self.rzi.text().strip()))
        f.addRow("Име на РЗИ в обобщените файлове:", self.rzi)
        self._spin(f, "Допустимо отклонение на средната заплата (%):", "avg_tolerance_pct")
        root.addWidget(g)

        # --- обновяване
        g = QGroupBox("Обновяване")
        v = QVBoxLayout(g)
        self._check(v, "Проверявай за нова версия при стартиране", "auto_update")
        f = QFormLayout()
        self.repo = QLineEdit(self.s.get("github_repo"))
        self.repo.setPlaceholderText("потребител/хранилище")
        self.repo.editingFinished.connect(lambda: self.s.set("github_repo", self.repo.text().strip()))
        f.addRow("GitHub хранилище:", self.repo)
        v.addLayout(f)
        row = QHBoxLayout()
        btn = QPushButton("Провери за обновление сега")
        btn.clicked.connect(lambda: (self.s.set("github_repo", self.repo.text().strip()), self.check_updates.emit()))
        row.addWidget(btn)
        row.addStretch(1)
        v.addLayout(row)
        self.update_status = QLabel("")
        v.addWidget(self.update_status)
        root.addWidget(g)

        about = QLabel(f"{APP_NAME} – версия {VERSION}")
        about.setStyleSheet("color: gray;")
        root.addWidget(about)
        root.addStretch(1)

    def _check(self, layout, text, key) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setChecked(self.s.get(key))
        cb.toggled.connect(lambda val, k=key: self.s.set(k, val))
        layout.addWidget(cb)
        return cb

    def _spin(self, form, text, key) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(0, 1000)
        sp.setDecimals(1)
        sp.setSingleStep(0.5)
        sp.setValue(self.s.get(key))

        def changed(val, k=key):
            self.s.set(k, float(val))
            self.thresholds_changed.emit()
        sp.valueChanged.connect(changed)
        form.addRow(text, sp)
        return sp

    def _autostart(self, val):
        self.s.set("autostart", val)
        set_autostart(val)

    def _theme(self):
        val = self.theme.currentData()
        self.s.set("theme", val)
        self.theme_changed.emit(val)

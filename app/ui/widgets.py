"""Общи елементи на интерфейса."""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)


def open_path(path: str | Path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class Worker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = self.fn(*self.args, log=self.log.emit, progress=self.progress.emit, **self.kwargs)
            self.done.emit(res)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class FolderPicker(QWidget):
    changed = Signal(str)

    def __init__(self, placeholder: str = "Изберете папка...", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.path()))
        btn = QPushButton("Избери...")
        btn.clicked.connect(self.browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def browse(self):
        start = self.path() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "Изберете папка", start)
        if d:
            self.set_path(d)
            self.changed.emit(d)

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, p: str):
        self.edit.setText(str(Path(p)) if p else "")


class RunPanel(QWidget):
    """Бутон „Старт“, лента за напредък и дневник."""

    def __init__(self, button_text="Старт", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.button = QPushButton(button_text)
        self.button.setMinimumHeight(36)
        f = self.button.font()
        f.setBold(True)
        self.button.setFont(f)
        self.open_btn = QPushButton("Отвори папката с резултатите")
        self.open_btn.setEnabled(False)
        self.open_btn.setMinimumHeight(36)
        row.addWidget(self.button, 1)
        row.addWidget(self.open_btn)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.log.setFont(mono)
        lay.addWidget(self.log, 1)
        self.result_path = None
        self.open_btn.clicked.connect(lambda: self.result_path and open_path(self.result_path))

    def append(self, text: str):
        self.log.appendPlainText(text)

    def set_progress(self, i: int, total: int):
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(i)


def legend_label(low, mid, high) -> QLabel:
    def chip(color, text):
        return (f'<span style="background:{color};color:#000;padding:2px 8px;border-radius:3px">'
                f'&nbsp;{text}&nbsp;</span>')
    html = ("Цветове: "
            + chip("#ffffff", f"под {low:g}% – без цвят") + " "
            + chip("#C6EFCE", f"{low:g}–{mid:g}%") + " "
            + chip("#FFEB9C", f"над {mid:g}–{high:g}%") + " "
            + chip("#FFC7CE", f"над {high:g}% или ново/липсващо"))
    lbl = QLabel(html)
    lbl.setTextFormat(Qt.RichText)
    lbl.setWordWrap(True)
    return lbl


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def title_label(text: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    t = QLabel(text)
    f = t.font()
    f.setPointSize(f.pointSize() + 6)
    f.setBold(True)
    t.setFont(f)
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setWordWrap(True)
        s.setStyleSheet("color: #6b6b6b;")
        lay.addWidget(s)
    return w

"""Главен прозорец: меню вляво, задачи вдясно, икона до часовника."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QProgressDialog, QStackedWidget, QStyle,
                               QSystemTrayIcon, QWidget)

from .. import APP_NAME, VERSION, updater
from ..settings import Settings
from .pages import AnnualPage, BudgetLzbpPage, MunicipalPage
from .settings_page import SettingsPage


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1f6feb"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    bars = [(12, 34, "#C6EFCE"), (26, 22, "#FFEB9C"), (40, 12, "#FFC7CE")]
    for x, top, col in bars:
        p.setBrush(QColor(col))
        p.drawRoundedRect(x, top, 11, 52 - top, 3, 3)
    p.end()
    return QIcon(pm)


def apply_theme(app: QApplication, theme: str):
    app.setStyle("Fusion")
    if theme == "dark":
        pal = QPalette()
        base, alt, text = QColor(37, 37, 38), QColor(45, 45, 48), QColor(230, 230, 230)
        pal.setColor(QPalette.Window, alt)
        pal.setColor(QPalette.WindowText, text)
        pal.setColor(QPalette.Base, base)
        pal.setColor(QPalette.AlternateBase, alt)
        pal.setColor(QPalette.ToolTipBase, base)
        pal.setColor(QPalette.ToolTipText, text)
        pal.setColor(QPalette.Text, text)
        pal.setColor(QPalette.Button, alt)
        pal.setColor(QPalette.ButtonText, text)
        pal.setColor(QPalette.Highlight, QColor("#1f6feb"))
        pal.setColor(QPalette.HighlightedText, Qt.white)
        pal.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
        pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
        app.setPalette(pal)
    elif theme == "light":
        app.setPalette(app.style().standardPalette())
    else:
        app.setPalette(QPalette())
        try:
            from PySide6.QtCore import Qt as _Qt
            scheme = app.styleHints().colorScheme()
            if scheme == _Qt.ColorScheme.Dark:
                apply_theme(app, "dark")
        except Exception:  # noqa: BLE001
            pass


class UpdateCheck(QThread):
    result = Signal(object, str)

    def __init__(self, repo):
        super().__init__()
        self.repo = repo

    def run(self):
        try:
            self.result.emit(updater.latest_release(self.repo), "")
        except Exception as e:  # noqa: BLE001
            self.result.emit(None, str(e))


class Download(QThread):
    progress = Signal(int, int)
    done = Signal(str, str)

    def __init__(self, url, suffix=".exe"):
        super().__init__()
        self.url, self.suffix = url, suffix

    def run(self):
        try:
            self.done.emit(updater.download(self.url, self.progress.emit, self.suffix), "")
        except Exception as e:  # noqa: BLE001
            self.done.emit("", str(e))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.s = settings
        self.icon = make_icon()
        self.setWindowIcon(self.icon)
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(1100, 720)
        self._really_quit = False
        self._tray_hint_shown = False

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setFixedWidth(250)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setIconSize(QSize(22, 22))
        self.nav.setStyleSheet("""
            QListWidget { border: none; padding-top: 10px; background: palette(alternate-base); }
            QListWidget::item { padding: 10px 12px; margin: 2px 8px; border-radius: 6px; }
            QListWidget::item:selected { background: #1f6feb; color: white; }
        """)
        f = self.nav.font()
        f.setPointSize(f.pointSize() + 1)
        self.nav.setFont(f)
        self.stack = QStackedWidget()
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        st = self.style()
        self.annual = AnnualPage(self.s)
        self.lzbp = BudgetLzbpPage(self.s)
        self.mun = MunicipalPage(self.s)
        self.settings_page = SettingsPage(self.s)
        pages = [
            ("Годишни отчети ЛЗБП", st.standardIcon(QStyle.SP_FileDialogContentsView), self.annual),
            ("Бюджетни прогнози ЛЗБП", st.standardIcon(QStyle.SP_FileDialogDetailedView), self.lzbp),
            ("Бюджетни прогнози общини", st.standardIcon(QStyle.SP_DirIcon), self.mun),
            ("Настройки", st.standardIcon(QStyle.SP_FileDialogListView), self.settings_page),
        ]
        for name, icon, page in pages:
            QListWidgetItem(icon, name, self.nav)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._page)
        self.nav.setCurrentRow(min(self.s.get("last_page"), len(pages) - 1))

        for p in (self.annual, self.lzbp, self.mun):
            p.finished.connect(self.notify)
        self.settings_page.theme_changed.connect(lambda t: apply_theme(QApplication.instance(), t))
        self.settings_page.thresholds_changed.connect(self.annual.refresh_legend)
        self.settings_page.check_updates.connect(lambda: self.check_updates(manual=True))

        self._setup_tray()
        if self.s.get("auto_update") and self.s.get("github_repo"):
            QTimer.singleShot(4000, lambda: self.check_updates(manual=False))

    # ------------------------------------------------------------ навигация
    def _page(self, i):
        self.stack.setCurrentIndex(i)
        self.s.set("last_page", i)

    # ------------------------------------------------------------ трей
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        act_show = QAction("Покажи", self)
        act_show.triggered.connect(self.show_normal)
        menu.addAction(act_show)
        for i, name in enumerate(["Годишни отчети ЛЗБП", "Бюджетни прогнози ЛЗБП", "Бюджетни прогнози общини"]):
            a = QAction(name, self)
            a.triggered.connect(lambda _=False, idx=i: (self.nav.setCurrentRow(idx), self.show_normal()))
            menu.addAction(a)
        menu.addSeparator()
        act_upd = QAction("Провери за обновление", self)
        act_upd.triggered.connect(lambda: self.check_updates(manual=True))
        menu.addAction(act_upd)
        act_quit = QAction("Изход", self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_normal() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()
        self._tray_menu = menu

    def show_normal(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def notify(self, title, msg):
        if self.s.get("notify_done") and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, msg, self.icon, 5000)

    def closeEvent(self, e):
        if not self._really_quit and self.s.get("minimize_to_tray") and QSystemTrayIcon.isSystemTrayAvailable():
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage(APP_NAME, "Програмата продължава да работи до часовника. "
                                                "Десен бутон върху иконата → Изход за затваряне.", self.icon, 4000)
                self._tray_hint_shown = True
            return
        self.tray.hide()
        e.accept()
        QApplication.instance().quit()

    def quit(self):
        busy = any(p.worker and p.worker.isRunning() for p in (self.annual, self.lzbp, self.mun))
        if busy and QMessageBox.question(self, "Изход", "Има обработка в момента. Да се затвори ли програмата?") \
                != QMessageBox.Yes:
            return
        self._really_quit = True
        self.close()

    # ------------------------------------------------------------ обновяване
    def check_updates(self, manual: bool):
        repo = self.s.get("github_repo")
        if not repo:
            if manual:
                QMessageBox.information(self, "Обновяване", "Въведете GitHub хранилище в Настройки.")
            return
        self.settings_page.update_status.setText("Проверка...")
        self._chk = UpdateCheck(repo)
        self._chk.result.connect(lambda info, err: self._update_result(info, err, manual))
        self._chk.start()

    def _update_result(self, info, err, manual):
        if err:
            self.settings_page.update_status.setText(f"Неуспешна проверка: {err}")
            if manual:
                QMessageBox.warning(self, "Обновяване", f"Неуспешна проверка за обновление:\n{err}")
            return
        if not info or not updater.is_newer(info.version):
            self.settings_page.update_status.setText(f"Използвате най-новата версия ({VERSION}).")
            if manual:
                QMessageBox.information(self, "Обновяване", f"Използвате най-новата версия ({VERSION}).")
            return
        self.settings_page.update_status.setText(f"Налична е нова версия: {info.version}")
        notes = (info.notes[:800] + "...") if len(info.notes) > 800 else info.notes
        if QMessageBox.question(self, "Нова версия",
                                f"Налична е нова версия {info.version} (сега: {VERSION}).\n\n{notes}\n\n"
                                "Да се изтегли и инсталира ли сега?") != QMessageBox.Yes:
            return
        self._source_mode = not updater.is_frozen()
        url = info.zip_url if self._source_mode else info.url
        if not url:
            QMessageBox.warning(self, "Обновяване", "В изданието липсва файл за изтегляне.")
            return
        self._dlg = QProgressDialog("Изтегляне на новата версия...", "Отказ", 0, 100, self)
        self._dlg.setWindowModality(Qt.WindowModal)
        self._dlg.show()
        self._dl = Download(url, ".zip" if self._source_mode else ".exe")
        self._dl.progress.connect(lambda d, t: self._dlg.setValue(int(d * 100 / max(t, 1))))
        self._dl.done.connect(self._downloaded)
        self._dl.start()

    def _downloaded(self, path, err):
        self._dlg.close()
        if err:
            QMessageBox.warning(self, "Обновяване", f"Грешка при изтегляне:\n{err}")
            return
        try:
            ok = updater.install_source_update(path) if self._source_mode else updater.install_and_restart(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Обновяване", f"Грешка при инсталиране:\n{e}")
            return
        if ok:
            self._really_quit = True
            self.close()
        else:
            QMessageBox.information(self, "Обновяване",
                                    f"Новата версия е изтеглена тук:\n{path}\n\n"
                                    "Автоматичната подмяна работи само в инсталираната .exe версия.")

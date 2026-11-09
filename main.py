"""Стартов файл на програмата."""
from __future__ import annotations

import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app import APP_ID, APP_NAME
from app.settings import Settings
from app.ui.main_window import MainWindow, apply_theme


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    # Само едно копие на програмата: второто стартиране показва вече отворения прозорец
    sock = QLocalSocket()
    sock.connectToServer(APP_ID)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(APP_ID)
    server = QLocalServer()
    server.listen(APP_ID)

    settings = Settings()
    apply_theme(app, settings.get("theme"))
    win = MainWindow(settings)

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(win.show_normal)
            win.show_normal()
    server.newConnection.connect(on_conn)

    minimized = "--minimized" in sys.argv and settings.get("start_minimized")
    if not minimized:
        win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

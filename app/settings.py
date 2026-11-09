"""Настройки на програмата (пазят се в регистъра на Windows чрез QSettings)."""
from __future__ import annotations

import json
import os
import sys

from PySide6.QtCore import QSettings

from . import APP_ID, DEFAULT_REPO

DEFAULTS = {
    "autostart": False,
    "start_minimized": False,
    "minimize_to_tray": True,
    "notify_done": True,
    "auto_update": True,
    "github_repo": DEFAULT_REPO,
    "theme": "system",            # system / light / dark
    "open_ready_folder": True,
    "thr_low": 1.0,
    "thr_mid": 5.0,
    "thr_high": 10.0,
    "rzi_name": "РЗИ ПАЗАРДЖИК",
    "avg_tolerance_pct": 1.0,
    "mun_avg_mode": "formula",     # formula / sum
    "last_page": 0,
}


class Settings:
    def __init__(self):
        self.q = QSettings(APP_ID, APP_ID)

    def get(self, key):
        default = DEFAULTS.get(key)
        v = self.q.value(key, default)
        if isinstance(default, bool):
            return v in (True, "true", "1", 1)
        if isinstance(default, float):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
        if isinstance(default, int):
            try:
                return int(v)
            except (TypeError, ValueError):
                return default
        return v

    def set(self, key, value):
        self.q.setValue(key, value)
        self.q.sync()

    def get_json(self, key, default):
        raw = self.q.value(key, None)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default

    def set_json(self, key, value):
        self.set(key, json.dumps(value, ensure_ascii=False))


# ---------------------------------------------------------------- автостарт

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def exe_command(minimized: bool = True) -> str:
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        main = os.path.abspath(sys.argv[0])
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        cmd = f'"{pyw}" "{main}"'
    return cmd + (" --minimized" if minimized else "")


def set_autostart(enabled: bool) -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, exe_command(True))
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass
    return True


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, APP_ID)
            return True
    except FileNotFoundError:
        return False

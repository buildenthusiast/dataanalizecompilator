"""Обновяване от GitHub Releases.

Всяко издание (release) в GitHub трябва да има прикачен файл DataAnalizeCompilator.exe
и етикет (tag) с номер на версия, напр. v0.2.0.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass

from . import APP_ID, VERSION

ASSET_NAME = f"{APP_ID}.exe"


@dataclass
class ReleaseInfo:
    version: str
    url: str          # линк за сваляне на .exe
    page: str         # страница на изданието
    notes: str


def _ver(s: str) -> tuple:
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str = VERSION) -> bool:
    return _ver(remote) > _ver(local)


def latest_release(repo: str, timeout: float = 10) -> ReleaseInfo | None:
    if not repo or "/" not in repo:
        raise ValueError("Не е зададено GitHub хранилище (във вида потребител/хранилище).")
    req = urllib.request.Request(f"https://api.github.com/repos/{repo.strip()}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": APP_ID})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower() == ASSET_NAME.lower()), None)
    if asset is None:
        asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")), None)
    if asset is None:
        return None
    return ReleaseInfo(data.get("tag_name", ""), asset["browser_download_url"], data.get("html_url", ""),
                       data.get("body", "") or "")


def download(url: str, progress=None) -> str:
    fd, path = tempfile.mkstemp(suffix=".exe", prefix=APP_ID + "_")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": APP_ID})
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done, total)
    return path


def install_and_restart(new_exe: str) -> bool:
    """Заменя текущия .exe с новия и рестартира програмата."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return False
    current = sys.executable
    ps1 = os.path.join(tempfile.gettempdir(), f"{APP_ID}_update.ps1")
    # PowerShell скрипт (UTF-8 с BOM), за да работят и пътища на кирилица
    script = f"""
$src = '{new_exe.replace("'", "''")}'
$dst = '{current.replace("'", "''")}'
for ($i = 0; $i -lt 60; $i++) {{
    Start-Sleep -Milliseconds 500
    try {{ Move-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop; break }} catch {{ }}
}}
Start-Process -FilePath $dst
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force
"""
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(script)
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", ps1], creationflags=0x08000000)  # CREATE_NO_WINDOW
    return True

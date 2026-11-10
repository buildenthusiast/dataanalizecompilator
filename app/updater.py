"""Обновяване от GitHub Releases.

Всяко издание (release) има етикет с номер на версия (напр. v0.2.0) и файл DataAnalizeCompilator.exe.
Когато програмата работи без .exe (с Python, напр. заради Smart App Control),
се изтегля изходният код на изданието и се разархивира върху папката на програмата.
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
    url: str          # линк за сваляне на .exe ("" ако няма)
    page: str         # страница на изданието
    notes: str
    zip_url: str = "" # изходният код на изданието (за работа без .exe)


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
    return ReleaseInfo(data.get("tag_name", ""), asset["browser_download_url"] if asset else "",
                       data.get("html_url", ""), data.get("body", "") or "", data.get("zipball_url", "") or "")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> str:
    """Папката с main.py (при работа без .exe)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_source_update(zip_path: str) -> bool:
    """Обновяване при работа от изходен код (с Python): разархивира новата версия
    върху папката на програмата, доинсталира библиотеките и рестартира."""
    import shutil
    import zipfile
    root = app_root()
    tmp = tempfile.mkdtemp(prefix=APP_ID + "_src_")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    inner = next((os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))), tmp)
    for name in os.listdir(inner):
        src = os.path.join(inner, name)
        dst = os.path.join(root, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    py = sys.executable
    pyw = py.replace("python.exe", "pythonw.exe") if sys.platform == "win32" else py
    flags = 0x08000000 if sys.platform == "win32" else 0
    req = os.path.join(root, "requirements.txt")
    if os.path.exists(req):
        in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        cmd = [py, "-m", "pip", "install", "-q", "-r", req]
        if not in_venv:
            cmd.insert(4, "--user")
        subprocess.run(cmd, creationflags=flags, check=False)
    launcher = os.path.join(root, "DataAnalizeCompilator.pyw")
    if not os.path.exists(launcher):
        launcher = os.path.join(root, "main.py")
    subprocess.Popen([pyw, launcher], cwd=root, creationflags=flags)
    return True


def download(url: str, progress=None, suffix: str = ".exe") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=APP_ID + "_")
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

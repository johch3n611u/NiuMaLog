"""雙擊啟動 Worklog。

行為：
1. 8000 已經有服務 -> 只開瀏覽器，不再起第二個行程（避免 port 衝突與重複分頁）
2. 否則 -> 背景起 uvicorn（無終端機視窗），等它 ready 再開瀏覽器

用 pythonw.exe 執行時不會出現黑色視窗。
停用自動開瀏覽器：設環境變數 WORKLOG_NO_BROWSER=1
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = os.getenv("WORKLOG_HOST", "127.0.0.1")
PORT = int(os.getenv("WORKLOG_PORT", "8000"))
URL = "http://%s:%d/" % (HOST, PORT)
HEALTH = URL + "api/health"

# Windows：讓子行程脫離本行程，關掉 launcher 也不會帶走 server。
DETACHED = 0x00000008 if os.name == "nt" else 0
NEW_GROUP = 0x00000200 if os.name == "nt" else 0


def already_running() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def start_server() -> None:
    python = sys.executable
    command = [python, "-m", "uvicorn", "apps.api.main:app", "--host", HOST, "--port", str(PORT)]
    subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED | NEW_GROUP,
    )


def main() -> int:
    if already_running():
        # 服務已在跑：不要重啟、不要多開分頁機制以外的東西。
        if os.getenv("WORKLOG_NO_BROWSER") != "1":
            webbrowser.open(URL)
        return 0

    start_server()

    for _ in range(120):
        if already_running():
            break
        time.sleep(0.5)
    else:
        # 等不到就別硬開瀏覽器，讓使用者看到真實錯誤而不是空白頁。
        print("啟動逾時：%s 無回應，請確認 port %d 未被佔用。" % (URL, PORT), file=sys.stderr)
        return 1

    if os.getenv("WORKLOG_NO_BROWSER") != "1":
        webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Desktop integration shared by the local web app on Windows, macOS and Linux."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import webbrowser


ROOT = Path(__file__).resolve().parent
_dialog_lock = threading.Lock()


class DialogError(RuntimeError):
    pass


def pick_path(mode="dir"):
    """Run a native dialog in its own UI process, never a Flask worker thread.

    Returns None on cancellation. No selected path is interpolated into a shell.
    Linux needs the distribution's python3-tk package and a desktop session.
    """
    if mode not in {"dir", "file", "save"}:
        raise ValueError("无效的选择类型")
    if not _dialog_lock.acquire(blocking=False):
        raise DialogError("已有一个选择框打开，请先完成或取消。")
    try:
        options = dict(capture_output=True, text=True, encoding="utf-8", timeout=300)
        if sys.platform == "win32":
            powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            command = [str(powershell), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                       "-File", str(ROOT / "windows_dialog.ps1"), mode]
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        elif sys.platform == "darwin":
            kind = {"dir": "folder", "file": "file", "save": "file name"}[mode]
            script = f'POSIX path of (choose {kind} with prompt "NegativeMaster")'
            result = subprocess.run(["osascript", "-e", script], **options)
            if result.returncode and "(-128)" not in result.stderr:
                raise DialogError(result.stderr.strip() or "系统选择框未能打开")
            return result.stdout.strip() or None
        else:
            command = [sys.executable, str(ROOT / "platform_support.py"), "--dialog", mode]
        result = subprocess.run(command, **options)
        if result.returncode:
            raise DialogError("系统选择框未能打开；也可以直接输入完整路径。" + result.stderr.strip()[-300:])
        return json.loads(result.stdout.lstrip("\ufeff"))["path"] or None
    except subprocess.TimeoutExpired as exc:
        raise DialogError("选择超时，请重新打开选择框。") from exc
    except (OSError, ValueError, KeyError) as exc:
        raise DialogError("系统选择框不可用；请直接输入完整路径。" + str(exc)) from exc
    finally:
        _dialog_lock.release()


def _tk_dialog(mode):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chooser = {"dir": filedialog.askdirectory, "file": filedialog.askopenfilename,
                   "save": filedialog.asksaveasfilename}[mode]
        return chooser(parent=root, title="NegativeMaster") or None
    finally:
        root.destroy()


def launch_background(script, arguments, logpath):
    """Spawn a detached interpreter without POSIX-only fork/setsid calls."""
    options = dict(stdin=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    # Explicit UTF-8 also keeps detached startup/error logs readable on Windows.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    with open(logpath, "ab", buffering=0) as log:
        process = subprocess.Popen([sys.executable, "-u", str(script), *arguments],
                                   stdout=log, stderr=log, env=env, **options)
    # Catch immediate failures (notably port conflicts), rather than reporting success.
    time.sleep(1)
    if process.poll() is not None:
        raise RuntimeError(f"后台服务启动失败，请查看 {logpath}")
    # Reap it if this caller remains alive, while allowing the launching terminal
    # to exit immediately. Retaining the Popen object also avoids false warnings.
    threading.Thread(target=process.wait, daemon=True).start()
    return process.pid


def serve(app, port, open_browser=False):
    """Bind first so browser launch uses the requested port and only a live server."""
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", port, app, threaded=True)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"在浏览器打开: {url}", flush=True)
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--dialog" and sys.argv[2] in {"dir", "file", "save"}:
        try:
            print(json.dumps({"path": _tk_dialog(sys.argv[2])}, ensure_ascii=True))
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1)

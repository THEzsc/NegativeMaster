"""Dependency-aware launcher; requires only Python's standard library."""
from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def environment_python():
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_environment():
    if sys.version_info < (3, 12) or struct.calcsize("P") < 8:
        raise RuntimeError("NegativeMaster requires 64-bit Python 3.12+ (Python 3.13 recommended).")
    python = environment_python()
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    # Check exact installed versions on every run. A failed/interrupted first install
    # or a changed requirements.txt is repaired on the next launch.
    check = """
import importlib.metadata as m, pathlib, sys
if sys.version_info < (3, 12): raise SystemExit(2)
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    if not line.strip() or line.lstrip().startswith('#'): continue
    name, version = line.strip().split('==')
    try: installed = m.version(name)
    except m.PackageNotFoundError: raise SystemExit(1)
    if installed != version: raise SystemExit(1)
"""
    result = subprocess.run([str(python), "-c", check, str(ROOT / "requirements.txt")])
    if result.returncode == 2:
        raise RuntimeError("The existing .venv uses an older Python. Rename .venv, then launch with Python 3.12+.")
    if result.returncode:
        print("Installing NegativeMaster dependencies...", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)
    return python


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"gui", "cli"}:
        print("Usage: python launcher.py gui|cli [application arguments]", file=sys.stderr)
        return 2
    try:
        python = ensure_environment()
        mode, arguments = sys.argv[1], sys.argv[2:]
        if mode == "gui" and "--no-browser" not in arguments and "--open-browser" not in arguments:
            arguments = ["--open-browser", *arguments]
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        return subprocess.call([str(python), str(ROOT / ("gui.py" if mode == "gui" else "decast.py")),
                                *arguments], env=env)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"NegativeMaster startup failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

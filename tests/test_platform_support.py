"""Cross-platform startup, native dialog protocol and filesystem regressions."""
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import urlopen

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decast
import gui
import launcher
import platform_support


class NativeDialogTests(unittest.TestCase):
    def test_invalid_modes_never_launch_a_process(self):
        with patch.object(platform_support.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                platform_support.pick_path("bad")
            run.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows native dialog transport")
    def test_windows_dialog_utf8_path_and_sta(self):
        path = r"D:\照片 & 底片\旅行 01\底片.tif"
        with patch.object(platform_support.subprocess, "run", return_value=Mock(
                returncode=0, stdout=json.dumps({"path": path}, ensure_ascii=False), stderr="")) as run:
            self.assertEqual(platform_support.pick_path("file"), path)
            args, kwargs = run.call_args
            self.assertIn("-STA", args[0])
            self.assertEqual(args[0][-1], "file")
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertNotIn("shell", kwargs)

    @unittest.skipUnless(sys.platform != "darwin", "macOS uses AppleScript cancellation")
    def test_cancellation_is_not_a_transport_failure(self):
        with patch.object(platform_support.subprocess, "run", return_value=Mock(
                returncode=0, stdout='{"path":null}', stderr="")):
            self.assertIsNone(platform_support.pick_path())

    def test_dialog_error_releases_lock(self):
        with patch.object(platform_support.subprocess, "run", side_effect=OSError("unavailable")):
            with self.assertRaises(platform_support.DialogError):
                platform_support.pick_path()
        self.assertFalse(platform_support._dialog_lock.locked())

    def test_only_one_dialog_can_be_open(self):
        platform_support._dialog_lock.acquire()
        try:
            with self.assertRaisesRegex(platform_support.DialogError, "已有"):
                platform_support.pick_path()
        finally:
            platform_support._dialog_lock.release()

    def test_api_reports_cancellation_and_unavailable_dialog(self):
        client = gui.app.test_client()
        with patch.object(platform_support, "pick_path", return_value=None):
            self.assertTrue(client.get("/api/pick").json["cancelled"])
        with patch.object(platform_support, "pick_path", side_effect=platform_support.DialogError("unavailable")):
            response = client.get("/api/pick")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json["err"], "unavailable")
        self.assertEqual(client.get("/api/pick?mode=invalid").status_code, 400)


class FilesystemTests(unittest.TestCase):
    def test_cli_accepts_forward_slash_output_directory_on_windows(self):
        with tempfile.TemporaryDirectory(prefix="negative master ") as temporary:
            output = str(Path(temporary) / "中文输出") + "/"
            target = decast.out_path_for("frame.jpg", output, False, "tif", "_pos")
            self.assertEqual(Path(target), Path(output) / "frame_pos.tif")
            self.assertTrue(Path(output).is_dir())

    def test_gui_load_settings_and_exports_in_unicode_paths(self):
        with tempfile.TemporaryDirectory(prefix="negative master ") as temporary:
            folder = Path(temporary) / "胶片 & 旅行"
            folder.mkdir()
            source = folder / "底片 001.tif"
            pixels = np.arange(72 * 96 * 3, dtype=np.uint8).reshape(72, 96, 3)
            Image.fromarray(pixels).save(source)
            client = gui.app.test_client()
            original_cache = dict(gui.CACHE)
            try:
                with patch.object(gui, "SETTINGS_DIR", str(folder / "设置")):
                    self.assertTrue(client.post("/api/load", json={"path": str(source)}).json["ok"])
                    data = {"P": {"gamma": 1.9}, "cropN": {"x0": .1, "y0": .1, "x1": .9, "y1": .9}}
                    self.assertTrue(client.post("/api/settings", json={"path": str(source), "data": data}).json["ok"])
                    self.assertEqual(client.get("/api/settings", query_string={"path": str(source)}).json["data"], data)
                    for extension, bits in (("jpg", 8), ("tif", 16)):
                        directory = folder / ("导出 " + extension)
                        response = client.post("/api/export", json={"out": str(directory) + os.sep,
                                              "format": extension, "bits": bits, "mode": "positive"})
                        self.assertTrue(response.json["ok"], response.json)
                        target = directory / ("底片 001_pos." + extension)
                        self.assertEqual(Path(response.json["out"]), target)
                        self.assertTrue(target.is_file())
                        self.assertGreater(target.stat().st_size, 100)
            finally:
                gui.CACHE.clear()
                gui.CACHE.update(original_cache)


class LauncherTests(unittest.TestCase):
    def test_incomplete_environment_is_repaired(self):
        with tempfile.TemporaryDirectory() as temporary:
            python = Path(temporary) / "python.exe"
            python.touch()
            with patch.object(launcher, "environment_python", return_value=python), \
                    patch.object(launcher.subprocess, "run", side_effect=[Mock(returncode=1), Mock(), Mock()]) as run:
                self.assertEqual(launcher.ensure_environment(), python)
                self.assertIn("-r", run.call_args_list[-1].args[0])

    def test_complete_environment_does_not_require_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            python = Path(temporary) / "python.exe"
            python.touch()
            with patch.object(launcher, "environment_python", return_value=python), \
                    patch.object(launcher.subprocess, "run", return_value=Mock(returncode=0)) as run:
                launcher.ensure_environment()
                self.assertEqual(run.call_count, 1)

    def test_browser_uses_the_bound_port(self):
        server = Mock(server_port=9876)
        with patch("werkzeug.serving.make_server", return_value=server), \
                patch.object(platform_support.threading, "Thread") as thread:
            platform_support.serve(Mock(), 9876, open_browser=True)
            self.assertEqual(thread.call_args.kwargs["args"], ("http://127.0.0.1:9876",))
            server.server_close.assert_called_once()

    def test_real_server_accepts_unicode_start_directory(self):
        with tempfile.TemporaryDirectory(prefix="NegativeMaster 中文 ") as folder:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen([sys.executable, str(platform_support.ROOT / "gui.py"),
                                        folder, "--port", str(port), "--no-browser"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail("Server exited before accepting requests")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/", timeout=.5) as response:
                            self.assertIn(b"local_paths.js", response.read())
                        with urlopen(f"http://127.0.0.1:{port}/sheet", timeout=2) as response:
                            self.assertEqual(response.status, 200)
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    self.fail("Server did not become ready")
            finally:
                process.terminate()
                process.wait(timeout=10)

    def test_real_background_server_returns_a_live_pid_and_writes_utf8_log(self):
        with tempfile.TemporaryDirectory(prefix="NegativeMaster 后台 ") as folder:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            log = Path(folder) / "gui.log"
            pid = platform_support.launch_background(platform_support.ROOT / "gui.py",
                [folder, "--port", str(port), "--no-browser"], log)
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/sheet", timeout=.5) as response:
                            self.assertEqual(response.status, 200)
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    self.fail("Detached server did not become ready")
                self.assertIn("在浏览器打开", log.read_text(encoding="utf-8"))
            finally:
                os.kill(pid, signal.SIGTERM)
                # Windows log handles close asynchronously after TerminateProcess.
                time.sleep(.2)


if __name__ == "__main__":
    unittest.main()

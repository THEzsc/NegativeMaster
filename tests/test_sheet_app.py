"""Contact-sheet regressions use only synthetic images and temporary sidecars."""
import argparse
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from flask import Flask
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sheet_app


def read_xml(text):
    root = ET.fromstring(text)
    params = {p.get("name"): json.loads(p.get("value"))
              for p in root.findall("./params/param")}
    data = {"P": params}
    crop = root.find("crop")
    if crop is not None:
        data["cropN"] = {k: float(crop.get(k)) for k in ("x0", "y0", "x1", "y1")}
    return data


class SheetApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.roll = self.root / "测试胶卷"
        self.roll.mkdir()
        self.settings = self.root / "settings"
        self.settings.mkdir()
        (self.root / "data").mkdir()
        (self.root / "data" / "film_stocks.json").write_text(json.dumps(dict(
            version=1, stocks=[dict(id="test", name="TEST 100", edge_text="TEST 100",
                                   edge_secondary="135", font_style="mono", process="B&W")]
        )), encoding="utf-8")
        self.base_patch = patch.object(sheet_app, "BASE_DIR", self.root)
        self.base_patch.start()
        self.opts_seen = []

        def make_opts(params):
            self.opts_seen.append(dict(params))
            result = argparse.Namespace(**params)
            result.denoise = params.get("denoise", 0)
            result.sharpen_radius = params.get("sharpen_radius", 0)
            result._ref_centers = "unrelated live reference"
            result._ref_cdfs = "unrelated live reference"
            return result

        self.blueprint = sheet_app.create_sheet_blueprint(
            make_opts, read_xml, self.settings_file, lambda: [str(self.roll)])
        app = Flask(__name__)
        app.register_blueprint(self.blueprint)
        self.client = app.test_client()

    def tearDown(self):
        self.blueprint.sheet_executor.shutdown(wait=True)
        for job in self.blueprint.sheet_jobs.values():
            shutil.rmtree(job["cache"], ignore_errors=True)
        self.base_patch.stop()
        self.temp.cleanup()

    def settings_file(self, path):
        return str(self.settings / (Path(path).name + ".json"))

    def image(self, name, color=(80, 120, 160), folder=None, mode="RGB", size=(90, 60)):
        path = (folder or self.roll) / name
        Image.new(mode, size, color).save(path)
        return path

    def xml(self, path, gamma=.85, crop=(.1, .2, .9, .8)):
        root = ET.Element("decastAdjustments")
        params = ET.SubElement(root, "params")
        ET.SubElement(params, "param", name="gamma", value=str(gamma))
        ET.SubElement(root, "crop", **dict(zip(("x0", "y0", "x1", "y1"), map(str, crop))))
        target = Path(str(path) + ".decast.xml")
        target.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
        return target

    def prepared(self, body):
        response = self.client.post("/api/sheet/prepare", json=body)
        self.assertEqual(response.status_code, 200, response.json)
        identifier = response.json["job"]
        return identifier, self.finished("/api/sheet/job/" + identifier)

    def finished(self, route):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            if response.json["state"] != "running":
                return response.json
            time.sleep(.005)
        self.fail("Asynchronous image task did not complete")

    def test_lettering_preview_is_bounded_and_rejects_unknown_styles(self):
        for style in ("citaro","citaro-tall","film-dot","film-stamp"):
            response=self.client.get("/api/sheet/lettering",query_string={"style":style,"text":"FOMAPAN 100"})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.mimetype,"image/png")
            with Image.open(io.BytesIO(response.data)) as im: self.assertEqual(im.size,(800,156))
            response.close()
        response=self.client.get("/api/sheet/lettering?style=missing")
        self.assertEqual(response.status_code,400)

    def test_export_preferred_and_raw_jpeg_pairs_deduplicated(self):
        self.image("FRAME001.JPG", color="black")
        (self.roll / "FRAME001.ARW").write_bytes(b"not decoded")
        jpg = self.image("FRAME001_pos.jpg", color="red")
        tiff = self.image("FRAME001_pos.tif", color="green")
        self.image("FRAME002.JPG", color="white")
        (self.roll / "FRAME002.ARW").write_bytes(b"missing saved adjustment")
        with patch.object(sheet_app.decast, "load_image", side_effect=AssertionError("RAW must not load")):
            identifier, state = self.prepared({"directory": str(self.roll)})
        self.assertEqual(state["state"], "ready")
        self.assertEqual(len(state["items"]), 1)
        self.assertEqual(state["items"][0]["path"], str(tiff))
        self.assertEqual(state["items"][0]["source"], "export")
        self.assertTrue(any("FRAME002" in warning for warning in state["warnings"]))
        thumb = self.client.get(f"/api/sheet/thumb/{identifier}/0")
        self.assertEqual(thumb.mimetype, "image/jpeg")
        thumb.close()
        self.assertEqual(self.opts_seen, [])
        self.assertTrue(jpg.exists())

    def test_saved_xml_wins_honors_crop_and_resizes_before_conversion(self):
        raw = self.roll / "FRAME003.ARW"
        raw.write_bytes(b"synthetic raw")
        xml = self.xml(raw)
        self.image("FRAME003.JPG")
        Path(self.settings_file(str(raw))).write_text(
            json.dumps({"P": {"gamma": 2.4}}), encoding="utf-8")
        before = xml.read_bytes()
        original = np.full((1800, 3000, 3), .2, np.float32)
        calls = []

        def convert(lin, opts):
            calls.append((lin.shape, opts))
            return lin[100:700, 200:900]

        with patch.object(sheet_app.decast, "load_image", return_value=(original, True)) as load:
            with patch.object(sheet_app.decast, "convert_negative", side_effect=convert):
                _, state = self.prepared({"directory": str(self.roll)})
        self.assertEqual(state["state"], "ready")
        self.assertEqual(state["items"][0]["source"], "saved")
        self.assertEqual(load.call_count, 1)
        self.assertLessEqual(max(calls[0][0][:2]), 2560)
        opts = calls[0][1]
        self.assertEqual(opts.gamma, .85)
        self.assertEqual(opts.crop_rect, [.1, .2, .9, .8])
        self.assertIsNone(opts.stats_rect)
        self.assertIsNone(opts._ref_cdfs)
        self.assertIsNone(opts._ref_centers)
        self.assertEqual(xml.read_bytes(), before)

    def test_settings_fallback_on_original_jpeg_uses_its_actual_saved_source(self):
        raw = self.roll / "FRAME004.ARW"
        raw.write_bytes(b"raw without adjustment")
        jpeg = self.image("FRAME004.JPG")
        Path(self.settings_file(str(jpeg))).write_text(json.dumps(dict(
            P=dict(gamma=1.05), cropN=dict(x0=0, y0=0, x1=1, y1=1))), encoding="utf-8")
        with patch.object(sheet_app.decast, "load_image", return_value=(np.ones((20, 30, 3)), False)) as load:
            with patch.object(sheet_app.decast, "convert_negative", side_effect=lambda lin, opts: lin):
                _, state = self.prepared({"directory": str(self.roll)})
        self.assertEqual(state["items"][0]["path"], str(jpeg))
        self.assertEqual(load.call_args.args[0], str(jpeg))
        self.assertEqual(self.opts_seen[0]["gamma"], 1.05)

    def test_selected_original_paths_discover_exports_and_use_saved_jpeg_adjustments(self):
        raw = self.roll / "FRAME012.ARW"
        raw.write_bytes(b"must not decode this exported frame")
        original = self.image("FRAME012.JPG", color="black")
        positive_folder = self.roll / "positives"
        positive_folder.mkdir()
        exported = self.image("FRAME012_pos.tif", color="green", folder=positive_folder)
        adjusted = self.image("FRAME013.JPG", color="black")
        self.xml(adjusted, gamma=.7)
        with patch.object(sheet_app.decast, "load_image", return_value=(np.ones((20, 30, 3)), False)) as load:
            with patch.object(sheet_app.decast, "convert_negative", side_effect=lambda lin, opts: lin):
                _, state = self.prepared({"paths": [str(raw), str(original), str(adjusted)]})
        self.assertEqual(state["state"], "ready")
        self.assertEqual(len(state["items"]), 2)
        self.assertEqual(state["items"][0]["path"], str(exported))
        self.assertEqual(state["items"][0]["source"], "export")
        self.assertEqual(state["items"][1]["path"], str(adjusted))
        self.assertEqual(state["items"][1]["source"], "saved")
        self.assertEqual(load.call_count, 1)
        self.assertEqual(load.call_args.args[0], str(adjusted))
        self.assertEqual(self.opts_seen[0]["gamma"], .7)

    def test_raw_without_adjustments_is_excluded(self):
        raw = self.roll / "FRAME005.ARW"
        raw.write_bytes(b"bare raw")
        with patch.object(sheet_app.decast, "load_image", side_effect=AssertionError("should never invert")):
            _, state = self.prepared({"paths": [str(raw)]})
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["items"], [])
        self.assertTrue(state["warnings"])

    def test_direct_image_is_positive_and_alpha_is_retained_for_renderer(self):
        image = self.image("custom.png", (255, 0, 0, 80), mode="RGBA")
        identifier, state = self.prepared({"paths": [str(image), str(image)]})
        self.assertEqual(len(state["items"]), 1)
        self.assertEqual(state["items"][0]["source"], "import")
        cached = self.blueprint.sheet_jobs[identifier]["items"][0]["cache"]
        with Image.open(cached) as decoded:
            self.assertEqual(decoded.mode, "RGBA")
            self.assertEqual(decoded.getpixel((0, 0))[3], 80)
        response = self.client.post("/api/sheet/preview", json=dict(
            job=identifier, stockId="test", config=dict(width=9999, columns=3,
            background=dict(mode="transparent"), header=dict(enabled=False),
            strip=dict(leader=False))))
        self.assertEqual(response.status_code, 200, response.json)
        with Image.open(io.BytesIO(response.data)) as rendered:
            self.assertEqual(rendered.width, 1200)
            self.assertEqual(rendered.mode, "RGBA")
        self.assertEqual(self.opts_seen, [])

    def test_upload_raw_rejected_and_positive_upload_keeps_original_display_name(self):
        failed = self.client.post("/api/sheet/upload", data={
            "files": (io.BytesIO(b"raw"), "camera.ARW")}, content_type="multipart/form-data")
        self.assertEqual(failed.status_code, 400)
        self.assertIn("RAW", failed.json["error"])
        self.assertEqual(len(self.blueprint.sheet_jobs), 0)
        buffer = io.BytesIO()
        Image.new("RGB", (32, 24), "yellow").save(buffer, "PNG")
        buffer.seek(0)
        response = self.client.post("/api/sheet/upload", data={
            "files": (buffer, "my-positive.png")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        self.blueprint.sheet_executor.shutdown(wait=True)
        state = self.client.get("/api/sheet/job/" + response.json["job"]).json
        self.assertEqual(state["state"], "ready")
        self.assertEqual(state["items"][0]["name"], "my-positive.png")
        self.assertEqual(list(self.roll.iterdir()), [])

    def test_invalid_order_and_oversized_render_rejected(self):
        image = self.image("frame_pos.jpg")
        identifier, _ = self.prepared({"paths": [str(image)]})
        for order in ([0, 0], [99], [], [True]):
            response = self.client.post("/api/sheet/preview", json=dict(job=identifier, order=order))
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/sheet/export", json=dict(
            job=identifier, config=dict(width=10001)))
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/sheet/preview", json=dict(
            job=identifier, config=dict(spacing=float("nan"))))
        self.assertEqual(response.status_code, 400)

    def test_preview_reports_exact_full_resolution_dimensions(self):
        image = self.image("frame_pos.jpg")
        identifier, _ = self.prepared({"paths": [str(image)]})
        config = dict(width=4800, columns=6, background=dict(mode="solid"))
        response = self.client.post("/api/sheet/preview", json=dict(
            job=identifier, order=[0], stockId="test", config=config))
        self.assertEqual(response.status_code, 200, response.json)
        full_width, full_height = sheet_app.sheet_size(1, config)
        self.assertEqual(response.headers["X-Sheet-Width"], str(full_width))
        self.assertEqual(response.headers["X-Sheet-Height"], str(full_height))
        with Image.open(io.BytesIO(response.data)) as preview:
            self.assertEqual(preview.width, 1200)
            self.assertNotEqual(full_height, preview.height * 4)

    def test_preview_reuses_decoded_pixels_but_reloads_for_larger_crop(self):
        images = [self.image(f"frame-{i}_pos.jpg", color=color, size=(1500, 1000))
                  for i, color in enumerate(("red", "blue"))]
        identifier, _ = self.prepared({"paths": list(map(str, images))})
        body = dict(job=identifier, config=dict(width=4800, columns=6,
                    background=dict(mode="solid")))
        cached_paths = {item["cache"] for item in self.blueprint.sheet_jobs[identifier]["items"]}
        with patch.object(sheet_app.Image, "open", wraps=Image.open) as opened:
            first = self.client.post("/api/sheet/preview", json=body)
            repeated = self.client.post("/api/sheet/preview", json=body)
            self.assertEqual(first.status_code, 200, first.json)
            self.assertEqual(repeated.data, first.data)
            self.assertEqual(sum(call.args[0] in cached_paths for call in opened.call_args_list), 2)
            body["config"]["header"] = dict(title="Changed without decoding photos again")
            self.assertEqual(self.client.post("/api/sheet/preview", json=body).status_code, 200)
            self.assertEqual(sum(call.args[0] in cached_paths for call in opened.call_args_list), 2)
            body["config"]["frameOverrides"] = [dict(crop=dict(scale=2))]
            self.assertEqual(self.client.post("/api/sheet/preview", json=body).status_code, 200)
            self.assertEqual(sum(call.args[0] in cached_paths for call in opened.call_args_list), 3)
            body["config"].pop("frameOverrides")
            self.assertEqual(self.client.post("/api/sheet/preview", json=body).status_code, 200)
            self.assertEqual(sum(call.args[0] in cached_paths for call in opened.call_args_list), 3)

    def test_preview_decode_does_not_block_status_or_allow_job_eviction(self):
        image = self.image("frame_pos.jpg")
        identifier, _ = self.prepared({"paths": [str(image)]})
        job = self.blueprint.sheet_jobs[identifier]
        cached_path = job["items"][0]["cache"]
        entered, release = threading.Event(), threading.Event()
        original_open = Image.open

        def blocked_open(path, *args, **kwargs):
            if str(path) == cached_path:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Test did not release the preview decode")
            return original_open(path, *args, **kwargs)

        def post_preview():
            with self.client.application.test_client() as client:
                return client.post("/api/sheet/preview", json=dict(job=identifier,
                    config=dict(background=dict(mode="solid")))).status_code

        def inspect_while_decoding():
            with self.client.application.test_client() as client:
                state = client.get("/api/sheet/job/" + identifier)
                attempted = client.post("/api/sheet/prepare", json=dict(paths=[str(image)]))
                return state.status_code, attempted.status_code

        with patch.object(sheet_app, "MAX_JOBS", 1), ThreadPoolExecutor(max_workers=2) as pool:
            with patch.object(sheet_app.Image, "open", side_effect=blocked_open):
                preview = pool.submit(post_preview)
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(pool.submit(inspect_while_decoding).result(timeout=2), (200, 400))
                    self.assertEqual(job["users"], 1)
                    self.assertTrue(Path(cached_path).is_file())
                finally:
                    release.set()
                self.assertEqual(preview.result(timeout=3), 200)
            self.assertEqual(job["users"], 0)
            self.assertTrue(self.blueprint.sheet_preview_images.entries)
            _, state = self.prepared(dict(paths=[str(image)]))
            self.assertEqual(state["state"], "ready")
            self.assertNotIn(identifier, self.blueprint.sheet_jobs)
            self.assertFalse(Path(cached_path).exists())
            self.assertFalse(self.blueprint.sheet_preview_images.entries)
            self.assertEqual(self.blueprint.sheet_preview_images.bytes, 0)

    def test_preview_releases_job_when_validation_fails(self):
        image = self.image("frame_pos.jpg")
        identifier, _ = self.prepared({"paths": [str(image)]})
        response = self.client.post("/api/sheet/preview", json=dict(job=identifier, order=[]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.blueprint.sheet_jobs[identifier]["users"], 0)

    def test_generated_sheets_not_reimported_as_photographs(self):
        output = self.roll / "整卷展示"
        output.mkdir()
        self.image("sheet.png", folder=output)
        image = self.image("frame_pos.jpg")
        _, state = self.prepared({"directory": str(self.roll)})
        self.assertEqual([item["path"] for item in state["items"]], [str(image)])

    def test_missing_path_and_unknown_stock_return_json_errors(self):
        missing = self.client.post("/api/sheet/prepare", json=dict(directory=str(self.root / "missing")))
        self.assertEqual(missing.status_code, 400)
        self.assertFalse(missing.json["ok"])
        image = self.image("frame_pos.jpg")
        identifier, _ = self.prepared({"paths": [str(image)]})
        bad = self.client.post("/api/sheet/preview", json=dict(job=identifier, stockId="missing"))
        self.assertEqual(bad.status_code, 400)
        self.assertIn("型号", bad.json["error"])

    def test_export_has_srgb_and_300_dpi_and_never_overwrites_existing_file(self):
        image = self.image("frame_pos.jpg")
        identifier, _ = self.prepared({"paths": [str(image)]})
        target = self.roll / "existing.png"
        target.write_bytes(b"keep existing user artwork")
        started = self.client.post("/api/sheet/export", json=dict(
            job=identifier, stockId="test", out=str(target), format="png",
            config=dict(width=1200, columns=3, background=dict(mode="solid"))))
        self.assertEqual(started.status_code, 200, started.json)
        record = self.finished("/api/sheet/export/" + started.json["export"])
        self.assertEqual(record["state"], "ready", record)
        self.assertNotEqual(record["out"], str(target))
        self.assertEqual(target.read_bytes(), b"keep existing user artwork")
        with Image.open(record["out"]) as result:
            self.assertEqual(result.width, 1200)
            self.assertTrue(result.info.get("icc_profile"))
            self.assertAlmostEqual(result.info["dpi"][0], 300, delta=.1)
        download = self.client.get("/api/sheet/download/" + started.json["export"])
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["Content-Disposition"])
        download.close()

    def test_custom_background_upload_and_preview(self):
        image = self.image("frame_pos.jpg", color="blue")
        identifier, _ = self.prepared({"paths": [str(image)]})
        buffer = io.BytesIO()
        Image.new("RGB", (50, 50), "red").save(buffer, "PNG")
        buffer.seek(0)
        uploaded = self.client.post("/api/sheet/background", data=dict(
            job=identifier, file=(buffer, "background.png")), content_type="multipart/form-data")
        self.assertEqual(uploaded.status_code, 200, uploaded.json)
        response = self.client.post("/api/sheet/preview", json=dict(job=identifier,
            stockId="test", config=dict(background=dict(mode="blur", sourceIndex="custom",
            blur=0, brightness=1))))
        self.assertEqual(response.status_code, 200, response.json)
        with Image.open(io.BytesIO(response.data)) as result:
            self.assertEqual(result.getpixel((0, 0))[:3], (255, 0, 0))
        self.assertEqual(self.client.get("/api/sheet/job/" + identifier).json["hasBackground"], True)
        # A replacement upload must not reuse pixels from the previous file,
        # even when its user-facing filename is unchanged.
        replacement = io.BytesIO()
        Image.new("RGB", (50, 50), "lime").save(replacement, "PNG")
        replacement.seek(0)
        self.client.post("/api/sheet/background", data=dict(job=identifier,
            file=(replacement, "background.png")), content_type="multipart/form-data")
        response = self.client.post("/api/sheet/preview", json=dict(job=identifier,
            stockId="test", config=dict(background=dict(mode="blur", sourceIndex="custom",
            blur=0, brightness=1))))
        self.assertEqual(response.status_code, 200, response.json)
        with Image.open(io.BytesIO(response.data)) as result:
            self.assertEqual(result.getpixel((0, 0))[:3], (0, 255, 0))

    def test_portable_project_restores_pixels_alpha_and_custom_background_after_cache_cleanup(self):
        original = self.image("portable.png", (20, 60, 180, 130), mode="RGBA")
        identifier, _ = self.prepared({"paths": [str(original)]})
        background = io.BytesIO()
        Image.new("RGB", (40, 40), "red").save(background, "PNG")
        background.seek(0)
        self.client.post("/api/sheet/background", data=dict(job=identifier,
            file=(background, "background.png")), content_type="multipart/form-data")
        override = dict(rotation=90, label="23", crop=dict(x=.4, y=.6, scale=1.4))
        exported = self.client.post("/api/sheet/project/export", json=dict(
            job=identifier, order=[0], stockId="test", config=dict(width=1200,
            columns=3, background=dict(mode="blur", sourceIndex="custom"),
            header=dict(roll="2401",showStock=True,infoScale=1.2),
            strip=dict(fontStyle="citaro",leaderMode="manual",leaderCount=4,leaderStyle="leak",leaderStrength=.6),
            frameOverrides=[override])))
        self.assertEqual(exported.status_code, 200, exported.json)
        self.assertEqual(exported.mimetype, "application/zip")
        package = exported.data
        exported.close()
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["version"], 2)
            self.assertEqual(manifest["assets"][0]["override"], override)
            self.assertTrue(manifest["assets"][0]["file"].endswith(".png"))
            self.assertIn("backgroundFile", manifest)
            self.assertNotIn("_backgroundImage", manifest["config"])
        old = self.blueprint.sheet_jobs.pop(identifier)
        shutil.rmtree(old["cache"])
        original.unlink()
        with patch.object(sheet_app.decast, "load_image", side_effect=AssertionError("portable pixels must be positive")):
            imported = self.client.post("/api/sheet/project/import", data={
                "file": (io.BytesIO(package), "restored.zip")}, content_type="multipart/form-data")
            self.assertEqual(imported.status_code, 200, imported.json)
            state = self.finished("/api/sheet/job/" + imported.json["job"])
        self.assertEqual(state["state"], "ready", state)
        self.assertTrue(state["hasBackground"])
        self.assertEqual(state["items"][0]["name"], "portable.png")
        project = imported.json["project"]
        self.assertEqual(project["version"], 1)
        self.assertEqual(project["config"]["header"]["roll"], "2401")
        self.assertEqual(project["config"]["header"]["infoScale"], 1.2)
        for key,value in dict(fontStyle="citaro",leaderMode="manual",leaderCount=4,leaderStyle="leak",leaderStrength=.6).items():
            self.assertEqual(project["config"]["strip"][key], value)
        self.assertEqual(project["frameOptions"][project["sources"][0]], override)
        self.assertTrue(Path(project["sources"][0]).is_file())
        cached = self.blueprint.sheet_jobs[imported.json["job"]]["items"][0]["cache"]
        with Image.open(cached) as decoded:
            self.assertEqual(decoded.getpixel((0, 0))[3], 130)
        preview = self.client.post("/api/sheet/preview", json=dict(job=imported.json["job"],
            stockId=project["stockId"], config=project["config"]))
        self.assertEqual(preview.status_code, 200, preview.json)

    def project_archive(self, *, extra=None, source_path="/should/never/read/this.ARW", photo=None):
        photo = photo or io.BytesIO()
        if not photo.getvalue():
            Image.new("RGB", (30, 20), "yellow").save(photo, "PNG")
        manifest = dict(type="NegativeMasterSheet", version=2, stockId="test",
            config=dict(width=1200, columns=3), assets=[dict(file="assets/000.png",
            name="photo.png", sourcePath=source_path, override={})])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("assets/000.png", photo.getvalue())
            if extra:
                archive.writestr(extra, b"untrusted extra")
        buffer.seek(0)
        return buffer

    def test_portable_project_source_paths_never_drive_filesystem_access(self):
        imported = self.client.post("/api/sheet/project/import", data={
            "file": (self.project_archive(source_path="../../outside-raw.ARW"), "project.zip")},
            content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 200, imported.json)
        state = self.finished("/api/sheet/job/" + imported.json["job"])
        self.assertEqual(state["state"], "ready")
        self.assertEqual(state["items"][0]["source"], "import")
        self.assertNotIn("outside-raw", str(imported.json["project"]["sources"]))

    def test_portable_project_rejects_zip_slip_and_undeclared_entries(self):
        for extra in ("../outside.txt", "/absolute.txt", "assets/../../outside.txt", "unlisted.txt"):
            with self.subTest(extra=extra):
                imported = self.client.post("/api/sheet/project/import", data={
                    "file": (self.project_archive(extra=extra), "project.zip")},
                    content_type="multipart/form-data")
                self.assertEqual(imported.status_code, 400)
                self.assertFalse(imported.json["ok"])
        self.assertEqual(self.blueprint.sheet_jobs, {})

    def test_portable_project_enforces_uncompressed_size_limit(self):
        photo = io.BytesIO()
        Image.new("RGB", (30, 20), "yellow").save(photo, "PNG")
        photo.write(b"\0" * 16000)
        fixture = self.project_archive(photo=photo)
        compressed = io.BytesIO()
        with zipfile.ZipFile(fixture) as source:
            with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for name in source.namelist():
                    target.writestr(name, source.read(name))
        self.assertLess(len(compressed.getvalue()), 4096)
        compressed.seek(0)
        with patch.object(sheet_app, "MAX_PROJECT_BYTES", 4096):
            imported = self.client.post("/api/sheet/project/import", data={
                "file": (compressed, "project.zip")}, content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 400)
        self.assertIn("解压", imported.json["error"])


class PreviewCacheTests(unittest.TestCase):
    def test_bounds_memory_evicts_least_recent_and_protects_cached_pixels(self):
        cache = sheet_app._PreviewImageCache(800)
        loaded = []

        def get(key):
            def loader():
                loaded.append(key)
                return Image.new("RGB", (10, 10), "red")
            return cache.get(("roll", key, 10), loader)

        first = get("first")
        first.putpixel((0, 0), (0, 0, 255))
        self.assertEqual(get("first").getpixel((0, 0)), (255, 0, 0))
        get("second")
        get("first")
        get("third")
        self.assertEqual(cache.bytes, 800)
        self.assertEqual(get("first").getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(loaded.count("first"), 1)
        get("second")
        self.assertEqual(loaded.count("second"), 2)
        oversized = cache.get(("roll", "oversized", 20), lambda: Image.new("RGBA", (20, 20)))
        self.assertEqual(oversized.size, (20, 20))
        self.assertLessEqual(cache.bytes, cache.limit)
        self.assertNotIn(("roll", "oversized", 20), cache.entries)
        cache.discard_job("roll")
        self.assertEqual(cache.bytes, 0)
        self.assertFalse(cache.entries)


if __name__ == "__main__":
    unittest.main()

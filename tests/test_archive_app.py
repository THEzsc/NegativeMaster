"""Archive regressions use synthetic images and isolated temporary databases."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from unittest.mock import patch

from flask import Flask, request
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from archive_app import create_archive_blueprint


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.photos = self.root / "海边的照片"
        self.photos.mkdir()
        for name, color in [("frame2_pos.jpg", "orange"), ("frame10_pos.jpg", "navy"), ("frame2.jpg", "brown")]:
            Image.new("RGB", (80, 60), color).save(self.photos / name)
        self.originals = {p.name: p.read_bytes() for p in self.photos.iterdir()}
        self.bp = create_archive_blueprint(self.root / "archive")
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
        app.config["TESTING"] = True
        app.register_blueprint(self.bp)
        self.app = app
        self.client = app.test_client()
        self.headers = {"X-NegativeMaster-Archive": "1"}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, method, path, data=None, **kwargs):
        return getattr(self.client, method)(path, json=data, headers=self.headers, **kwargs)

    def create(self, **changes):
        data = {"title": "秋日海边", "date_start": "2026-10-01", "place": "青岛", "camera": "Nikon F3", "tags": ["旅行", "海边"], "iso": 200}
        data.update(changes)
        response = self.write("post", "/api/archive/rolls", data)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["roll"]

    def add(self, roll, mode="positive"):
        response = self.write("post", f"/api/archive/rolls/{roll['id']}/frames", {"directory": str(self.photos), "mode": mode})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def backup(self):
        response = self.client.get("/api/archive/backup")
        self.assertEqual(response.status_code, 200)
        return response.data

    def restore(self, raw):
        return self.client.post("/api/archive/restore", data={"file": (io.BytesIO(raw), "backup.zip")}, headers=self.headers)

    @staticmethod
    def zip_manifest(manifest, extras=None):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for key, value in (extras or {}).items():
                archive.writestr(key, value)
        return data.getvalue()

    def test_page_catalog_and_empty_library(self):
        page = self.client.get("/archive")
        self.assertEqual(page.status_code, 200)
        self.assertIn("胶片档案", page.get_data(as_text=True))
        data = self.client.get("/api/archive/catalog").get_json()
        self.assertGreaterEqual(len(data["stocks"]), 100)
        self.assertEqual(self.client.get("/api/archive/rolls").get_json()["stats"]["rolls"], 0)

    def test_artwork_cover_attribution_survives_edit_backup_and_restore(self):
        items = self.client.get("/api/archive/artwork").get_json()["artworks"]
        item = next(a for a in items if "kodak-colorplus-200" in a["stock_ids"])
        roll = self.create(stock_id="kodak-colorplus-200")
        url = f"/api/archive/rolls/{roll['id']}"
        result = self.write("post", url + "/cover", {"artwork_id": item["id"]})
        self.assertEqual(result.status_code, 200, result.get_json())
        selected = result.get_json()["roll"]
        self.assertEqual(selected["cover_source"], item["source_url"])
        self.assertEqual(selected["cover_license"], item["license"])
        with self.client.get('/api/archive/assets/' + selected['cover']) as image_response:
            self.assertEqual(image_response.status_code, 200)
        # Old clients without the new provenance fields may still edit a roll.
        edit = {k:v for k,v in selected.items() if not k.startswith('cover_')}
        edit['title'] = '图案封面与资料独立保存'
        saved = self.write('put', url, edit).get_json()['roll']
        self.assertEqual(saved['cover_artwork'], item['id'])
        restored = self.restore(self.backup()).get_json()
        copy = self.client.get('/api/archive/rolls/' + restored['ids'][0]).get_json()['roll']
        for key in ['cover', 'cover_artwork', 'cover_credit', 'cover_source', 'cover_license', 'cover_license_url']:
            self.assertEqual(copy[key], saved[key])
        reset = self.write('post', url + '/cover', {}).get_json()['roll']
        self.assertEqual(reset['cover_license'], '')
        self.assertEqual(reset['cover_artwork'], '')
        self.assertEqual(reset['cover'], '')

    def test_artwork_selection_accepts_only_bundled_ids(self):
        roll = self.create()
        url = f"/api/archive/rolls/{roll['id']}/cover"
        for value in ['../../private.jpg', 'https://example.com/a.jpg', None, []]:
            self.assertEqual(self.write('post', url, {'artwork_id':value}).status_code, 400)
        item = self.client.get('/api/archive/artwork').get_json()['artworks'][0]
        self.assertEqual(self.client.post(url,json={'artwork_id':item['id']}).status_code,403)

    def test_legacy_rolls_without_artwork_fields_remain_searchable(self):
        roll = self.create()
        with self.bp.archive_store.connection() as db:
            data = json.loads(db.execute('SELECT data FROM rolls WHERE id=?',(roll['id'],)).fetchone()[0])
            for key in ('cover_artwork','cover_license','cover_license_url'):
                data.pop(key)
            db.execute('UPDATE rolls SET data=? WHERE id=?',(json.dumps(data),roll['id']))
        response = self.client.get('/api/archive/rolls?q=海边')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['rolls'][0]['id'],roll['id'])
        self.assertEqual(response.get_json()['rolls'][0]['cover_license'],'')

    def test_crud_persists_and_optimistic_conflict_prevents_lost_edits(self):
        roll = self.create()
        url = f"/api/archive/rolls/{roll['id']}"
        updated = self.write("put", url, {**roll, "title": "更新后", "status": "archived"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.write("put", url, {**roll, "title": "过期编辑"}).status_code, 409)
        app2 = Flask("reopened")
        app2.register_blueprint(create_archive_blueprint(self.root / "archive"))
        self.assertEqual(app2.test_client().get(url).get_json()["roll"]["title"], "更新后")
        self.assertEqual(self.write("delete", url).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_validation_rejects_bad_dates_and_types(self):
        for changes in ({"date_start": "2026-02-30"}, {"date_end": "2026-01-01"}, {"iso": 0}, {"iso": True}, {"status": []}, {"tags": "foo"}, {"cover_source": "javascript:alert(1)"}, {"title": ""}):
            result = self.write("post", "/api/archive/rolls", {"title": "Test", "date_start": "2026-10-01", **changes})
            self.assertEqual(result.status_code, 400, changes)
        self.assertEqual(self.client.get("/api/archive/rolls").get_json()["stats"]["rolls"], 0)

    def test_search_filter_and_sort_with_chinese_and_tags(self):
        self.create()
        self.create(title="冬日", date_start="2025-12-01", status="archived", place="上海", tags=["人像"])
        for query in ("q=青岛", "q=海边", "q=nikon&year=2026", "status=archived", "year=2025"):
            self.assertEqual(len(self.client.get("/api/archive/rolls?" + query).get_json()["rolls"]), 1)
        self.assertEqual(self.client.get("/api/archive/rolls?q=不存在").get_json()["rolls"], [])

    def test_linking_is_natural_order_deduplicated_and_non_destructive(self):
        roll = self.create()
        result = self.add(roll)
        self.assertEqual(result["added"], 2)
        self.assertEqual([f["name"] for f in result["roll"]["frames"]], ["frame2_pos.jpg", "frame10_pos.jpg"])
        self.assertEqual(self.add(roll)["added"], 0)
        for frame in result["roll"]["frames"]:
            response = self.client.get("/api/archive/assets/" + frame["thumb"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/jpeg")
            response.close()
        self.write("delete", f"/api/archive/rolls/{roll['id']}")
        self.assertEqual({p.name: p.read_bytes() for p in self.photos.iterdir()}, self.originals)

    def test_raw_and_invalid_image_keep_reference_without_fake_preview(self):
        (self.photos / "frame3.dng").write_bytes(b"raw placeholder")
        (self.photos / "broken.jpg").write_bytes(b"invalid")
        result = self.add(self.create(), mode="all")
        self.assertEqual(result["added"], 5)
        self.assertEqual(len(result["warnings"]), 2)
        self.assertEqual(sum(not f["thumb"] for f in result["roll"]["frames"]), 2)

    def test_frame_notes_ratings_and_removal_do_not_touch_source(self):
        roll = self.add(self.create())["roll"]
        frame = roll["frames"][0]
        url = f"/api/archive/rolls/{roll['id']}/frames/{frame['id']}"
        response = self.write("put", url, {"rating": 5, "notes": "值得放大"})
        self.assertEqual(response.get_json()["roll"]["frames"][0]["rating"], 5)
        self.assertEqual(self.write("put", url, {"rating": 6}).status_code, 400)
        self.assertEqual(self.write("delete", url).status_code, 200)
        self.assertEqual(Path(frame["path"]).read_bytes(), self.originals[frame["name"]])

    def test_cover_upload_stores_provenance_and_strips_original_metadata(self):
        roll = self.create()
        data = io.BytesIO()
        Image.new("RGBA", (40, 60), (255, 0, 0, 120)).save(data, "PNG")
        response = self.client.post(f"/api/archive/rolls/{roll['id']}/cover", headers=self.headers, data={"file": (io.BytesIO(data.getvalue()), "../../box.png"), "source": "https://www.kodak.com/", "credit": "我的胶卷盒"})
        self.assertEqual(response.status_code, 200)
        stored = response.get_json()["roll"]
        self.assertEqual(stored["cover_credit"], "我的胶卷盒")
        self.assertEqual(stored["cover_source"], "https://www.kodak.com/")
        with Image.open(self.bp.archive_store.asset(stored["cover"])) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.mode, "RGB")

    def test_cover_from_frame_cannot_reference_another_roll(self):
        first = self.add(self.create())["roll"]
        second = self.create()
        url = f"/api/archive/rolls/{second['id']}/cover"
        self.assertEqual(self.write("post", url, {"frame_id": first["frames"][0]["id"]}).status_code, 400)
        self.assertEqual(self.write("post", f"/api/archive/rolls/{first['id']}/cover", {"frame_id": first["frames"][0]["id"]}).status_code, 200)

    def test_backup_restore_is_portable_and_additive_without_originals(self):
        roll = self.add(self.create())["roll"]
        frame = roll["frames"][0]
        self.write("post", f"/api/archive/rolls/{roll['id']}/cover", {"frame_id": frame["id"]})
        backup = self.backup()
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertFalse(manifest["originals_included"])
            self.assertTrue(all(name == "manifest.json" or name.startswith("assets/") for name in archive.namelist()))
        shutil.rmtree(self.photos)
        restored = self.restore(backup)
        self.assertEqual(restored.status_code, 200, restored.get_json())
        new_id = restored.get_json()["ids"][0]
        self.assertNotEqual(new_id, roll["id"])
        new_roll = self.client.get(f"/api/archive/rolls/{new_id}").get_json()["roll"]
        self.assertTrue(all(frame["missing"] for frame in new_roll["frames"]))
        response = self.client.get("/api/archive/assets/" + new_roll["cover"])
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.get("/api/archive/rolls").get_json()["stats"]["rolls"], 2)

    def test_restore_rejects_traversal_and_atomic_invalid_manifest(self):
        original = self.create()
        manifest = {"format": "NegativeMasterArchive", "version": 1, "rolls": [original]}
        response = self.restore(self.zip_manifest(manifest, {"../../escape.txt": "bad"}))
        self.assertEqual(response.status_code, 400)
        manifest["rolls"].append({"title": "坏记录", "date_start": "oops"})
        self.assertEqual(self.restore(self.zip_manifest(manifest)).status_code, 400)
        self.assertEqual(self.client.get("/api/archive/rolls").get_json()["stats"]["rolls"], 1)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_restore_rejects_corrupt_asset_and_wrong_version(self):
        roll = self.create()
        roll["cover"] = "a" * 64 + ".jpg"
        manifest = {"format": "NegativeMasterArchive", "version": 1, "rolls": [roll]}
        self.assertEqual(self.restore(self.zip_manifest(manifest, {"assets/" + roll["cover"]: b"bad"})).status_code, 400)
        manifest["version"] = 2
        self.assertEqual(self.restore(self.zip_manifest(manifest)).status_code, 400)
        self.assertEqual(self.restore(b"not a zip").status_code, 400)

    def test_relink_keeps_preview_notes_and_original_bytes(self):
        roll = self.add(self.create())["roll"]
        moved = self.root / "迁移后的文件夹"
        self.photos.rename(moved)
        response = self.write("post", f"/api/archive/rolls/{roll['id']}/relink", {"directory": str(moved)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["linked"], 2)
        new_roll = response.get_json()["roll"]
        self.assertTrue(all(not f["missing"] for f in new_roll["frames"]))
        self.assertEqual(new_roll["frames"][0]["thumb"], roll["frames"][0]["thumb"])
        self.assertEqual({p.name: p.read_bytes() for p in moved.iterdir()}, self.originals)

    def test_cross_origin_and_missing_header_cannot_mutate(self):
        self.assertEqual(self.client.post("/api/archive/rolls", json={"title": "oops"}).status_code, 403)
        headers = {**self.headers, "Origin": "https://evil.example"}
        self.assertEqual(self.client.post("/api/archive/rolls", json={"title": "oops"}, headers=headers).status_code, 403)
        headers["Origin"] = "http://localhost"
        self.assertEqual(self.client.post("/api/archive/rolls", json={"title": "合法本地请求"}, headers=headers).status_code, 201)

    def test_unreferenced_assets_not_exposed_and_bad_json_rejected(self):
        name = self.bp.archive_store.save_image(self.photos / "frame2.jpg")
        self.assertEqual(self.client.get("/api/archive/assets/" + name).status_code, 404)
        self.assertEqual(self.client.get("/api/archive/assets/not-a-file.jpg").status_code, 400)
        self.assertEqual(self.write("post", "/api/archive/rolls", []).status_code, 400)

    def test_cover_change_never_discards_a_successful_concurrent_metadata_save(self):
        roll = self.create(title="original")
        url = f"/api/archive/rolls/{roll['id']}"
        cover_read, release = threading.Event(), threading.Event()
        original_reader = self.bp.archive_store.roll
        cover_reads = 0

        def pause_cover(db, identifier, frames=False):
            nonlocal cover_reads
            result = original_reader(db, identifier, frames)
            if request.endpoint == "archive.cover":
                cover_reads += 1
                if cover_reads == 2:
                    cover_read.set()
                    if not release.wait(5):
                        raise RuntimeError("Concurrent cover test timed out")
            return result

        def save_title():
            with self.app.test_client() as client:
                return client.put(url, json={**roll, "title": "new edit"}, headers=self.headers).status_code

        def reset_cover():
            with self.app.test_client() as client:
                return client.post(url + "/cover", json={}, headers=self.headers).status_code

        with patch.object(self.bp.archive_store, "roll", side_effect=pause_cover), ThreadPoolExecutor(max_workers=2) as pool:
            cover = pool.submit(reset_cover)
            self.assertTrue(cover_read.wait(5))
            edit = pool.submit(save_title)
            try:
                # A writer holding the archive transaction may block the editor;
                # an old implementation completed this save and then erased it.
                try:
                    edit.result(timeout=.15)
                except FutureTimeout:
                    pass
            finally:
                release.set()
            self.assertEqual(cover.result(timeout=5), 200)
            edit_status = edit.result(timeout=5)
        self.assertIn(edit_status, (200, 409))
        final = self.client.get(url).get_json()["roll"]
        self.assertEqual(final["title"], "new edit" if edit_status == 200 else "original")


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from PIL import Image
import film_artwork

ROOT = Path(__file__).resolve().parents[1]


class ArtworkTests(unittest.TestCase):
    def test_bundled_assets_match_manifest_and_attribution(self):
        data = film_artwork.catalog()
        stocks = {s['id'] for s in json.loads((ROOT/'data/film_stocks.json').read_text(encoding='utf-8'))['stocks']}
        ids = set()
        for item in data['artworks']:
            self.assertNotIn(item['id'],ids); ids.add(item['id'])
            _, path = film_artwork.artwork(item['id'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),item['sha256'])
            self.assertTrue(item['credit'])
            self.assertTrue(item['license_url'].startswith('https://'))
            self.assertTrue(item['license'].startswith(('CC BY','CC0')))
            self.assertTrue(set(item['stock_ids']) <= stocks)
            with Image.open(path) as image:
                self.assertEqual(image.size,(item['width'],item['height']))
                image.verify()
        for item in data['references']:
            self.assertTrue(set(item['stock_ids']) <= stocks)
            self.assertNotIn('image',item)  # Referenced scans are not bundled licensed artwork.
        self.assertGreater(len(ids),30)

    def test_native_bundle_module_list_bootstraps_without_checkout_imports(self):
        script = (ROOT/'FilmDecastSwift/build-app.sh').read_text(encoding='utf-8')
        files = re.search(r'for source in (.+); do',script).group(1).split()
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            for name in files: shutil.copy2(ROOT/name,stage/name)
            for name in ('data','static','templates','presets'):
                shutil.copytree(ROOT/name,stage/name)
            code = "import sys;sys.path.insert(0,sys.argv[1]);import gui;c=gui.app.test_client();assert c.get('/archive').status_code==200;assert c.get('/api/archive/artwork').json['artworks'];assert '/api/workflow/analyze' in {r.rule for r in gui.app.url_map.iter_rules()};assert c.get('/sheet').status_code==200"
            result = subprocess.run([sys.executable,'-I','-c',code,str(stage)],cwd=stage,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import gui
from workflow_app import representative_paths


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = patch.object(gui, 'SETTINGS_DIR', str(self.root / 'settings'))
        self.settings.start()
        self.cache = dict(gui.CACHE)
        self.client = gui.app.test_client()
        a = np.tile(np.linspace(30, 220, 160, dtype=np.uint8), (100, 1))
        self.path = self.root / '胶卷 01.png'
        Image.fromarray(np.stack([a, a // 2 + 25, a // 3 + 20], axis=-1)).save(self.path)

    def tearDown(self):
        gui.CACHE.clear(); gui.CACHE.update(self.cache)
        self.settings.stop(); self.tmp.cleanup()

    def data(self, **params):
        return dict(P={**gui.DEFAULTS, **params}, cropN=dict(x0=.1, y0=.12, x1=.9, y1=.88),
                    geometrySource='auto', curFmt='135', orient='land')

    def save(self, path, data):
        Path(gui.sidecar_path(str(path))).write_text(gui._data_to_xml(data, str(path)), encoding='utf-8')

    def test_analysis_does_not_mutate_original_sidecars_or_cache(self):
        self.save(self.path, self.data(gamma=1.4))
        sidecar = Path(gui.sidecar_path(str(self.path)))
        before = (self.path.read_bytes(), sidecar.read_bytes())
        sentinel = np.ones((2, 2, 3), dtype=np.float32)
        gui.CACHE.update(path='other-file', prev=sentinel)
        response = self.client.post('/api/workflow/analyze', json={'paths':[str(self.path)]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['sampled'], 1)
        self.assertEqual(response.json['frames'][0]['parameter_key'], 'gamma')
        self.assertIs(gui.CACHE['prev'], sentinel)
        self.assertEqual(gui.CACHE['path'], 'other-file')
        self.assertEqual((self.path.read_bytes(), sidecar.read_bytes()), before)

    def test_roll_apply_only_changes_gamma_and_keeps_each_frame_geometry(self):
        a = self.data(gamma=1.2, exposure=-1.1, temp=12, level_angle=.6)
        bpath = self.root / '02.png'; bpath.write_bytes(self.path.read_bytes())
        b = self.data(gamma=2.2, exposure=.8, temp=-8, rotate=90)
        b['cropN'] = dict(x0=.2, y0=.3, x1=.8, y1=.7)
        self.save(self.path, a); self.save(bpath, b)
        response = self.client.post('/api/workflow/roll-gamma', json={'paths':[str(self.path), str(bpath)], 'gamma':1.65})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['updated']), 2)
        for path, expected in ((self.path,a), (bpath,b)):
            expected['P']['gamma'] = 1.65
            actual = gui._xml_to_data(Path(gui.sidecar_path(str(path))).read_text(encoding='utf-8'))
            self.assertEqual(actual, expected)
            self.assertEqual(json.loads(Path(gui.settings_file(str(path))).read_text(encoding='utf-8')), expected)

    def test_damaged_sidecar_and_wrong_engine_are_not_replaced(self):
        sidecar = Path(gui.sidecar_path(str(self.path))); sidecar.write_text('<broken', encoding='utf-8')
        response = self.client.post('/api/workflow/roll-gamma', json={'paths':[str(self.path)],'gamma':1.6})
        self.assertEqual(response.json['updated'], [])
        self.assertEqual(sidecar.read_text(), '<broken')
        self.save(self.path, self.data(negadoctor=True))
        before = sidecar.read_bytes()
        response = self.client.post('/api/workflow/roll-gamma', json={'paths':[str(self.path)],'gamma':1.6})
        self.assertEqual(response.json['updated'], [])
        self.assertEqual(sidecar.read_bytes(), before)
        response = self.client.post('/api/workflow/roll-gamma', json={'paths':[str(self.path)],'gamma':3.1,'parameter_key':'nd_gamma'})
        self.assertEqual(len(response.json['updated']), 1)
        self.assertEqual(gui._xml_to_data(sidecar.read_text(encoding='utf-8'))['P']['nd_gamma'], 3.1)

    def test_invalid_requests_and_gamma_are_rejected_before_writing(self):
        for value in (None, {}, [], 'bad', {'paths':'not-a-list'}, {'paths':[False]}):
            response=self.client.post('/api/workflow/analyze',json=value)
            self.assertEqual(response.status_code, 400)
        for value in (True, '1.6', -1, 0, 4, float('nan'), float('inf')):
            response=self.client.post('/api/workflow/roll-gamma',json={'paths':[str(self.path)],'gamma':value})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(Path(gui.sidecar_path(str(self.path))).exists())

    def test_representative_sample_spans_roll_and_deduplicates(self):
        paths=[str(self.root / f'{i:03}.png') for i in range(36)]
        sample=representative_paths(paths + [paths[-1]])
        self.assertEqual(len(sample),12)
        self.assertEqual(sample[0],paths[0]);self.assertEqual(sample[-1],paths[-1])
        self.assertEqual(len(set(sample)),12)

    def test_unedited_roll_frame_keeps_the_web_ui_mirror_default(self):
        response=self.client.post('/api/workflow/roll-gamma',json={'paths':[str(self.path)],'gamma':1.6})
        self.assertEqual(len(response.json['updated']),1)
        saved=gui._xml_to_data(Path(gui.sidecar_path(str(self.path))).read_text(encoding='utf-8'))
        self.assertEqual(saved['P']['flip'],'h')
        self.assertEqual(saved['cropN'],dict(x0=.06,y0=.06,x1=.94,y1=.94))

    def test_decode_change_invalidates_cache_and_export_uses_same_decode(self):
        gui.load_full(str(self.path), decode_params={'input_gamma':'srgb'})
        original=gui.CACHE['full'].copy()
        gui.load_full(str(self.path), decode_params={'input_gamma':'linear'})
        self.assertGreater(float(gui.CACHE['full'].mean()),float(original.mean()))
        linear=gui.CACHE['full']
        gui.load_full(str(self.path), decode_params={'input_gamma':'linear'})
        self.assertIs(gui.CACHE['full'],linear)
        out=self.root/'positive.jpg'
        response=self.client.post('/api/export',json={'input_gamma':'linear','mode':'positive','out':str(out),'format':'jpg'})
        self.assertEqual(response.status_code,200,response.json)
        self.assertIs(gui.CACHE['full'],linear)
        self.assertTrue(out.is_file())

    def test_stale_frame_export_and_original_overwrite_are_rejected(self):
        gui.load_full(str(self.path))
        before=self.path.read_bytes()
        out=self.root/'must-not-exist.jpg'
        response=self.client.post('/api/export',json={'source_path':str(self.root/'other.png'),'out':str(out)})
        self.assertEqual(response.status_code,409)
        self.assertFalse(out.exists())
        response=self.client.post('/api/export',json={'source_path':str(self.path),'out':str(self.path)})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.path.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()

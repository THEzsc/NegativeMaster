"""Browser parity must retain full exports, scoped edits and original sidecars."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
import gui

class WebWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = patch.object(gui, 'SETTINGS_DIR', str(self.root/'settings'))
        self.settings.start()
        self.cache = dict(gui.CACHE)
        self.webcache = gui._WEB_PREVIEW
        gui._WEB_PREVIEW = None
        self.client = gui.app.test_client()
        self.path = self.root/'frame.tif'
        pixels = np.tile(np.linspace(30,220,1800,dtype=np.uint8),(1200,1))
        Image.fromarray(np.stack([pixels]*3,axis=-1)).save(self.path)
        self.original = self.path.read_bytes()
        self.data = dict(P={**gui.DEFAULTS,'mode':'bw','exposure':.7,'gamma':1.6},
                         cropN=dict(x0=.1,y0=.2,x1=.9,y1=.8),geometrySource='manual',curFmt='free',orient='land')
        Path(gui.sidecar_path(str(self.path))).write_text(gui._data_to_xml(self.data,str(self.path)))

    def tearDown(self):
        self.assertEqual(self.path.read_bytes(),self.original)
        gui.CACHE.clear();gui.CACHE.update(self.cache)
        gui._WEB_PREVIEW=self.webcache
        self.settings.stop();self.tmp.cleanup()

    def post(self,action,**body):
        return self.client.post('/api/workbench/'+action,json=body)

    def test_selective_apply_conflict_and_durable_undo(self):
        path=str(self.path)
        before=Path(gui.sidecar_path(path)).read_bytes()
        snap=self.post('snapshot',path=path).json
        result=self.post('apply',path=path,token=snap['token'],kind='batch',patch={'gamma':.85})
        self.assertEqual(result.status_code,200,result.json)
        current=self.post('snapshot',path=path).json
        self.assertEqual(current['params']['gamma'],.85)
        self.assertEqual(current['params']['exposure'],.7)
        self.assertEqual(current['data']['cropN'],self.data['cropN'])
        conflict=self.post('apply',path=path,token=snap['token'],patch={'gamma':1.2})
        self.assertEqual(conflict.status_code,400)
        undo=self.post('undo',undo_id=result.json['undo_id'])
        self.assertEqual(undo.status_code,200,undo.json)
        self.assertEqual(Path(gui.sidecar_path(path)).read_bytes(),before)

    def test_sync_only_chosen_group_and_emulsion_is_idempotent(self):
        path=str(self.path)
        snap=self.post('snapshot',path=path).json
        r=self.post('apply',path=path,token=snap['token'],kind='sync',groups=['exposure'],source={**gui.DEFAULTS,'exposure':-.4,'gamma':2.5})
        self.assertEqual(r.status_code,200,r.json)
        snap=self.post('snapshot',path=path).json
        self.assertEqual(snap['params']['gamma'],1.6)
        self.assertEqual(snap['params']['exposure'],-.4)
        for _ in range(2):
            r=self.post('apply',path=path,token=snap['token'],kind='film',emulsion=True)
            self.assertEqual(r.status_code,200,r.json)
            new=self.post('snapshot',path=path).json
            if _==1:self.assertEqual(new['params'],snap['params'])
            snap=new

    def test_bounded_preview_never_becomes_export_source(self):
        path=str(self.path)
        r=self.client.post('/api/load',json={'path':path,'preview':True})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual((r.json['w'],r.json['h']),(1800,1200))
        self.assertLessEqual(max(gui.CACHE['full'].shape[:2]),1500)
        out=self.root/'export.jpg'
        r=self.client.post('/api/export',json={**gui.DEFAULTS,'source_path':path,'mode':'positive','crop':0,'crop_rect':None,'out':str(out),'format':'jpg'})
        self.assertEqual(r.status_code,200,r.json)
        with Image.open(out) as im:self.assertEqual(im.size,(1800,1200))
        log=self.post('export-log',directory=str(self.root),items=[{'source':path,'path':str(out)}])
        self.assertEqual(log.status_code,200,log.json)
        self.assertTrue(Path(log.json['log']).is_file())

    def test_analysis_and_detail_do_not_change_active_cache_or_sidecar(self):
        path=str(self.path);before=Path(gui.sidecar_path(path)).read_bytes()
        sentinel=np.ones((3,4,3),dtype=np.float32)
        gui.CACHE.update(path='another',prev=sentinel)
        for kind in ('gamma','crop'):
            r=self.post('analyze',path=path,params=self.data['P'],kind=kind,reference=False)
            self.assertEqual(r.status_code,200,r.json)
            self.assertIn('report',r.json)
        r=self.post('detail',path=path,params={**gui.DEFAULTS,'mode':'positive'},side=1800)
        self.assertEqual(r.status_code,200)
        with Image.open(io.BytesIO(r.data)) as im:self.assertEqual(im.size,(1800,1200))
        self.assertIs(gui.CACHE['prev'],sentinel)
        self.assertEqual(gui.CACHE['path'],'another')
        self.assertEqual(Path(gui.sidecar_path(path)).read_bytes(),before)
        thumb=self.client.get('/api/workbench/thumb',query_string={'path':path})
        self.assertEqual(thumb.status_code,200)
        with Image.open(io.BytesIO(thumb.data)) as im:self.assertLessEqual(max(im.size),200)

    def test_saved_reference_is_resolved_without_replacing_active_reference(self):
        before = dict(gui.REF)
        opts = gui.make_opts({'use_match': True, 'reference_path': str(self.path)})
        self.assertIsNotNone(opts._ref_cdfs)
        self.assertEqual(gui.REF['path'], before['path'])
        self.assertIs(gui.REF['cdfs'], before['cdfs'])
        with self.assertRaises(FileNotFoundError):
            gui.make_opts({'use_match': True, 'reference_path': str(self.root/'missing.jpg')})

    def test_cross_origin_changes_are_rejected(self):
        r=self.client.post('/api/workbench/snapshot',json={'path':str(self.path)},headers={'Origin':'https://example.com'})
        self.assertEqual(r.status_code,403)

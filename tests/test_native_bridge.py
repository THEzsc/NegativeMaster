"""End-to-end tests for SwiftUI's local transport and shared renderer."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

class NativeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='nm-native-test-')
        cls.dir = Path(cls.temp.name)
        shutil.copytree(ROOT/'presets',cls.dir/'presets')
        cls.images = cls.dir/'photos';cls.images.mkdir()
        y,x=np.mgrid[:120,:180]
        image=np.stack([x/179*150+30,y/119*130+25,(x+y)/298*90+20],axis=-1).astype(np.uint8)
        cls.photo=cls.images/'negative.png';Image.fromarray(image).save(cls.photo)
        cls.positive=cls.images/'positive.png';Image.fromarray(255-image).save(cls.positive)
        env=dict(os.environ,NM_DATA_ROOT=str(cls.dir))
        cls.stderr=open(cls.dir/'worker.log','w')
        cls.p=subprocess.Popen([sys.executable,str(ROOT/'FilmDecastSwift/Support/native_worker.py'),str(ROOT)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=cls.stderr,text=True,env=env)
        cls.bootstrap=cls.call('bootstrap')
        cls.defaults=cls.bootstrap['defaults']
    @classmethod
    def tearDownClass(cls):
        cls.p.stdin.close();cls.p.wait(timeout=20);cls.p.stdout.close();cls.stderr.close();cls.temp.cleanup()
    @classmethod
    def call(cls,action='api',body=None,**kwargs):
        cls.p.stdin.write(json.dumps(dict(action=action,body=body or {},**kwargs))+'\n');cls.p.stdin.flush()
        line=cls.p.stdout.readline()
        if not line:raise AssertionError('Worker exited')
        r=json.loads(line)
        if not r['ok']:raise ValueError(r['error'])
        return r['result']
    @classmethod
    def api(cls,path,body=None,**kwargs):return cls.call(path=path,body=body,**kwargs)
    def image(self,r):return Image.open(io.BytesIO(base64.b64decode(r['bytes'])))
    def ready(self,job):
        for _ in range(200):
            r=self.api('/api/sheet/job/'+job,method='GET')
            if r['state']=='failed':self.fail(str(r))
            if r['state']=='ready':return r
            time.sleep(.03)
        self.fail('Prepare timed out')
    def test_export_atomic_no_clobber(self):
        self.assertIn('arw', self.bootstrap['rawExtensions'])
        out=self.dir/'collision.jpg'
        out.write_bytes(b'existing result')
        body=dict(path=str(self.photo),params=self.defaults,out=str(out),bits=8,overwrite=False)
        with self.assertRaises(ValueError): self.call('export',body)
        self.assertEqual(out.read_bytes(),b'existing result')
        self.assertEqual(list(self.dir.glob('.nm-export-*')),[])
        out.unlink()
        self.call('export',body)
        with Image.open(out) as image: image.verify()
        self.assertEqual(list(self.dir.glob('.nm-export-*')),[])

    def test_01_bootstrap_controls_and_catalog(self):
        b=self.bootstrap
        self.assertEqual(len(b['stocks']),100)
        keys={f['key'] for f in b['fields']}
        self.assertEqual(len(keys),57)
        self.assertIn('strip.leaderStyle',keys)
        self.assertIn('background.opacity',keys)
        self.assertTrue(all(f['title'] for f in b['fields']))
    def test_02_render_all_tone_controls_and_decode_options(self):
        body=dict(path=str(self.photo),params=self.defaults)
        basic=self.call('render',body)
        self.assertEqual(self.image(basic).size,(180,120))
        self.assertEqual(len(basic['histogram']['r']),64)
        p=dict(self.defaults,exposure=.4,vibrance=20,curve=[[0,0],[.5,.65],[1,1]],curve_r=[[0,0],[.5,.45],[1,1]],hsl={'orange':{'h':10,'s':20,'l':-10}},sharpen=.4,denoise=2,vignette=-30)
        enhanced=self.call('render',dict(path=str(self.photo),params=p))
        self.assertNotEqual(enhanced['bytes'],basic['bytes'])
        linear=self.call('render',dict(path=str(self.photo),params=dict(self.defaults,input_gamma='linear')))
        self.assertNotEqual(linear['bytes'],basic['bytes'])
        nd=self.call('render',dict(path=str(self.photo),params=dict(self.defaults,negadoctor=True)))
        self.assertNotEqual(nd['bytes'],basic['bytes'])
    def test_03_adjustments_sidecar_roundtrip(self):
        params=dict(self.defaults,crop_rect=[.1,.15,.9,.85],temp=12,curve_b=[[0,0],[1,.9]])
        before=hashlib.sha256(self.photo.read_bytes()).digest()
        self.call('save',dict(path=str(self.photo),params=params,sidecar=True))
        loaded=self.call('adjustments',dict(path=str(self.photo)))
        self.assertEqual(loaded['params'],params)
        self.assertTrue(Path(str(self.photo)+'.decast.xml').is_file())
        self.assertEqual(before,hashlib.sha256(self.photo.read_bytes()).digest())
    def test_04_export_tiff_jpeg_png_and_protect_original(self):
        before=self.photo.read_bytes()
        for fmt,bits in [('tif',16),('jpg',8),('png',8)]:
            path=self.dir/('export.'+fmt)
            self.call('export',dict(path=str(self.photo),params=dict(self.defaults,crop_rect=[.1,.1,.9,.9]),out=str(path),bits=bits,quality=91,resize=100))
            with Image.open(path) as im:self.assertEqual(max(im.size),100)
        with self.assertRaisesRegex(ValueError,'原始照片'):
            self.call('export',dict(path=str(self.photo),params=self.defaults,out=str(self.photo),bits=8))
        self.assertEqual(before,self.photo.read_bytes())
    def test_05_presets(self):
        self.api('/api/presets',dict(name='Native Test',data=dict(self.defaults,exposure=.7)))
        loaded=self.api('/api/presets?name=Native%20Test',method='GET')
        self.assertEqual(loaded['data']['exposure'],.7)
        self.api('/api/presets?name=Native%20Test',method='DELETE')
        with self.assertRaises(ValueError):self.api('/api/presets?name=Native%20Test',method='GET')
    def test_06_sheet_full_roundtrip(self):
        job=self.api('/api/sheet/prepare',dict(paths=[str(self.photo),str(self.positive)],positiveOnly=True))['job']
        ready=self.ready(job);order=[i['id'] for i in ready['items']][::-1]
        config=json.loads(json.dumps(self.bootstrap['sheetDefaults']))
        config.update(width=1200,columns=2)
        config['strip'].update(fontStyle='film-kodak',leaderStyle='ribbon',edgeGlow=.3,edgeArrow='right',separation='paper',sprocketStyle='cinema',leakPhotoCount=1)
        config['background'].update(mode='transparent',opacity=.4)
        config['frameOverrides']=[dict(rotation=90,label='TEST',crop=dict(scale=1.5,x=.3,y=.6)),{}]
        payload=dict(job=job,order=order,stockId=self.bootstrap['stocks'][0]['id'],config=config)
        preview=self.api('/api/sheet/preview',payload)
        self.assertEqual(self.image(preview).width,1200)
        frame=self.call('frame',dict(job=job,id=order[0],override=config['frameOverrides'][0],ratio='3:2',fit='cover'))
        self.assertEqual(self.image(frame).size,(1200,800))
        export=self.api('/api/sheet/export',dict(payload,out=str(self.dir/'sheet.png'),format='png'))['export']
        for _ in range(200):
            r=self.api('/api/sheet/export/'+export,method='GET')
            if r['state']!='running':break
            time.sleep(.05)
        self.assertEqual(r['state'],'ready',r)
        with Image.open(r['out']) as im:self.assertEqual(im.mode,'RGBA');self.assertEqual(im.width,1200)
        self.api('/api/sheet/background',dict(job=job),files=dict(file=str(self.positive)))
        config['background'].update(mode='blur',sourceIndex='custom')
        project=self.dir/'project.zip'
        self.api('/api/sheet/project/export',payload,output=str(project))
        with zipfile.ZipFile(project) as z:
            manifest=json.loads(z.read('manifest.json'))
            self.assertEqual(manifest['config']['frameOverrides'][0]['rotation'],90)
            self.assertIn('backgroundFile',manifest)
            self.assertEqual(len(manifest['assets']),2)
        restored=self.api('/api/sheet/project/import',files=dict(file=str(project)))
        r=self.ready(restored['job'])
        self.assertTrue(r['hasBackground']);self.assertTrue(Path(r['backgroundFile']).is_file())
        self.assertEqual(restored['project']['config']['frameOverrides'],config['frameOverrides'])
    def test_07_white_balance_sampling(self):
        r=self.call('wbtemp',dict(self.defaults,path=str(self.photo),wb_rect=[.2,.2,.8,.8]))
        self.assertTrue(-100<=r['temp']<=100)
        self.assertTrue(-100<=r['tint']<=100)
    def test_08_all_film_lettering_and_exposure_styles(self):
        job=self.api('/api/sheet/prepare',dict(paths=[str(self.positive)],positiveOnly=True))['job']
        ready=self.ready(job)
        config=json.loads(json.dumps(self.bootstrap['sheetDefaults']))
        config.update(width=1200,columns=2)
        payload=dict(job=job,order=[ready['items'][0]['id']],stockId=self.bootstrap['stocks'][0]['id'],config=config)
        keys=['strip.fontStyle','strip.leaderStyle','strip.sprocketStyle','strip.sprocketRim','strip.separation','background.mode']
        for key in keys:
            field=next(f for f in self.bootstrap['fields'] if f['key']==key)
            section,name=key.split('.')
            original=config[section][name]
            for option in field['options']:
                with self.subTest(field=key,value=option['value']):
                    config[section][name]=option['value']
                    image=self.image(self.api('/api/sheet/preview',payload))
                    self.assertEqual(image.width,1200)
            config[section][name]=original
    def test_09_invalid_input_is_recoverable(self):
        with self.assertRaises(ValueError):self.call('render',dict(path=str(self.dir/'missing.png'),params=self.defaults))
        self.assertTrue(self.call('bootstrap')['stocks'])
        with self.assertRaises(ValueError):self.api('/api/sheet/preview',dict(job='missing'))

    def test_10_lazy_negative_matches_legacy_render(self):
        body=dict(path=str(self.photo),params=dict(self.defaults,rotate=90,level_angle=.3))
        old=self.call('render',body)
        lean=self.call('render',dict(body,include_negative=False))
        self.assertNotIn('negative',lean)
        self.assertEqual(lean['bytes'],old['bytes'])
        self.assertEqual(self.call('negative',body)['bytes'],old['negative'])
        self.assertLess(len(json.dumps(lean)),len(json.dumps(old)))

    def test_11_lightweight_thumbnail(self):
        job=self.api('/api/sheet/prepare',dict(paths=[str(self.positive)],positiveOnly=True))['job']
        ready=self.ready(job);fid=ready['items'][0]['id']
        thumb=self.image(self.call('thumbnail',dict(job=job,id=fid)))
        self.assertEqual(thumb.size,(160,107))
        with self.assertRaises(ValueError):self.call('thumbnail',dict(job='missing',id=fid))
        self.assertTrue(self.call('bootstrap')['stocks'])

    def test_12_archive_lifecycle_and_artwork_backup(self):
        catalog=self.api('/api/archive/catalog',method='GET')
        self.assertEqual(Path(catalog['storage']),(self.dir/'archive_data').resolve())
        art=self.api('/api/archive/artwork',method='GET')['artworks'][0]
        roll=self.api('/api/archive/rolls',dict(title='Native QA',stock_id='kodak-gold-200',status='scanning',tags=['synthetic']))['roll']
        rid=roll['id']
        roll=self.api('/api/archive/rolls/'+rid+'/cover',dict(artwork_id=art['id']))['roll']
        self.assertEqual(roll['cover_artwork'],art['id'])
        roll=self.api('/api/archive/rolls/'+rid,dict(roll,camera='QA camera'),method='PUT')['roll']
        self.assertEqual(roll['cover_license'],art['license'])
        roll=self.api('/api/archive/rolls/'+rid+'/frames',dict(directory=str(self.images),mode='all'))['roll']
        self.assertGreaterEqual(len(roll['frames']),2)
        fid=roll['frames'][0]['id']
        roll=self.api('/api/archive/rolls/'+rid+'/frames/'+fid,dict(rating=4,notes='Keep'),method='PUT')['roll']
        self.assertEqual(next(f for f in roll['frames'] if f['id']==fid)['rating'],4)
        backup=self.dir/'archive-backup.zip'
        self.api('/api/archive/backup',method='GET',output=str(backup))
        restored=self.api('/api/archive/restore',files=dict(file=str(backup)))
        self.assertEqual(restored['imported'],1)
        copied=self.api('/api/archive/rolls/'+restored['ids'][0],method='GET')['roll']
        self.assertEqual(copied['cover_license'],art['license'])
        self.assertEqual(copied['cover_credit'],art['credit'])
        self.api('/api/archive/rolls/'+rid,method='DELETE')
        self.api('/api/archive/rolls/'+copied['id'],method='DELETE')
        self.assertEqual(self.api('/api/archive/rolls',method='GET')['stats']['rolls'],0)
        self.assertTrue(self.photo.exists())

    def test_13_workflow_gamma_only_preserves_edits(self):
        first=dict(self.defaults,exposure=.6,crop_rect=[.1,.2,.8,.9],rotate=90,temp=18)
        second=dict(self.defaults,exposure=-.3,crop_rect=[.2,.1,.9,.8],rotate=180,temp=-8)
        paths=[str(self.photo),str(self.positive)]
        for path,p in zip(paths,[first,second]):self.call('save',dict(path=path,params=p,sidecar=True))
        report=self.api('/api/workflow/analyze',dict(paths=paths,current_path=paths[0],current=dict(P=first)))
        self.assertIn('recommendation',report['report'])
        result=self.api('/api/workflow/roll-gamma',dict(paths=paths,parameter_key='gamma',gamma=.85,current_path=paths[0],current=dict(P=first,cropN=dict(zip(['x0','y0','x1','y1'],first['crop_rect'])))))
        self.assertEqual(result['updated'],paths)
        for path,p in zip(paths,[first,second]):
            loaded=self.call('adjustments',dict(path=path))['params']
            self.assertEqual(loaded,dict(p,gamma=.85))
        self.call('save',dict(path=paths[1],params=dict(second,mode='positive'),sidecar=True))
        mismatch=self.api('/api/workflow/roll-gamma',dict(paths=[paths[1]],parameter_key='gamma',gamma=1.1))
        self.assertEqual(mismatch['updated'],[])
        self.assertEqual(len(mismatch['errors']),1)

if __name__=='__main__':unittest.main()

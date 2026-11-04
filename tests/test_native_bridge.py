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
        env=dict(os.environ,NM_DATA_ROOT=str(cls.dir),NM_PREVIEW_CACHE=str(cls.dir/'preview-cache'))
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
    def test_batch_patch_is_selective_conflict_checked_and_reversible(self):
        photo=self.images/'batch-edit.png';photo.write_bytes(self.photo.read_bytes())
        p=dict(self.defaults,mode='bw',gamma=1.3,exposure=.4,rotate=90,flip='h',crop_rect=[.1,.2,.9,.8],level_angle=.25)
        self.call('save',dict(path=str(photo),params=p,sidecar=True))
        sidecar=Path(str(photo)+'.decast.xml');before=sidecar.read_bytes();original=photo.read_bytes()
        snapshot=self.call('batch_snapshot',dict(path=str(photo)))
        r=self.call('batch_apply',dict(path=str(photo),token=snapshot['token'],patch={'gamma':1.65}))
        expected=dict(p,gamma=1.65)
        actual=self.call('adjustments',dict(path=str(photo)))['params']
        self.assertEqual(actual,expected)
        with self.assertRaises(ValueError):self.call('batch_apply',dict(path=str(photo),token=snapshot['token'],patch={'gamma':1.8}))
        self.call('batch_restore',dict(undo_id=r['undo_id']))
        self.assertEqual(sidecar.read_bytes(),before)
        self.assertEqual(photo.read_bytes(),original)
        with self.assertRaises(ValueError):self.call('batch_apply',dict(path=str(photo),token=snapshot['token'],patch={'exposure':2}))
        crop={'crop_rect':[.2,.1,.8,.9],'level_angle':-.4,'geometry_source':'auto'}
        r=self.call('batch_apply',dict(path=str(photo),token=snapshot['token'],patch=crop))
        changed=self.call('adjustments',dict(path=str(photo)))['params']
        self.assertEqual(changed,dict(p,**crop))
        self.call('save',dict(path=str(photo),params=dict(changed,exposure=.9),sidecar=True))
        later=sidecar.read_bytes()
        with self.assertRaises(ValueError):self.call('batch_restore',dict(undo_id=r['undo_id']))
        self.assertEqual(sidecar.read_bytes(),later)

    def test_batch_new_sidecar_undo_and_corrupt_metadata(self):
        photo=self.images/'batch-new.png';photo.write_bytes(self.photo.read_bytes())
        snap=self.call('batch_snapshot',dict(path=str(photo)))
        r=self.call('batch_apply',dict(path=str(photo),token=snap['token'],patch={'gamma':1.6}))
        sidecar=Path(str(photo)+'.decast.xml');self.assertTrue(sidecar.is_file())
        self.call('batch_restore',dict(undo_id=r['undo_id']))
        self.assertFalse(sidecar.exists())
        sidecar.write_text('<broken')
        with self.assertRaises(ValueError):self.call('batch_snapshot',dict(path=str(photo)))
        self.assertEqual(sidecar.read_text(),'<broken')

    def test_film_scope_patches_each_frame_without_copying_geometry(self):
        # A preset cannot smuggle crop, rotation or input coordinates into another frame.
        preset='native-film-scope'
        (self.dir/'presets'/f'{preset}.json').write_text(json.dumps(dict(
            gamma=1.25, contrast=.1, crop_rect=[0,0,1,1], rotate=180, film_base_rect=[1,2,3,4])))
        for i in range(2):
            photo=self.images/f'film-scope-{i}.png';photo.write_bytes(self.photo.read_bytes())
            p=dict(self.defaults,mode='positive',gamma=1.5+i*.2,exposure=i*.4,
                   crop_rect=[.1+i*.02,.2,.9,.8],rotate=i*90,level_angle=i*.3)
            self.call('save',dict(path=str(photo),params=p,sidecar=True))
            sidecar=Path(str(photo)+'.decast.xml')
            sidecar.write_text(sidecar.read_text().replace('fmt="free"','fmt="3:2"').replace('orient="land"','orient="port"'))
            before=sidecar.read_bytes()
            snap=self.call('batch_snapshot',dict(path=str(photo)))
            changed=self.call('film_apply',dict(path=str(photo),token=snap['token'],mode='bw'))
            self.assertEqual(changed['params'],dict(p,mode='bw'))
            self.assertIn('fmt="3:2"',sidecar.read_text())
            self.assertIn('orient="port"',sidecar.read_text())
            with self.assertRaises(ValueError):
                self.call('film_apply',dict(path=str(photo),token=snap['token'],mode='color'))
            self.call('batch_restore',dict(undo_id=changed['undo_id']))
            self.assertEqual(before,sidecar.read_bytes())
            snap=self.call('batch_snapshot',dict(path=str(photo)))
            changed=self.call('film_apply',dict(path=str(photo),token=snap['token'],preset=preset))
            self.assertEqual(changed['params'],dict(p,gamma=1.25,contrast=.1))
            self.assertEqual(photo.read_bytes(),self.photo.read_bytes())
            snap=self.call('batch_snapshot',dict(path=str(photo)))
            for bad in ({'mode':'bogus'}, {'preset':'../escape'}, {'preset':'missing-preset'}):
                with self.assertRaises(ValueError):
                    self.call('film_apply',dict(path=str(photo),token=snap['token'],**bad))
            self.assertEqual(self.call('batch_snapshot',dict(path=str(photo)))['token'],snap['token'])

    def test_emulsion_defaults_preserve_saved_edits_and_batch_is_idempotent(self):
        fresh=self.images/'emulsion-new.png';fresh.write_bytes(self.photo.read_bytes())
        defaults=self.call('adjustments',dict(path=str(fresh)))
        self.assertEqual(defaults['params']['flip'],'h')
        self.assertTrue(defaults['params']['emulsion_mirrored'])
        self.assertEqual(defaults['data'],{})
        self.assertFalse(Path(str(fresh)+'.decast.xml').exists())
        for i, flip in enumerate(('none','h','v')):
            photo=self.images/f'emulsion-old-{i}.png';photo.write_bytes(self.photo.read_bytes())
            old=dict(self.defaults,flip=flip,rotate=90,gamma=1.1+i*.2,level_angle=.5,
                     crop_rect=[.125,.25,.625,.875],wb_point=[.25,.125])
            old.pop('emulsion_mirrored')  # Old app versions did not store this property.
            self.call('save',dict(path=str(photo),params=old,sidecar=True))
            xml=Path(str(photo)+'.decast.xml'); before=xml.read_bytes()
            self.assertEqual(self.call('adjustments',dict(path=str(photo)))['params'],old)
            snap=self.call('batch_snapshot',dict(path=str(photo)))
            changed=self.call('film_apply',dict(path=str(photo),token=snap['token'],emulsion=True))
            p=changed['params']
            self.assertTrue(p['emulsion_mirrored']);self.assertEqual(p['gamma'],old['gamma'])
            if flip=='none':
                self.assertEqual(p['flip'],'v')
                self.assertEqual(p['crop_rect'],[.125,.125,.625,.75])
                self.assertEqual(p['wb_point'],[.25,.875])
                self.assertEqual(p['level_angle'],-.5)
            else:
                for key,value in old.items():self.assertEqual(p[key],value)
            repeated=self.call('batch_snapshot',dict(path=str(photo)))
            again=self.call('film_apply',dict(path=str(photo),token=repeated['token'],emulsion=True))
            self.assertEqual(again['params'],p)
            self.call('batch_restore',dict(undo_id=again['undo_id']))
            self.call('batch_restore',dict(undo_id=changed['undo_id']))
            self.assertEqual(xml.read_bytes(),before)
            with self.assertRaises(ValueError):
                self.call('film_apply',dict(path=str(photo),token=snap['token'],emulsion='true'))

    def test_emulsion_disable_survives_reload_and_orientation_sync(self):
        photo=self.images/'emulsion-disabled.png';photo.write_bytes(self.photo.read_bytes())
        snap=self.call('batch_snapshot',dict(path=str(photo)))
        changed=self.call('film_apply',dict(path=str(photo),token=snap['token'],emulsion=False))
        self.assertEqual(changed['params']['flip'],'none')
        self.assertFalse(self.call('adjustments',dict(path=str(photo)))['params']['emulsion_mirrored'])
        snap=self.call('batch_snapshot',dict(path=str(photo)))
        source=dict(self.defaults,flip='v',emulsion_mirrored=False)
        changed=self.call('sync_apply',dict(path=str(photo),token=snap['token'],groups=['orientation'],source=source))
        self.assertEqual(changed['params']['flip'],'v')
        self.assertFalse(changed['params']['emulsion_mirrored'])

    def test_sync_selected_groups_preserve_individual_edits_and_allow_undo(self):
        groups={g['id']:g for g in self.bootstrap['syncGroups']}
        for key in ('gamma','exposure','crop','orientation','samples'):
            self.assertFalse(groups[key]['selected'])
        photo=self.images/'selective-sync.png';photo.write_bytes(self.photo.read_bytes())
        original=dict(self.defaults,mode='bw',gamma=1.9,exposure=.7,rotate=90,
                      crop_rect=[.15,.1,.85,.9],level_angle=.3,geometry_source='auto',
                      hsl={'red':{'h':12,'s':-8,'l':2}},film_base_rect=[.1,.1,.2,.2])
        self.call('save',dict(path=str(photo),params=original,sidecar=True))
        before=Path(str(photo)+'.decast.xml').read_bytes()
        source=dict(self.defaults,mode='positive',gamma=.85,exposure=-2,temp=28,tint=-10,
                    rotate=180,crop_rect=None,hsl={'blue':{'h':4,'s':14,'l':6}})
        snap=self.call('batch_snapshot',dict(path=str(photo)))
        r=self.call('sync_apply',dict(path=str(photo),token=snap['token'],groups=['whiteBalance','hsl'],source=source))
        expected=dict(original,wb=source['wb'],temp=28,tint=-10,hsl=source['hsl'])
        self.assertEqual(r['params'],expected)
        # Merely selecting/saving an unchanged frame must not invalidate batch undo.
        after=self.call('batch_snapshot',dict(path=str(photo)))
        self.call('save',dict(path=str(photo),params=expected,sidecar=True))
        self.assertEqual(self.call('batch_snapshot',dict(path=str(photo)))['token'],after['token'])
        self.call('batch_restore',dict(undo_id=r['undo_id']))
        self.assertEqual(Path(str(photo)+'.decast.xml').read_bytes(),before)
        for groups in ([],['invented'],['crop','invented']):
            with self.assertRaises(ValueError):
                self.call('sync_apply',dict(path=str(photo),token=snap['token'],groups=groups,source=source))
        self.assertEqual(Path(str(photo)+'.decast.xml').read_bytes(),before)

    def test_sync_can_clear_crop_without_touching_orientation_or_tone(self):
        photo=self.images/'clear-synced-crop.png';photo.write_bytes(self.photo.read_bytes())
        original=dict(self.defaults,crop_rect=[.2,.1,.8,.9],level_angle=.5,geometry_source='auto',rotate=90,gamma=1.4)
        self.call('save',dict(path=str(photo),params=original,sidecar=True))
        snap=self.call('batch_snapshot',dict(path=str(photo)))
        result=self.call('sync_apply',dict(path=str(photo),token=snap['token'],groups=['crop'],source=self.defaults))
        self.assertEqual(result['params'],dict(original,crop_rect=None,level_angle=0,geometry_source='manual'))
        self.assertFalse(self.call('adjustments',dict(path=str(photo)))['data'].get('cropN'))
        with self.assertRaises(ValueError):
            self.call('sync_apply',dict(path=str(photo),token=snap['token'],groups=['gamma'],source=self.defaults))

    def test_fast_gamma_analysis_keeps_sources_and_has_per_frame_values(self):
        photo=self.images/'batch-gamma.png'
        scene=np.linspace(0,1,240*160).reshape(160,240)**1.6
        image=np.repeat(np.power(10.,-(.2+1.4*scene))[...,None],3,axis=-1)
        Image.fromarray((image*255).astype('uint8')).save(photo)
        p=dict(self.defaults,mode='bw',wb='none',input_gamma='linear',black_pct=0,white_pct=100,contrast=0)
        before=photo.read_bytes()
        a=self.call('analyze_gamma',dict(path=str(photo),params=dict(p,exposure=0)))['report']
        b=self.call('analyze_gamma',dict(path=str(photo),params=dict(p,exposure=.5)))['report']
        self.assertEqual(a['method'],'per-frame-finished-midtones-v1')
        self.assertGreater(a['recommendation'],b['recommendation'])
        self.assertEqual(photo.read_bytes(),before)
        self.assertFalse(Path(str(photo)+'.decast.xml').exists())
        rejected=self.call('analyze_gamma',dict(path=str(photo),params=dict(p,mode='positive')))['report']
        self.assertIsNone(rejected['recommendation'])

    def test_preview_resolutions_and_geometry_provenance(self):
        photo=self.images/'large-preview.jpg'
        Image.new('RGB',(3000,2000),(120,100,60)).save(photo)
        quick=self.call('render',dict(path=str(photo),params=self.defaults,interactive=True,include_negative=False))
        detail=self.call('render',dict(path=str(photo),params=self.defaults,include_negative=False))
        self.assertLessEqual(max(self.image(quick).size),720)
        self.assertEqual(max(self.image(detail).size),1500)
        self.assertEqual((detail['fullWidth'],detail['fullHeight']),(3000,2000))
        out=self.dir/'preview-then-export.jpg'
        self.call('export',dict(path=str(photo),params=self.defaults,out=str(out),bits=8,resize=0))
        with Image.open(out) as exported:
            self.assertEqual(exported.size,(3000,2000))
        p=dict(self.defaults,geometry_source='auto')
        self.call('save',dict(path=str(photo),params=p,sidecar=True))
        self.assertEqual(self.call('adjustments',dict(path=str(photo)))['params']['geometry_source'],'auto')
        self.assertIn('geometry_source="auto"',Path(str(photo)+'.decast.xml').read_text())

    def test_detail_preview_resolves_source_pixels_and_preserves_geometry(self):
        photo = self.images/'fine-lines.png'
        lines = np.tile(np.where(np.arange(3200) % 2, 210, 40).astype(np.uint8), (640, 1))
        Image.fromarray(np.repeat(lines[..., None], 3, axis=2)).save(photo)
        original = photo.read_bytes()
        p = dict(self.defaults, mode='positive', wb='none', gamma=1, contrast=0,
                 crop_rect=[.1, .1, .9, .9])
        low = np.asarray(self.image(self.call('render', dict(path=str(photo), params=p, include_negative=False))))
        out = self.dir/'detail-100.jpg'
        result = self.call('detail', dict(path=str(photo), params=p, side=3200, out=str(out)))
        self.assertEqual((result['width'], result['height']), (3200, 640))
        with Image.open(out) as im:
            high = np.asarray(im)
            self.assertTrue(im.info.get('icc_profile'))
        self.assertGreater(float(high[320, :, 0].std()), float(low[low.shape[0]//2, :, 0].std()) + 40)
        half = self.dir/'detail-50.jpg'
        result = self.call('detail', dict(path=str(photo), params=p, side=1600, out=str(half)))
        self.assertEqual((result['width'], result['height']), (1600, 320))
        rotated = self.dir/'detail-rotated.jpg'
        result = self.call('detail', dict(path=str(photo), params=dict(p, rotate=90), side=3200, out=str(rotated)))
        self.assertEqual((result['width'], result['height']), (640, 3200))
        negative = self.dir/'detail-negative.jpg'
        result = self.call('detail', dict(path=str(photo), params=p, side=3200, negative=True, out=str(negative)))
        self.assertEqual(result['width'], 3200)
        for output in (out, photo):
            before = output.read_bytes()
            with self.assertRaises(ValueError):
                self.call('detail', dict(path=str(photo), params=p, side=3200, out=str(output)))
            self.assertEqual(output.read_bytes(), before)
        self.assertEqual(photo.read_bytes(), original)
        self.assertFalse(Path(str(photo)+'.decast.xml').exists())
        # A detail request must not replace the normal worker's low-resolution cache.
        after = self.call('render', dict(path=str(photo), params=p, include_negative=False))
        self.assertEqual(self.image(after).width, 1500)

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

    def test_jpeg_export_is_shared_by_sheet_and_archive_after_worker_restart(self):
        source = self.images / 'jpeg-priority.tif'
        Image.new('RGB', (90, 60), 'gray').save(source)
        custom = self.dir / 'arbitrary-destination'; custom.mkdir(exist_ok=True)
        jpeg = custom / 'custom-name-7.jpg'
        p = dict(self.defaults, mode='positive')
        self.call('export', dict(path=str(source), params=p, out=str(jpeg), bits=8))
        log = self.call('export_log', dict(directory=str(custom), items=[dict(source=str(source), path=str(jpeg))]))
        self.assertEqual(json.loads(Path(log['log']).read_text())['items'][0]['path'], str(jpeg.resolve()))
        self.call('export', dict(path=str(source), params=p, out=str(custom/'later.tif'), bits=16))
        job = self.api('/api/sheet/prepare', dict(paths=[str(source)]))['job']
        self.assertEqual(self.ready(job)['items'][0]['path'], str(jpeg.resolve()))
        request = dict(action='api', path='/api/archive/index-plan', body=dict(paths=[str(source)]))
        env = dict(os.environ, NM_DATA_ROOT=str(self.dir), NM_PREVIEW_CACHE=str(self.dir/'preview-cache'))
        process = subprocess.run([sys.executable, str(ROOT/'FilmDecastSwift/Support/native_worker.py'), str(ROOT)],
            input=json.dumps(request)+'\n', capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['items'][0]['path'], str(jpeg.resolve()))

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

    def test_shared_decode_is_unchanged_after_editing_and_negative_comparison(self):
        body = dict(path=str(self.photo), params=self.defaults, include_negative=False)
        original = self.call('render', body)['bytes']
        for mode in ('color', 'bw', 'positive'):
            params = dict(self.defaults, mode=mode, rotate=90, flip='h', level_angle=.3,
                          exposure=.7, gamma=1.4, crop_rect=[.1,.1,.9,.9],
                          hsl={'red': {'h': 12, 's': -8, 'l': 2}})
            self.call('render', dict(body, params=params))
            self.call('negative', dict(body, params=params))
            self.assertEqual(self.call('render', body)['bytes'], original)

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

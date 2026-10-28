"""Geometry-based regressions; no source photograph or sidecar is modified."""
import unittest
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decast


def scene(h=400, w=600):
    y, x = np.mgrid[:h, :w]
    v = .42 + .18*np.sin(x/13)*np.cos(y/17) + .10*np.sin((x+y)/31)
    return np.repeat(v[..., None], 3, axis=2).astype(np.float32)


def frame(border=.95, tilt=0., color=None, double=False):
    a = scene()
    h,w=a.shape[:2];y,x=np.mgrid[:h,:w]
    mask=(x>=36+tilt*(y-h/2))&(x<564+tilt*(y-h/2))&(y>=24-tilt*(x-w/2))&(y<376-tilt*(x-w/2))
    a[~mask] = border
    if double:
        a[:16]=.01;a[384:]=.01;a[:,:28]=.01;a[:,572:]=.01
    if color is not None:
        a *= np.array(color)
    return a


def soft_frame(h=600, w=900, seed=47, border=True, holder=True):
    """Fine grain, busy center and a diffuse low-contrast peripheral film band."""
    y,x=np.mgrid[:h,:w];rng=np.random.default_rng(seed)
    a=.87+.025*x/w+.028*np.sin(x/17)*np.cos(y/9)
    a[(np.sin(x/13)*np.cos(y/17)>.5)&(y<h*.85)]=.1
    if border:
        blend=np.clip((y-(h-h*.025-4))/8,0,1)
        a=a*(1-blend)+(.915+.025*x/w)*blend
    a+=rng.normal(0,.008,(h,w))
    if holder: a[:,-max(3,int(w*.02)):]=.015
    return np.repeat(a[...,None],3,axis=2).astype('float32')


class FilmFrameTests(unittest.TestCase):
    def assertRectNear(self, actual, expected, tolerance=.014):
        np.testing.assert_allclose(actual, expected, atol=tolerance, rtol=0)

    def test_soft_border_recovers_without_excessive_scene_trim(self):
        for h,w,seed in ((600,900,47),(600,900,53),(935,1400,47),(935,1400,53)):
            for exposure in (.25,1.):
                with self.subTest(size=(h,w),seed=seed,exposure=exposure):
                    a=soft_frame(h,w,seed)*exposure
                    result=decast.detect_film_frame(a)
                    self.assertIsNotNone(result['edges']['bottom'])
                    self.assertEqual(result['edges']['bottom']['method'],'soft-border')
                    self.assertGreater(result['rect'][3],.955)
                    self.assertLess(result['rect'][3],.975)
                    self.assertEqual(result['rect'][:2],[0.,0.])
                    # Weak-edge evidence may crop but cannot supply a rotation.
                    self.assertLess(result['edges']['bottom']['confidence'],.55)

    def test_soft_border_is_repeatable_and_tracks_orientation(self):
        a = soft_frame()
        original = decast.detect_film_frame(a)
        self.assertEqual(original, decast.detect_film_frame(a))
        r = original['rect']
        transformed = decast.detect_film_frame(np.rot90(a)[:, ::-1])
        np.testing.assert_allclose(transformed['rect'],
                                   [1-r[3], 1-r[2], 1-r[1], 1-r[0]], atol=.006, rtol=0)
        self.assertEqual(transformed['edges']['left']['method'], 'soft-border')

    def test_weak_texture_and_missing_physical_frame_do_not_create_crop(self):
        for h,w in ((600,900),(935,1400)):
            with self.subTest(size=(h,w)):
                result=decast.detect_film_frame(soft_frame(h,w,border=False))
                self.assertEqual(result['rect'][0:2],[0.,0.])
                self.assertEqual(result['rect'][3],1.)
                self.assertEqual(decast.detect_film_rect(soft_frame(h,w,holder=False)),[0.,0.,1.,1.])

    def test_black_and_white_borders(self):
        for value in (.01,.95):
            with self.subTest(value=value):
                r=decast.detect_film_frame(frame(value))
                self.assertEqual(r['detected_edges'],4)
                self.assertRectNear(r['rect'],[.06,.06,.94,.94])

    def test_thin_border(self):
        a=scene();a[:3]=.99;a[-3:]=.99;a[:,:3]=.99;a[:,-3:]=.99
        self.assertRectNear(decast.detect_film_rect(a),[.005,.0075,.995,.9925],.008)

    def test_no_border_does_not_invent_crop(self):
        for a in (scene(),np.full((400,600,3),.4,np.float32),np.zeros((40,60,3))):
            self.assertEqual(decast.detect_film_rect(a),[0,0,1,1])

    def test_subject_lines_are_not_frame(self):
        a=scene();a[60:64]=.99;a[:,75:80]=.01
        self.assertEqual(decast.detect_film_rect(a),[0,0,1,1])

    def test_color_cast_and_exposure(self):
        for exposure in (.1,1.):
            a=frame(color=[1.,.5,.25])*exposure
            self.assertRectNear(decast.detect_film_rect(a),[.06,.06,.94,.94])

    def test_partial_frame(self):
        a=scene();a[:,:90]=.01
        r=decast.detect_film_frame(a)
        self.assertEqual(r['detected_edges'],1)
        self.assertRectNear(r['rect'],[.15,0,1,1])

    def test_tilt_and_deskew(self):
        a=frame(tilt=.04)
        r=decast.detect_film_rect(a)
        self.assertRectNear(r,[.074,.09,.926,.91])
        angle=decast.estimate_skew(a)
        self.assertAlmostEqual(angle,-np.degrees(np.arctan(.04)),delta=.3)

    def test_holder_plus_film_base(self):
        self.assertRectNear(decast.detect_film_rect(frame(double=True)),[.06,.06,.94,.94],.01)

    def test_dust_and_sensor_noise(self):
        rng=np.random.default_rng(45);a=frame()
        a+=rng.normal(0,.002,a.shape).astype(np.float32)
        for x,y in zip(rng.integers(0,600,35),rng.integers(0,400,35)):
            a[max(0,y-2):y+2,max(0,x-2):x+2]=.01
        self.assertRectNear(decast.detect_film_rect(a),[.06,.06,.94,.94])

class AutoCropApiTests(unittest.TestCase):
    def test_crop_uses_displayed_rotation_and_flip(self):
        import gui
        from unittest.mock import patch
        a=frame(tilt=.035)
        client=gui.app.test_client()
        with patch.dict(gui.CACHE, prev=a):
            result=client.post('/api/autocrop',json=dict(rotate=90,flip='h',level=False,level_angle=2.0))
        self.assertEqual(result.status_code,200)
        expected=decast.detect_film_alignment(decast.orient_image(a,90,'h'),2.0,auto_level=False)
        self.assertEqual(result.json['rect'],expected['rect'])
        self.assertEqual(result.json['angle'],2.0)

    def test_uncertain_and_unloaded(self):
        import gui
        from unittest.mock import patch
        client=gui.app.test_client()
        with patch.dict(gui.CACHE, prev=None):
            self.assertEqual(client.post('/api/autocrop',json={}).status_code,400)
        with patch.dict(gui.CACHE, prev=scene()):
            result=client.post('/api/autocrop',json={}).json
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(result['rect'],[0,0,1,1])


if __name__=='__main__':
    unittest.main()

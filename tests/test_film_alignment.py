import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import numpy as np
from test_film_detection import frame, scene
import decast
import film_reference


class AlignmentTests(unittest.TestCase):
    def test_small_angles_and_idempotence(self):
        for angle in (-.45, .12, .6):
            with self.subTest(angle=angle):
                a=frame(tilt=-np.tan(np.radians(angle)))
                first=decast.detect_film_alignment(a)
                self.assertAlmostEqual(first['angle'],angle,delta=.12)
                again=decast.detect_film_alignment(a,current_angle=first['angle'])
                self.assertEqual(first['rect'],again['rect'])
                self.assertEqual(first['angle'],again['angle'])

    def test_rotation_crop_contains_no_border_or_black_corners(self):
        for angle in (-3., .6, 2.5):
            a=frame(tilt=-np.tan(np.radians(angle)))
            for rotation,flip in [(0,'none'),(90,'h'),(180,'v')]:
                with self.subTest(angle=angle,rotation=rotation,flip=flip):
                    oriented=decast.orient_image(a,rotation,flip)
                    result=decast.detect_film_alignment(oriented)
                    mask=(np.max(oriented,axis=2)<.94).astype(np.float32)
                    aligned=decast._deskew_lin(np.repeat(mask[...,None],3,axis=2),result['angle'])
                    h,w=mask.shape;rc=result['rect']
                    xa,ya=int(np.ceil(rc[0]*w)),int(np.ceil(rc[1]*h))
                    xb,yb=int(np.floor(rc[2]*w)),int(np.floor(rc[3]*h))
                    self.assertGreater(float(aligned[ya:yb,xa:xb].min()),.99)
                    self.assertGreater((xb-xa)*(yb-ya)/(h*w),.65)

    def test_weak_image_uses_reference_without_claiming_detection(self):
        ref=dict(rect=[.02,.03,.98,.97],angle=.6,samples=7)
        r=decast.detect_film_alignment(np.ones((400,600,3))*.4,reference=ref)
        self.assertEqual(r['status'],'referenced')
        self.assertEqual(r['angle'],.6)
        self.assertEqual(r['detected_edges'],0)
        self.assertEqual(r['reference_samples'],7)
        np.testing.assert_allclose(r['rect'],ref['rect'],atol=.0001)

    def test_unknown_geometry_preserves_manual_angle(self):
        r=decast.detect_film_alignment(scene(),current_angle=.7)
        self.assertEqual(r['status'],'uncertain')
        self.assertEqual(r['angle'],.7)

    def test_reference_does_not_replace_current_manual_angle(self):
        ref=dict(rect=[.02,.03,.98,.97],angle=.6,samples=7)
        r=decast.detect_film_alignment(scene(),current_angle=.4,reference=ref)
        self.assertEqual(r['angle'],.4)
        self.assertEqual(r['angle_status'],'preserved')

    def test_manual_level_is_applied_when_auto_disabled(self):
        r=decast.detect_film_alignment(frame(tilt=.03),current_angle=-1.2,auto_level=False)
        self.assertEqual(r['angle'],-1.2)

    def test_weak_uniform_image_with_bright_frame(self):
        a=np.full((400,600,3),.75,np.float32)
        a[:12]=.95;a[-12:]=.95;a[:,:18]=.95;a[:,-18:]=.95
        r=decast.detect_film_alignment(a)
        self.assertEqual(r['detected_edges'],4)
        np.testing.assert_allclose(r['rect'],[.03,.03,.97,.97],atol=.012)


class ReferenceTests(unittest.TestCase):
    @staticmethod
    def sidecar(folder,name,rect=(.02,.03,.98,.97),angle=.6,rotate=0,flip='none'):
        root=ET.Element('decastAdjustments');p=ET.SubElement(root,'params')
        for k,v in dict(rotate=rotate,flip=flip,level_angle=angle).items():
            ET.SubElement(p,'param',name=k,value=str(v))
        ET.SubElement(root,'crop',**dict(zip(('x0','y0','x1','y1'),map(str,rect))))
        Path(folder,name+'.decast.xml').write_text(ET.tostring(root,encoding='unicode'))

    def test_orientation_round_trip(self):
        rect=[.02,.04,.96,.93]
        for rotate in (0,90,180,270):
            for flip in ('none','h','v'):
                transformed=film_reference.orient_rect(rect,0,'none',rotate,flip)
                back=film_reference.orient_rect(transformed,rotate,flip,0,'none')
                np.testing.assert_allclose(back,rect)

    def test_excludes_self_deduplicates_and_only_reads_same_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(9):
                self.sidecar(folder,f'IMG{i:03d}.ARW')
                self.sidecar(folder,f'IMG{i:03d}.JPG')
            self.sidecar(folder,'IMG005.ARW',rect=(.1,.1,.9,.9),angle=5)
            self.sidecar(folder,'IMG005.JPG',rect=(.1,.1,.9,.9),angle=5)
            ref=film_reference.reference_for(str(Path(folder,'IMG005.ARW')),90,'h')
            self.assertEqual(ref['samples'],8)
            self.assertEqual(ref['angle'],-.6)
            self.assertFalse(any('005' in f for f in ref['files']))
            np.testing.assert_allclose(ref['rect'],[.03,.02,.97,.98])
            self.assertIsNone(film_reference.reference_for(str(Path(folder,'other','IMG005.ARW'))))

    def test_requires_enough_consistent_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(4):self.sidecar(folder,f'IMG{i:03d}.ARW')
            self.assertIsNone(film_reference.reference_for(str(Path(folder,'IMG009.ARW'))))
            for i in range(4,9):self.sidecar(folder,f'IMG{i:03d}.ARW',rect=(.1,.1,.9,.9))
            self.assertIsNone(film_reference.reference_for(str(Path(folder,'IMG004.ARW'))))

    def test_auto_outputs_are_not_reused_as_manual_training(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(6):
                name=f'IMG{i:03d}.ARW'
                self.sidecar(folder,name)
                p=Path(folder,name+'.decast.xml');root=ET.parse(p).getroot()
                ET.SubElement(root,'view',geometry_source='auto')
                p.write_text(ET.tostring(root,encoding='unicode'))
            self.assertIsNone(film_reference.reference_for(str(Path(folder,'IMG009.ARW'))))

    def test_geometry_provenance_round_trips_in_xml(self):
        import gui
        data=dict(P=dict(level_angle=.6),cropN=dict(x0=.02,y0=.03,x1=.98,y1=.97),geometrySource='auto')
        restored=gui._xml_to_data(gui._data_to_xml(data,'test.ARW'))
        self.assertEqual(restored['geometrySource'],'auto')

    def test_malformed_sidecar_does_not_block_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'broken.ARW.decast.xml').write_text('not XML')
            self.assertIsNone(film_reference.reference_for(str(Path(folder,'IMG009.ARW'))))


if __name__=='__main__':unittest.main()

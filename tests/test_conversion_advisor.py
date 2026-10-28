import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import tifffile

import conversion_advisor as advisor
import decast


def negative(power=2, shape=(96, 144)):
    scene = np.linspace(0, 1, np.prod(shape)).reshape(shape) ** power
    return np.repeat(np.power(10., -(.2 + 1.5 * scene))[..., None], 3, axis=-1).astype(np.float32)


def opts(**kwargs):
    return SimpleNamespace(**dict(dict(mode="color", wb="none", gamma=1., contrast=0.,
                                       black_pct=0., white_pct=100.), **kwargs))


class AdvisorTests(unittest.TestCase):
    def test_recovers_known_midpoint_power(self):
        for power in (1., 1.5, 2., 2.5):
            with self.subTest(power=power):
                report = advisor.analyze_frame(negative(power), opts())
                self.assertAlmostEqual(report["recommendation"], power, delta=.012)
                self.assertEqual(report["parameter_key"], "gamma")
                json.dumps(report, allow_nan=False)

    def test_does_not_depend_on_current_gamma_or_finishing(self):
        lin = negative()
        p = dict(gamma=2.5, contrast=.7, exposure=-2, highlights=85,
                 shadows=-20, saturation=1.6, curve=[[0, 0], [.5, .9], [1, 1]])
        before, saved = lin.copy(), copy.deepcopy(p)
        report = advisor.analyze_frame(lin, p)
        self.assertEqual(report, advisor.analyze_frame(lin, {}))
        np.testing.assert_array_equal(lin, before)
        self.assertEqual(p, saved)

    def test_per_frame_advice_accounts_for_finishing_without_changing_it(self):
        lin=negative(1.7)
        p=dict(mode='bw',wb='none',black_pct=0,white_pct=100,exposure=.5,contrast=.12)
        saved=copy.deepcopy(p)
        a=advisor.analyze_frame(lin,dict(p,exposure=0),respect_finishing=True)
        b=advisor.analyze_frame(lin,p,respect_finishing=True)
        self.assertGreater(a['recommendation'],b['recommendation'])
        rendered=decast.convert_negative(lin,SimpleNamespace(**dict(p,gamma=b['recommendation'])))
        self.assertAlmostEqual(advisor._midpoint(rendered),.5,delta=.012)
        self.assertEqual(p,saved)

    def test_flat_invalid_and_tiny_frames_do_not_invent_gamma(self):
        for image in (np.full((32, 32, 3), .4), np.zeros((32, 32, 3)),
                      np.ones((32, 32, 3)), np.full((32, 32, 3), np.nan),
                      np.empty((0, 0, 3)), np.ones((4, 4, 3))):
            result = advisor.analyze_frame(image, {})
            self.assertIsNone(result["recommendation"])
            self.assertEqual(result["confidence"], "none")
            json.dumps(result, allow_nan=False)

    def test_gamma_bound_remains_conservative(self):
        result = advisor.analyze_frame(negative(6), opts())
        self.assertLessEqual(result["recommendation"], 2.8)
        self.assertEqual(result["confidence"], "low")
        self.assertGreater(len(result["warnings"]), 1)

    def test_reference_matching_disables_ineffective_gamma_advice(self):
        report = advisor.analyze_frame(negative(), {"use_match": True})
        self.assertIsNone(report["recommendation"])

    def test_cropped_analysis_ignores_film_border(self):
        core = negative(shape=(80, 120))
        full = np.full((100, 160, 3), .95, dtype=np.float32)
        full[10:90, 20:140] = core
        p = dict(crop_rect=[.125, .1, .875, .9])
        a = advisor.analyze_frame(full, p)
        b = advisor.analyze_frame(core, {})
        self.assertAlmostEqual(a["recommendation"], b["recommendation"], places=3)
        self.assertEqual(a["stats"]["sample_pixels"], 80 * 120)
        p = dict(stats_rect=p["crop_rect"])
        self.assertEqual(a, advisor.analyze_frame(full, p))

    def test_negadoctor_uses_paper_gamma_and_real_pipeline(self):
        lin = negative()
        p = dict(negadoctor=True, wb="none")
        report = advisor.analyze_frame(lin, p)
        self.assertEqual(report["parameter_key"], "nd_gamma")
        self.assertGreaterEqual(report["recommendation"], 1.)
        self.assertLessEqual(report["recommendation"], 6.)
        p.update(nd_gamma=report["recommendation"], contrast=0)
        rendered, _ = decast.convert_base(lin, SimpleNamespace(**p))
        self.assertAlmostEqual(advisor._midpoint(rendered), .5, delta=.01)

    def test_bw_and_positive_use_regular_gamma_despite_saved_nd_flag(self):
        for mode in ("bw", "positive"):
            report = advisor.analyze_frame(negative(), dict(mode=mode, negadoctor=True))
            self.assertEqual(report["parameter_key"], "gamma")

    def test_roll_rejects_minor_outlier_and_uses_one_common_gamma(self):
        reports = []
        for gamma in (1.7, 1.75, 1.8, 1.85, 1.9, 2.8):
            report = advisor._report({})
            report.update(recommendation=gamma, confidence="medium", confidence_score=.7)
            reports.append(report)
        saved = copy.deepcopy(reports)
        result = advisor.analyze_roll(reports)
        self.assertEqual(result["recommendation"], 1.8)
        self.assertEqual(result["accepted_count"], 5)
        self.assertEqual(result["rejected_count"], 1)
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(reports, saved)
        json.dumps(result, allow_nan=False)

    def test_roll_sample_count_and_mixed_modes(self):
        report = advisor.analyze_frame(negative(), {})
        self.assertEqual(advisor.analyze_roll([report])["confidence"], "low")
        self.assertIsNone(advisor.analyze_roll([])["recommendation"])
        other = dict(report, mode="bw")
        self.assertIsNone(advisor.analyze_roll([report, other])["recommendation"])


class PipelineRegressionTests(unittest.TestCase):
    def test_alignment_confidence_excludes_discarded_subject_edge(self):
        edges = dict(top=dict(confidence=.8, slope=0, offset=8, center=99.5, residual=.1),
                     bottom=dict(confidence=.8, slope=0, offset=8, center=99.5, residual=.1),
                     left=dict(confidence=1., slope=.1, offset=8, center=49.5, residual=.1),
                     right=None)
        detected = dict(edges=edges, analysis_shape=[100, 200], rect=[.05, .08, .95, .92],
                        confidence=.867, detected_edges=3, status='partial')
        with patch.object(decast, 'detect_film_frame', return_value=detected):
            result = decast.detect_film_alignment(np.ones((100, 200, 3), dtype=np.float32))
        self.assertIsNone(result['edges']['left'])
        self.assertEqual(result['detected_edges'], 2)
        self.assertEqual(result['confidence'], .8)
        self.assertEqual(result['geometry_confidence'], .4)
        self.assertEqual(result['edge_coverage'], .5)
        self.assertEqual(result['confidence_label'], 'low')
        self.assertTrue(result['warnings'])

    def test_reference_alignment_does_not_claim_measured_confidence(self):
        reference = dict(rect=[.03, .04, .97, .96], angle=.4, samples=6)
        result = decast.detect_film_alignment(np.ones((100, 160, 3), dtype=np.float32) * .4,
                                             reference=reference)
        self.assertEqual(result['status'], 'referenced')
        self.assertEqual(result['angle'], .4)
        self.assertEqual(result['geometry_confidence'], 0)
        self.assertEqual(result['confidence_label'], 'none')
        self.assertGreaterEqual(len(result['warnings']), 2)

    def test_rgb_16bit_tiff_preserves_adjacent_sample_codes(self):
        data = np.array([[[10001, 20002, 30003], [10002, 20003, 30004]],
                         [[65000, 40000, 12345], [65535, 0, 1]]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "negative.tif")
            tifffile.imwrite(path, data, photometric="rgb")
            lin, was_raw = decast.load_image(str(path), SimpleNamespace(input_gamma="linear"))
            np.testing.assert_allclose(lin, data / 65535., rtol=1e-7, atol=1e-8)
            self.assertNotEqual(lin[0, 0, 0], lin[0, 1, 0])
            self.assertFalse(was_raw)

    def test_float_and_planar_tiff(self):
        data = np.linspace(.1, .9, 180, dtype=np.float32).reshape(6, 10, 3)
        with tempfile.TemporaryDirectory() as folder:
            for name, pixels, planar in (("float", data, "contig"),
                                         ("planar", data.transpose(2, 0, 1), "separate")):
                path = Path(folder, name + ".tif")
                tifffile.imwrite(path, pixels, photometric="rgb", planarconfig=planar)
                lin, _ = decast.load_image(str(path), SimpleNamespace(input_gamma="linear"))
                np.testing.assert_array_equal(lin, data)

    def test_palette_and_gray_alpha_png_decode_to_rgb(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ("P", "LA"):
                path = Path(folder, mode + ".png")
                im = Image.new(mode, (8, 8), color=128 if mode == "P" else (128, 255))
                if mode == "P":
                    im.putpalette([v for i in range(256) for v in (i, i, i)])
                im.save(path)
                lin, _ = decast.load_image(str(path), SimpleNamespace(input_gamma="linear"))
                self.assertEqual(lin.shape, (8, 8, 3))
                np.testing.assert_allclose(lin, 128 / 255, rtol=1e-6)

    def test_input_transfer_function_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "negative.png")
            Image.new("RGB", (8, 8), (128, 128, 128)).save(path)
            linear, _ = decast.load_image(str(path), SimpleNamespace(input_gamma="linear"))
            srgb, _ = decast.load_image(str(path), SimpleNamespace(input_gamma="srgb"))
            np.testing.assert_allclose(srgb, decast.srgb_to_linear(linear), rtol=1e-6)
            for gamma in ("0", "-2", "nan", "inf"):
                with self.assertRaises(ValueError):
                    decast.load_image(str(path), SimpleNamespace(input_gamma=gamma))

    def test_film_base_sample_outside_crop_uses_actual_film_base(self):
        lin = np.full((100, 120, 3), [.9, .6, .3], dtype=np.float32)
        core = negative(shape=(80, 96)) * np.array([1., .8, .6], dtype=np.float32)
        lin[10:90, 12:108] = core
        params = opts(crop_rect=[.1, .1, .9, .9], film_base_rect=[0, 0, .08, .08])
        result, _ = decast.convert_base(lin, params)
        density = -np.log10(core)
        black = -np.log10(np.array([.9, .6, .3], dtype=np.float32))
        white = np.max(density, axis=(0, 1))
        expected = np.clip((density - black) / (white - black), 0, 1)
        np.testing.assert_allclose(result, expected, atol=2e-6)

    def test_crop_preview_and_export_match_with_gray_balance_and_nd(self):
        rng = np.random.default_rng(42)
        lin = rng.uniform(.03, .65, (80, 120, 3)).astype(np.float32)
        lin[:8] = [.02, .7, .1]
        lin[-8:] = [.2, .05, .8]
        rect = [.1, .1, .9, .9]
        for nd in (False, True):
            export, _ = decast.convert_base(lin, opts(wb="gray", negadoctor=nd, crop_rect=rect))
            preview, _ = decast.convert_base(lin, opts(wb="gray", negadoctor=nd, stats_rect=rect))
            np.testing.assert_allclose(export, preview[8:72, 12:108], atol=2e-6)

    def test_positive_gamma_not_disabled_by_saved_nd_option(self):
        lin = negative()
        ordinary, _ = decast.convert_base(lin, opts(mode="positive", gamma=2))
        flagged, _ = decast.convert_base(lin, opts(mode="positive", gamma=2, negadoctor=True))
        np.testing.assert_array_equal(ordinary, flagged)

    def test_negadoctor_softclip_is_finite_at_supported_extremes(self):
        lin = np.linspace(0, 1, 600, dtype=np.float32).reshape(10, 20, 3)
        for softclip in (.0001, .75, .9999, 1.):
            for dmax in (.1, 2.046, 6):
                with np.errstate(over="raise", divide="raise", invalid="raise"):
                    result = decast.negadoctor(lin, [.9, .6, .3],
                                               opts(nd_softclip=softclip, nd_dmax=dmax))
                self.assertTrue(np.isfinite(result).all())
                self.assertGreaterEqual(result.min(), 0)
                self.assertLessEqual(result.max(), 1)

    def test_negadoctor_invalid_parameters_fail_clearly(self):
        for kwargs in (dict(nd_dmax=0), dict(nd_gamma=-1), dict(nd_softclip=2),
                       dict(nd_exposure=float("nan"))):
            with self.assertRaises(ValueError):
                decast.negadoctor(negative(), [.9, .6, .3], opts(**kwargs))


if __name__ == "__main__":
    unittest.main()

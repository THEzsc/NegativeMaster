"""Resource budgets must not change decoded pixels or evicted-frame reloads."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'FilmDecastSwift/Support'))
from native_runtime import configure_threads
from native_preview import PreviewCache
from native_detail import load_detail
import numpy as np


class NativeResourceTests(unittest.TestCase):
    def test_sheet_raw_preview_uses_half_decode_but_exports_keep_full_decode(self):
        import decast
        opts = argparse.Namespace(raw_denoise=False, no_camera_wb=True,
                                  no_autorotate=False, preview_max_side=30)
        with patch.object(decast.rawpy, 'imread') as read:
            raw = read.return_value.__enter__.return_value
            raw.sizes.height, raw.sizes.width = 120, 180
            raw.postprocess.return_value = np.full((60, 90, 3), 32768, dtype=np.uint16)
            small, _ = decast.load_image('fixture.ARW', opts)
            self.assertTrue(raw.postprocess.call_args.kwargs['half_size'])
            self.assertEqual(max(small.shape[:2]), 30)
            self.assertEqual(opts._preview_original_side, 180)
            del opts.preview_max_side
            decast.load_image('fixture.ARW', opts)
            self.assertNotIn('half_size', raw.postprocess.call_args.kwargs)

    def test_detail_raw_switches_to_full_decode_at_native_pixel_scale(self):
        opts = argparse.Namespace(raw_denoise=False, no_camera_wb=True,
                                  no_autorotate=False, input_gamma=2.2)
        with patch('native_detail.decast.rawpy.imread') as read:
            raw = read.return_value.__enter__.return_value
            raw.sizes.height, raw.sizes.width, raw.sizes.flip = 5320, 7968, 0
            raw.postprocess.return_value = np.full((40, 60, 3), 32768, dtype=np.uint16)
            small, shape = load_detail('fixture.ARW', opts, 3000)
            self.assertTrue(raw.postprocess.call_args.kwargs['half_size'])
            detail, _ = load_detail('fixture.ARW', opts, 7968)
            self.assertFalse(raw.postprocess.call_args.kwargs['half_size'])
            self.assertFalse(raw.postprocess.call_args.kwargs['use_camera_wb'])
            self.assertEqual(shape, (5320, 7968))
            np.testing.assert_array_equal(detail, small)

    def test_thread_budget_overrides_inherited_pools_and_bounds_override(self):
        for override, expected in ((None, 2), ('bad', 2), ('32', 4), ('0', 1), ('3', 3)):
            env = {'OPENBLAS_NUM_THREADS': '64', 'OMP_NUM_THREADS': '64'}
            if override is not None:
                env['NM_ENGINE_THREADS'] = override
            self.assertEqual(configure_threads(env), expected)
            for name in ('OMP_NUM_THREADS', 'OMP_THREAD_LIMIT', 'OPENBLAS_NUM_THREADS',
                         'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
                self.assertEqual(env[name], str(expected))
            self.assertEqual(env['OMP_WAIT_POLICY'], 'PASSIVE')
            self.assertEqual(env['KMP_BLOCKTIME'], '0')

    def test_byte_budget_lru_and_disk_reload_preserve_pixels(self):
        pixels = np.linspace(0, 1, 1800, dtype=np.float32).reshape(20, 30, 3)
        opts = argparse.Namespace(raw_denoise=False, no_camera_wb=False,
                                  no_autorotate=False, input_gamma=2.2)
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f'{i}.png' for i in range(4)]
            for path in paths:
                path.write_bytes(b'identity only; decoder mocked')
            cache = PreviewCache(Path(folder) / 'cache', limit=4, byte_limit=pixels.nbytes * 2)
            with patch('native_preview.decast.load_image', return_value=(pixels, None)) as decode:
                with patch.object(cache, 'trim', wraps=cache.trim) as trim:
                    cache.load(paths[0], opts)
                    cache.load(paths[1], opts)
                    cache.load(paths[0], opts)  # Refresh LRU.
                    cache.load(paths[2], opts)
                    self.assertNotIn(cache.key(paths[1], opts), cache.memory)
                    self.assertIn(cache.key(paths[0], opts), cache.memory)
                    self.assertEqual(cache.bytes, pixels.nbytes * 2)
                    restored, shape = cache.load(paths[1], opts)
                    np.testing.assert_array_equal(restored, pixels)
                    self.assertEqual(shape, pixels.shape[:2])
                    self.assertEqual(decode.call_count, 3)  # Reload from disk, not decoder.
                    self.assertEqual(trim.call_count, 1)
                oversized = PreviewCache(Path(folder) / 'cache', byte_limit=1)
                np.testing.assert_array_equal(oversized.load(paths[0], opts)[0], pixels)
                self.assertFalse(oversized.memory)
                self.assertEqual(oversized.bytes, 0)

    def test_raw_decode_uses_one_float_buffer_without_changing_precision(self):
        raw_pixels = np.arange(1800, dtype=np.uint16).reshape(20, 30, 3) * 31
        expected = raw_pixels.astype(np.float32) / 65535
        opts = argparse.Namespace(raw_denoise=False, no_camera_wb=False,
                                  no_autorotate=False, input_gamma=2.2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'frame.ARW'
            path.write_bytes(b'raw fixture')
            with patch('native_preview.decast.rawpy.imread') as read:
                raw = read.return_value.__enter__.return_value
                raw.sizes.height, raw.sizes.width, raw.sizes.flip = 20, 30, 0
                raw.postprocess.return_value = raw_pixels
                cache = PreviewCache(Path(folder) / 'cache')
                actual, shape = cache.load(path, opts)
                np.testing.assert_array_equal(actual, expected)
                self.assertEqual(shape, (20, 30))
                raw.postprocess.assert_called_once()
                self.assertTrue(raw.postprocess.call_args.kwargs['half_size'])


if __name__ == '__main__':
    unittest.main()

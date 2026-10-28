"""Bounded linear RAW previews. Never used to produce final exports."""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
import decast

class PreviewCache:
    def __init__(self, directory=None, limit=4):
        self.directory = Path(directory or os.environ.get('NM_PREVIEW_CACHE', Path.home() / 'Library/Caches/NegativeMaster/linear-v1'))
        self.limit = limit
        self.memory = OrderedDict()

    def key(self, path, opts):
        stat = Path(path).stat()
        options = [getattr(opts, k, None) for k in ('raw_denoise','no_camera_wb','no_autorotate','input_gamma')]
        return hashlib.sha256(json.dumps([str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns, options, 1]).encode()).hexdigest()

    def load(self, path, opts):
        key = self.key(path, opts)
        if key in self.memory:
            self.memory.move_to_end(key)
            return self.memory[key]
        cached = self.directory / (key + '.npz')
        value = None
        try:
            with np.load(cached, allow_pickle=False) as f:
                a, shape = f['image'], tuple(int(n) for n in f['shape'])
                if a.dtype == np.float32 and a.ndim == 3 and a.shape[2] == 3 and max(a.shape[:2]) <= 1500:
                    value = (a, shape)
        except (OSError, ValueError, KeyError, EOFError):
            pass
        if value is None:
            if Path(path).suffix.lower() in decast.RAW_EXTS:
                with decast.rawpy.imread(path) as raw:
                    shape = (raw.sizes.height, raw.sizes.width)
                    if not opts.no_autorotate and raw.sizes.flip in (5, 6):
                        shape = shape[::-1]
                    pp = dict(gamma=(1,1), no_auto_bright=True, output_bps=16,
                              use_camera_wb=not opts.no_camera_wb, use_auto_wb=False,
                              output_color=decast.rawpy.ColorSpace.sRGB,
                              user_flip=0 if opts.no_autorotate else -1, half_size=True)
                    if opts.raw_denoise:
                        pp['fbdd_noise_reduction'] = decast.rawpy.FBDDNoiseReductionMode.Full
                    a = raw.postprocess(**pp).astype(np.float32) / 65535
            else:
                a, _ = decast.load_image(path, opts)
                shape = a.shape[:2]
            scale = min(1, 1500 / max(a.shape[:2]))
            if scale < 1:
                size = (round(a.shape[1]*scale), round(a.shape[0]*scale))
                a = np.stack([np.asarray(Image.fromarray(a[...,c]).resize(size, Image.Resampling.BOX)) for c in range(3)], axis=-1)
            value = (a.astype(np.float32), shape)
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.tmp', delete=False) as f:
                    temp = Path(f.name)
                    try:
                        np.savez(f, image=value[0], shape=np.array(shape))
                        os.replace(temp, cached)
                    finally:
                        temp.unlink(missing_ok=True)
                self.trim()
            except OSError:
                pass  # A read-only or full cache must not prevent editing.
        self.memory[key] = value
        while len(self.memory) > self.limit:
            self.memory.popitem(last=False)
        return value

    def trim(self):
        files = sorted(self.directory.glob('*.npz'), key=lambda p: p.stat().st_mtime, reverse=True)
        size = 0
        for f in files:
            size += f.stat().st_size
            if size > 512*1024*1024:
                f.unlink(missing_ok=True)

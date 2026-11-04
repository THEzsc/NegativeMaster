"""On-demand display-resolution rendering, isolated from interactive preview caches."""
from pathlib import Path
import numpy as np
from PIL import Image
import decast


def load_detail(path, opts, side):
    if Path(path).suffix.lower() in decast.RAW_EXTS:
        with decast.rawpy.imread(path) as raw:
            shape = (raw.sizes.height, raw.sizes.width)
            if not opts.no_autorotate and raw.sizes.flip in (5, 6):
                shape = shape[::-1]
            pp = dict(gamma=(1, 1), no_auto_bright=True, output_bps=16,
                      use_camera_wb=not opts.no_camera_wb, use_auto_wb=False,
                      output_color=decast.rawpy.ColorSpace.sRGB,
                      user_flip=0 if opts.no_autorotate else -1,
                      half_size=side <= max(shape) // 2)
            if opts.raw_denoise:
                pp['fbdd_noise_reduction'] = decast.rawpy.FBDDNoiseReductionMode.Full
            rgb = raw.postprocess(**pp)
        scale = min(1, side / max(rgb.shape[:2]))
        if scale < 1:
            size = (round(rgb.shape[1] * scale), round(rgb.shape[0] * scale))
            # Resize one channel at a time before allocating a full RGB float buffer.
            linear = np.stack([np.asarray(Image.fromarray(rgb[..., c].astype(np.float32))
                               .resize(size, Image.Resampling.BOX)) for c in range(3)], axis=-1)
        else:
            linear = rgb.astype(np.float32)
        linear /= 65535
        return linear, shape
    linear, _ = decast.load_image(path, opts)
    shape = linear.shape[:2]
    return decast._resize_long_edge(linear, side), shape


def render_detail(body, gui):
    side = int(body.get('side', 1500))
    if not 1 <= side <= 32768:
        raise ValueError('预览尺寸无效')
    output = Path(body['out'])
    if output.exists() or output.resolve() == Path(body['path']).resolve():
        raise ValueError('预览文件不能覆盖现有文件')
    params = dict(body['params'])
    linear, shape = load_detail(body['path'], gui.make_opts(params), side)
    scale = max(linear.shape[:2]) / max(shape)
    if body.get('negative'):
        oriented = decast.orient_image(linear, int(params.get('rotate', 0) or 0), params.get('flip', 'none'))
        result = np.power(np.clip(oriented, 0, 1), 1 / 2.2)
    else:
        if params.get('denoise'):
            params['denoise'] = max(0, round(float(params['denoise']) * scale))
        if params.get('sharpen_radius'):
            params['sharpen_radius'] = max(1, float(params['sharpen_radius']) * scale)
        opts = gui.make_opts(params)
        # Match the normal preview: use crop for statistics, leave display clipping to Swift.
        opts.crop = 0
        opts.crop_rect = None
        opts.stats_rect = params.get('crop_rect')
        result = decast.convert_negative(linear, opts)
    del linear
    rgb = np.empty(result.shape, dtype=np.uint8)
    for y in range(0, result.shape[0], 128):
        rgb[y:y+128] = (np.clip(result[y:y+128], 0, 1) * 255 + .5).astype(np.uint8)
    del result
    # A file avoids full-resolution base64 copies in the JSON transport and Swift heap.
    # Exclusive creation protects sources and lets the caller clean up cancellation safely.
    with output.open('xb') as stream:
        Image.fromarray(rgb).save(stream, 'JPEG', quality=95, subsampling=0,
                                  icc_profile=decast._srgb_icc_bytes())
    return dict(out=str(output), width=rgb.shape[1], height=rgb.shape[0],
                fullWidth=shape[1], fullHeight=shape[0])

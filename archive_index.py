"""Lightweight archive references and small, disposable RAW previews."""
from pathlib import Path
import io
import json
import re

from PIL import Image, ImageOps

EXPORT_DIRS = {"positive", "positives", "export", "exports", "output", "outputs",
               "成片", "导出", "导出成片", "输出", "正片", "positives_output", "胶卷库成片"}
JPEG_EXTS = {".jpg", ".jpeg"}


def frame_key(path):
    return re.sub(r"_pos$", "", path.stem, flags=re.I).casefold()


def export_directories(parent):
    folders = [parent]
    for child in sorted(parent.iterdir()):
        if child.is_dir() and child.name.casefold() in EXPORT_DIRS:
            folders.append(child)
            # Previous native releases used dated export subfolders.
            if child.name == '胶卷库成片':
                folders.extend(p for p in sorted(child.iterdir()) if p.is_dir() and not p.name.startswith('.'))
    return folders


def resolve_sources(paths, image_exts, raw_exts):
    """Prefer exported JPEGs, never a camera's adjacent RAW+JPEG negative pair."""
    result, seen, listings = [], set(), {}
    for source in paths:
        source = Path(source).resolve()
        if source.suffix.lower() not in image_exts | raw_exts or not source.is_file():
            raise ValueError(f"找不到支持的照片：{source.name}")
        parent = source.parent
        if parent.name.casefold() in EXPORT_DIRS:
            parent = parent.parent
        elif parent.parent.name == '胶卷库成片':
            parent = parent.parent.parent
        if parent not in listings:
            listings[parent] = [(p.resolve(), folder != parent)
                                for folder in export_directories(parent)
                                for p in folder.iterdir() if p.is_file()]
        candidates = [(p, exported) for p, exported in listings[parent] if frame_key(p) == frame_key(source)]
        raw = sorted(p for p, exported in candidates if not exported and p.suffix.lower() in raw_exts)
        # A camera JPEG beside a RAW is a source preview, not a developed positive.
        if raw:
            source = raw[0]
        exported = [p for p, in_export in candidates if p.suffix.lower() in JPEG_EXTS
                    and (in_export or p.stem.lower().endswith('_pos'))]
        exported.sort(key=lambda p: (not p.stem.lower().endswith('_pos'), -p.stat().st_mtime_ns, str(p)))
        target = exported[0] if exported else source
        if str(target) not in seen:
            seen.add(str(target))
            result.append(dict(source=str(source), path=str(target), raw=target.suffix.lower() in raw_exts))
    return result


def raw_preview(path, make_opts=None, read_xml=None, settings_file=None):
    """Decode at half size, develop at 960 px. No full-size export or linear disk cache."""
    import rawpy
    data = None
    xml = Path(str(path) + '.decast.xml')
    saved = Path(settings_file(str(path))) if settings_file else None
    if xml.is_file() and read_xml:
        data = read_xml(xml.read_text())
    elif saved and saved.is_file():
        data = json.loads(saved.read_text())
    with rawpy.imread(str(path)) as raw:
        if data and data.get('P') and make_opts:
            import decast
            import numpy as np
            params = dict(data['P'], negative_preview=False, use_match=False)
            if data.get('cropN'):
                params['crop_rect'] = [float(data['cropN'][k]) for k in ('x0', 'y0', 'x1', 'y1')]
            opts = make_opts(params)
            opts._ref_centers = None; opts._ref_cdfs = None; opts.stats_rect = None
            rgb = raw.postprocess(half_size=True, gamma=(1, 1), no_auto_bright=True,
                                  output_bps=16, use_camera_wb=not opts.no_camera_wb,
                                  use_auto_wb=False, output_color=rawpy.ColorSpace.sRGB,
                                  user_flip=0 if opts.no_autorotate else -1)
            linear = rgb.astype(np.float32) / 65535
            scale = min(1, 960 / max(linear.shape[:2]))
            if scale < 1:
                size = (round(linear.shape[1]*scale), round(linear.shape[0]*scale))
                linear = np.stack([np.asarray(Image.fromarray(linear[...,c]).resize(size, Image.Resampling.BOX)) for c in range(3)], axis=-1)
            opts.denoise = 0  # A browsing preview does not need costly detail processing.
            opts.sharpen_radius = max(1, opts.sharpen_radius * scale)
            output = decast.convert_negative(linear, opts)
            return Image.fromarray((np.clip(output, 0, 1)*255+.5).astype('uint8'))
        try:
            thumb = raw.extract_thumb()
            image = Image.open(io.BytesIO(thumb.data)) if thumb.format == rawpy.ThumbFormat.JPEG else Image.fromarray(thumb.data)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((960, 960), Image.Resampling.LANCZOS)
            return image.copy()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            return Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))

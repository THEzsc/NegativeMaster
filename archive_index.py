"""Lightweight archive references and small, disposable RAW previews."""
from pathlib import Path
import io
import json
import re
import hashlib
import os
import tempfile

from PIL import Image, ImageOps

EXPORT_DIRS = {"positive", "positives", "export", "exports", "output", "outputs",
               "成片", "导出", "导出成片", "输出", "正片", "positives_output", "胶卷库成片"}
JPEG_EXTS = {".jpg", ".jpeg"}


def frame_key(path):
    return re.sub(r"_pos(?:-\d+)?$", "", path.stem, flags=re.I).casefold()


def is_export(path):
    return bool(re.search(r"_pos(?:-\d+)?$", path.stem, re.I))


def fingerprint(path):
    stat = Path(path).stat()
    return [stat.st_size, stat.st_mtime_ns]


def write_export_log(entries, directory, settings_file=None):
    """One human-readable source/JPEG manifest per completed or stopped batch."""
    import uuid
    from datetime import datetime, timezone
    folder = Path(directory).resolve()
    if not folder.is_dir() or not isinstance(entries, list) or not entries:
        raise ValueError('缺少导出目录或已完成的 JPEG')
    items = []
    for entry in entries:
        source, output = Path(entry['source']).resolve(), Path(entry['path']).resolve()
        if output.suffix.lower() not in JPEG_EXTS or output.parent != folder or source == output:
            raise ValueError('索引日志只能关联该目录中已导出的 JPEG')
        with Image.open(output) as image:
            if image.format != 'JPEG':
                raise ValueError('导出文件不是 JPEG')
            image.verify()
        items.append(dict(source=str(source), path=str(output),
                          source_stat=fingerprint(source), output_stat=fingerprint(output)))
    target = folder / ('导出索引-' + uuid.uuid4().hex[:12] + '.json')
    data = dict(version=1, created_at=datetime.now(timezone.utc).isoformat(), items=items)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    if settings_file:
        # Remember only the log location so custom output folders remain discoverable.
        pointers = Path(settings_file(items[0]['source'])).parent / 'export-logs'
        pointers.mkdir(parents=True, exist_ok=True)
        pointer = pointers / (hashlib.sha256(str(target).encode()).hexdigest() + '.json')
        pointer.write_text(json.dumps(dict(log=str(target)), ensure_ascii=False))
    return target


def logged_exports(paths, settings_file=None):
    logs = set()
    folders = set()
    for path in paths:
        parent = Path(path).resolve().parent
        if parent.name.casefold() in EXPORT_DIRS | {'raw', 'tif', 'tiff'}:
            parent = parent.parent
        folders.add(parent)
    for parent in folders:
        for folder in export_directories(parent):
            logs.update(folder.glob('导出索引-*.json'))
    if paths and settings_file:
        pointers = Path(settings_file(str(paths[0]))).parent / 'export-logs'
        for pointer in pointers.glob('*.json'):
            try:
                logs.add(Path(json.loads(pointer.read_text())['log']))
            except (OSError, ValueError, KeyError, TypeError):
                pass
    result = {}
    for log in sorted((p for p in logs if p.is_file()), key=lambda p: p.stat().st_mtime_ns):
        try:
            if log.stat().st_size > 2 * 1024 * 1024:
                continue
            data = json.loads(log.read_text())
            if data.get('version') != 1:
                continue
            for item in data['items']:
                try:
                    source, output = Path(item['source']).resolve(), Path(item['path']).resolve()
                    if (output.suffix.lower() in JPEG_EXTS and item['source_stat'] == fingerprint(source)
                            and item['output_stat'] == fingerprint(output)):
                        result[str(source)] = output
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return result


def cached_jpeg(path, signature, settings_file, render, max_side=2560):
    """Disposable rendered JPEG, invalidated by source bytes metadata and saved settings."""
    if not settings_file:
        return render()
    folder = Path(settings_file(str(path))).parent / 'preview-jpeg'
    key = hashlib.sha256(json.dumps([str(Path(path).resolve()), fingerprint(path),
        signature, max_side, 1], sort_keys=True).encode()).hexdigest()
    cached = folder / (key + '.jpg')
    try:
        with Image.open(cached) as image:
            result = image.copy()
        os.utime(cached, None)
        return result
    except (OSError, ValueError):
        pass
    image = render()
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    temp = None
    try:
        import decast
        folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=folder, suffix='.tmp')
        os.close(fd); temp = Path(name)
        image.convert('RGB').save(temp, 'JPEG', quality=88, icc_profile=decast._srgb_icc_bytes())
        os.replace(temp, cached)
        # Bound disk use; this runs only when a new preview is written.
        total = 0
        for file in sorted(folder.glob('*.jpg'), key=lambda p: p.stat().st_mtime_ns, reverse=True):
            total += file.stat().st_size
            if total > 256 * 1024 * 1024:
                file.unlink(missing_ok=True)
    except OSError:
        pass
    finally:
        if temp:
            temp.unlink(missing_ok=True)
    return image


def export_directories(parent):
    folders = [parent]
    for child in sorted(parent.iterdir()):
        if child.is_dir() and child.name.casefold() in EXPORT_DIRS:
            folders.append(child)
            # Previous native releases used dated export subfolders.
            if child.name == '胶卷库成片':
                folders.extend(p for p in sorted(child.iterdir()) if p.is_dir() and not p.name.startswith('.'))
    return folders


def resolve_sources(paths, image_exts, raw_exts, settings_file=None):
    """Prefer exported JPEGs, never a camera's adjacent RAW+JPEG negative pair."""
    result, seen, listings = [], set(), {}
    logged = logged_exports(paths, settings_file)
    for source in paths:
        source = Path(source).resolve()
        if source.suffix.lower() not in image_exts | raw_exts or not source.is_file():
            raise ValueError(f"找不到支持的照片：{source.name}")
        parent = source.parent
        if parent.name.casefold() in EXPORT_DIRS | {'raw', 'tif', 'tiff'}:
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
        if raw and source.suffix.lower() in JPEG_EXTS:
            source = raw[0]
        exported = [p for p, in_export in candidates if p.suffix.lower() in JPEG_EXTS
                    and (in_export or is_export(p))]
        exported.sort(key=lambda p: (-p.stat().st_mtime_ns, str(p)))
        recorded = logged.get(str(source))
        if recorded:
            exported.insert(0, recorded)
        target = source
        for candidate in exported:
            try:
                with Image.open(candidate) as image:
                    if image.format != 'JPEG':
                        continue
                    image.verify()
                target = candidate
                break
            except (OSError, ValueError):
                continue
        if str(target) not in seen:
            seen.add(str(target))
            result.append(dict(source=str(source), path=str(target), raw=target.suffix.lower() in raw_exts))
    return result


def saved_data(path, read_xml=None, settings_file=None):
    xml = Path(str(path) + '.decast.xml')
    saved = Path(settings_file(str(path))) if settings_file else None
    if xml.is_file() and read_xml:
        return read_xml(xml.read_text())
    if saved and saved.is_file():
        return json.loads(saved.read_text())
    return None


def image_preview(path, make_opts=None, read_xml=None, settings_file=None):
    """TIFF/JPEG negatives use their saved adjustment; no full-size positive export."""
    data = saved_data(path, read_xml, settings_file)
    def render():
        if data and data.get('P') and make_opts:
            import decast
            import numpy as np
            params = dict(data['P'], negative_preview=False, use_match=False)
            if data.get('cropN'):
                params['crop_rect'] = [float(data['cropN'][k]) for k in ('x0', 'y0', 'x1', 'y1')]
            opts = make_opts(params)
            opts._ref_centers = None; opts._ref_cdfs = None; opts.stats_rect = None
            opts.preview_max_side = 960
            linear, _ = decast.load_image(str(path), opts)
            linear = decast._resize_long_edge(linear, 960)
            opts.denoise = 0
            opts.sharpen_radius = max(1, getattr(opts, 'sharpen_radius', 0) *
                min(1, 960 / getattr(opts, '_preview_original_side', 960)))
            output = decast.convert_negative(linear, opts)
            return Image.fromarray((np.clip(output, 0, 1)*255+.5).astype('uint8'))
        with Image.open(path) as opened:
            opened.draft('RGB', (960, 960))
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((960, 960), Image.Resampling.LANCZOS)
            return image.convert('RGB')
    return cached_jpeg(path, data, settings_file, render, 960)


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

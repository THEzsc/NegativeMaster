"""Browser adapters for the same bounded previews and selective edits as Swift."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit
from flask import Blueprint, jsonify, request, send_file
from PIL import Image, ImageOps
import numpy as np
import archive_index
import conversion_advisor
import decast
import film_reference

SUPPORT = Path(__file__).parent / 'FilmDecastSwift' / 'Support'
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
from native_preview import PreviewCache
from native_batch import snapshot, apply, restore
from native_sync import catalog, patch_for
from native_film import fresh_params, emulsion_patch
from native_detail import render_detail


def create_workbench_blueprint(gui):
    bp = Blueprint('web_workbench', __name__)
    previews = PreviewCache(directory=Path(gui.SETTINGS_DIR) / 'linear-preview')
    preview_lock = threading.Lock()
    detail_lock = threading.Lock()
    thumbnail_lock = threading.Lock()

    def adjustments(path):
        for name, xml in ((gui.sidecar_path(path), True), (gui.settings_file(path), False)):
            if Path(name).is_file():
                text = Path(name).read_text(encoding='utf-8')
                data = gui._xml_to_data(text) if xml else json.loads(text)
                p = dict(gui.DEFAULTS, **data.get('P', {}))
                if data.get('cropN'):
                    p['crop_rect'] = [data['cropN'][k] for k in ('x0','y0','x1','y1')]
                p['geometry_source'] = data.get('geometrySource', 'manual')
                return dict(params=p, data=data)
        return dict(params=fresh_params(gui.DEFAULTS), data={})

    @bp.before_request
    def local_request():
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(ok=False, err='不接受跨站请求'), 403
        if request.method == 'POST' and not request.is_json:
            return jsonify(ok=False, err='需要 JSON 请求'), 415

    @bp.errorhandler(Exception)
    def error(exc):
        return jsonify(ok=False, err=str(exc)), 400

    @bp.get('/api/workbench/catalog')
    def options():
        return jsonify(ok=True, groups=catalog(), rawExtensions=sorted(decast.RAW_EXTS))

    @bp.post('/api/workbench/snapshot')
    def read():
        path = request.json['path']
        with gui._IMAGE_LOCK:
            token = snapshot(gui, path)[2]
            result = adjustments(path)
            if snapshot(gui, path)[2] != token:
                raise ValueError('照片参数已变化，请重试')
        return jsonify(ok=True, token=token, **result)

    @bp.post('/api/workbench/apply')
    def write():
        b = request.json
        with gui._IMAGE_LOCK:
            kind = b.get('kind', 'batch')
            flags = {}
            if kind == 'sync':
                patch = patch_for(b.get('groups'), b.get('source'), gui.DEFAULTS)
                flags['sync'] = True
            elif kind == 'film':
                flags['film'] = True
                if 'emulsion' in b:
                    patch = emulsion_patch(adjustments(b['path'])['params'], b['emulsion'])
                    flags = dict(emulsion=True)
                elif b.get('preset'):
                    if gui.bad_preset_name(b['preset']):
                        raise ValueError('预设名称无效')
                    patch = decast.load_preset(b['preset'])
                else:
                    patch = {'mode': b.get('mode')}
            elif kind == 'batch':
                patch = b['patch']
            else:
                raise ValueError('操作类型无效')
            result = apply(gui, Path(gui.SETTINGS_DIR).parent, b['path'], patch,
                           b['token'], adjustments, **flags)
        return jsonify(result)

    @bp.post('/api/workbench/undo')
    def undo():
        with gui._IMAGE_LOCK:
            return jsonify(restore(gui, Path(gui.SETTINGS_DIR).parent,
                                   request.json['undo_id'], adjustments))

    @bp.post('/api/workbench/analyze')
    def analyze():
        b = request.json
        p = b['params']
        with preview_lock:
            previews.directory = Path(gui.SETTINGS_DIR) / 'linear-preview'
            image, shape = previews.load(b['path'], gui.make_opts(p))
            scale = max(image.shape[:2]) / max(shape)
            params = dict(vars(gui.make_opts(p)))
            if params.get('base_rect'):
                params['base_rect'] = [v * scale for v in params['base_rect']]
            if b.get('kind') == 'crop':
                oriented = decast.orient_image(image, int(p.get('rotate', 0)), p.get('flip', 'none'))
                ref = film_reference.reference_for(b['path'], int(p.get('rotate', 0)), p.get('flip', 'none')) if b.get('reference', True) else None
                report = decast.detect_film_alignment(oriented, current_angle=p.get('level_angle', 0), auto_level=True, reference=ref)
            else:
                report = conversion_advisor.analyze_frame(image, params, respect_finishing=True)
        return jsonify(ok=True, report=report)

    @bp.post('/api/workbench/detail')
    def detail():
        # Keep only one expensive detail decode in flight, separate from interactive CACHE.
        if not detail_lock.acquire(blocking=False):
            return jsonify(ok=False, err='高清预览忙，请稍后重试'), 429
        try:
            b = dict(request.json)
            with tempfile.TemporaryDirectory(prefix='nm-detail-') as folder:
                b['out'] = str(Path(folder) / 'preview.jpg')
                b['side'] = min(8192, max(1500, int(b.get('side', 1500))))
                render_detail(b, gui)
                data = Path(b['out']).read_bytes()
            return send_file(io.BytesIO(data), mimetype='image/jpeg')
        finally:
            detail_lock.release()

    @bp.get('/api/workbench/thumb')
    def thumbnail():
        path = Path(request.args['path'])
        if path.suffix.lower() not in decast.RAW_EXTS | decast.IMG_EXTS:
            raise ValueError('不支持此照片类型')
        def generate():
            if path.suffix.lower() in decast.RAW_EXTS:
                with decast.rawpy.imread(str(path)) as raw:
                    try:
                        thumb = raw.extract_thumb()
                        im = Image.open(io.BytesIO(thumb.data)) if isinstance(thumb.data, bytes) else Image.fromarray(thumb.data)
                        return ImageOps.exif_transpose(im).convert('RGB')
                    except (decast.rawpy.LibRawNoThumbnailError, decast.rawpy.LibRawUnsupportedThumbnailError):
                        return Image.fromarray(raw.postprocess(half_size=True, output_bps=8))
            with Image.open(path) as im:
                im.draft('RGB', (200, 200))
                return ImageOps.exif_transpose(im).convert('RGB')
        with thumbnail_lock:
            image = archive_index.cached_jpeg(str(path), {'thumbnail': 1}, gui.settings_file, generate, 200)
        out = io.BytesIO(); image.save(out, 'JPEG', quality=80); out.seek(0)
        return send_file(out, mimetype='image/jpeg', max_age=3600)

    @bp.post('/api/workbench/export-log')
    def export_log():
        b = request.json
        return jsonify(ok=True, log=str(archive_index.write_export_log(b['items'], b['directory'], gui.settings_file)))

    return bp

"""Selective batch edits with optimistic concurrency and durable undo receipts."""
import copy
import hashlib
import json
import math
from pathlib import Path
import uuid

from workflow_app import atomic_text


def snapshot(gui, path):
    files = [Path(gui.sidecar_path(path)), Path(gui.settings_file(path))]
    texts = [p.read_text(encoding='utf-8') if p.exists() else None for p in files]
    token = hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()
    return files, texts, token


def validate_patch(patch):
    if not isinstance(patch, dict) or not patch:
        raise ValueError('缺少批量调整参数')
    if set(patch) not in ({'gamma'}, {'nd_gamma'}, {'crop_rect', 'level_angle', 'geometry_source'}):
        raise ValueError('批量处理只能更改 Gamma 或裁剪与校平')
    for key in ('gamma', 'nd_gamma', 'level_angle'):
        if key in patch:
            value = patch[key]
            lo, hi = {'gamma': (.6, 3), 'nd_gamma': (1, 8), 'level_angle': (-15, 15)}[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError('批量调整数值无效')
    if 'crop_rect' in patch:
        r = patch['crop_rect']
        if not isinstance(r, list) or len(r) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in r) or r[2] <= r[0] or r[3] <= r[1] or patch['geometry_source'] != 'auto':
            raise ValueError('裁剪范围无效')


def apply(gui, root, path, patch, expected, read_adjustments):
    validate_patch(patch)
    if not Path(path).is_file():
        raise ValueError('原照片不存在')
    files, before, token = snapshot(gui, path)
    if token != expected:
        raise ValueError('分析后照片参数已改变，请重新分析')
    current = read_adjustments(path)
    p = current['params']
    if 'gamma' in patch or 'nd_gamma' in patch:
        nd = p.get('mode') == 'color' and p.get('negadoctor', False)
        if p.get('use_match') or p.get('mode') == 'positive' or nd != ('nd_gamma' in patch):
            raise ValueError('当前反转引擎与 Gamma 建议不一致')
    data = copy.deepcopy(current['data']) or dict(P=copy.deepcopy(p), curFmt='free', orient='land')
    data.setdefault('P', {}).update(patch)
    if 'crop_rect' in patch:
        data['cropN'] = dict(zip(('x0', 'y0', 'x1', 'y1'), patch['crop_rect']))
        data['geometrySource'] = 'auto'
    # Record recovery data before replacing any sidecar. XML remains authoritative.
    journal = Path(root) / 'batch_history'
    journal.mkdir(parents=True, exist_ok=True)
    identifier = uuid.uuid4().hex
    receipt = dict(path=path, before=before, after=None)
    receipt_path = journal / (identifier + '.json')
    atomic_text(receipt_path, json.dumps(receipt, ensure_ascii=False))
    atomic_text(files[0], gui._data_to_xml(data, path))
    warnings = []
    try:
        atomic_text(files[1], json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as exc:
        warnings.append('XML 已保存，内部缓存未同步：' + str(exc))
    receipt['after'] = snapshot(gui, path)[2]
    atomic_text(receipt_path, json.dumps(receipt, ensure_ascii=False))
    return dict(ok=True, undo_id=identifier, params=read_adjustments(path)['params'], warnings=warnings)


def restore(gui, root, identifier, read_adjustments):
    if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('撤销记录无效')
    receipt_path = Path(root) / 'batch_history' / (identifier + '.json')
    receipt = json.loads(receipt_path.read_text())
    path = receipt['path']
    files, _, token = snapshot(gui, path)
    if not receipt.get('after') or receipt['after'] != token:
        raise ValueError('批量处理后照片参数已改变，未覆盖后续调整')
    for file, text in zip(files, receipt['before']):
        if text is None:
            file.unlink(missing_ok=True)
        else:
            atomic_text(file, text)
    return dict(ok=True, path=path, params=read_adjustments(path)['params'])

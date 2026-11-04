"""Explicit sync groups. Never copy the active photo's complete parameter dictionary."""
import copy

GROUPS = [
    ('film', '胶片类型', ['mode']),
    ('inversion', '反转设置', ['negadoctor', 'nd_dmax', 'nd_offset', 'nd_black', 'nd_softclip', 'nd_exposure']),
    ('gamma', 'Gamma', ['gamma', 'nd_gamma']),
    ('exposure', '曝光', ['exposure']),
    ('levels', '黑白场', ['black_pct', 'white_pct']),
    ('whiteBalance', '白平衡', ['wb', 'temp', 'tint']),
    ('tone', '影调', ['contrast', 'highlights', 'shadows', 'whites', 'blacks']),
    ('color', '色彩', ['saturation', 'vibrance']),
    ('curves', '曲线', ['curve', 'curve_r', 'curve_g', 'curve_b']),
    ('hsl', 'HSL', ['hsl']),
    ('detail', '锐化与降噪', ['sharpen', 'sharpen_radius', 'denoise', 'raw_denoise']),
    ('effects', '暗角', ['vignette']),
    ('crop', '裁剪与校平', ['crop_rect', 'level_angle', 'geometry_source']),
    ('orientation', '旋转与翻转', ['rotate', 'flip', 'emulsion_mirrored']),
    ('samples', '取样区域', ['wb_rect', 'wb_point', 'film_base_rect', 'shadow_rect', 'highlight_rect', 'base_rect']),
    ('reference', '参照匹配', ['use_match', 'reference_path']),
    ('input', '输入设置', ['no_camera_wb', 'no_autorotate', 'input_gamma']),
]
DEFAULT_GROUPS = {'whiteBalance', 'tone', 'color', 'curves', 'hsl'}


def catalog():
    return [dict(id=key, title=title, selected=key in DEFAULT_GROUPS) for key, title, _ in GROUPS]


def patch_for(groups, source, defaults):
    from native_film import is_emulsion_mirrored
    known = {key for key, _, _ in GROUPS}
    if not isinstance(groups, list) or not groups or any(not isinstance(g, str) or g not in known for g in groups):
        raise ValueError('请选择有效的同步项目')
    if not isinstance(source, dict):
        raise ValueError('缺少源照片调整')
    baseline = dict(defaults, geometry_source='manual', use_match=False, reference_path=None)
    patch = {}
    for key, _, fields in GROUPS:
        if key in groups:
            for field in fields:
                patch[field] = (is_emulsion_mirrored(source) if field == 'emulsion_mirrored'
                                else copy.deepcopy(source.get(field, baseline.get(field))))
    return patch


def validate(patch):
    known = {field for _, _, fields in GROUPS for field in fields}
    if not isinstance(patch, dict) or not patch or not set(patch).issubset(known):
        raise ValueError('同步项目包含不支持的参数')
    if 'crop_rect' in patch and patch['crop_rect'] is not None:
        import math
        r = patch['crop_rect']
        if not isinstance(r, list) or len(r) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in r) or r[0] >= r[2] or r[1] >= r[3]:
            raise ValueError('裁剪范围无效')
    if 'mode' in patch and patch['mode'] not in ('color', 'bw', 'positive'):
        raise ValueError('胶片类型无效')
    if 'emulsion_mirrored' in patch and not isinstance(patch['emulsion_mirrored'], bool):
        raise ValueError('药膜面翻拍设置无效')

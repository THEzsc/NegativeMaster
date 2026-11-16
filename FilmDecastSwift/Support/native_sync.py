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


FIELD_TITLES = dict(mode='胶片类型', gamma='Gamma', nd_gamma='纸张反差', exposure='曝光',
    wb='白平衡方式', temp='色温', tint='色调', contrast='对比度', highlights='高光', shadows='阴影', whites='白色', blacks='黑色',
    saturation='饱和度', vibrance='鲜艳度', curve='RGB 曲线', curve_r='红曲线', curve_g='绿曲线', curve_b='蓝曲线',
    sharpen='锐化', sharpen_radius='锐化半径', denoise='色度降噪', raw_denoise='RAW 降噪', vignette='晕影',
    crop_rect='裁剪框', level_angle='校平角度', rotate='旋转方向', flip='镜像', emulsion_mirrored='药膜面校正',
    wb_rect='白平衡取样框', wb_point='白平衡取样点', film_base_rect='片基取样', shadow_rect='暗部取样', highlight_rect='亮部取样', base_rect='片基区域',
    negadoctor='Negadoctor', nd_dmax='最大密度', nd_offset='密度偏移', nd_black='黑位', nd_softclip='高光柔和度', nd_exposure='印相曝光',
    black_pct='黑点百分位', white_pct='白点百分位', use_match='参照匹配开关', reference_path='参照图片',
    no_camera_wb='关闭相机白平衡', no_autorotate='关闭 EXIF 旋转', input_gamma='输入编码')
BANDS = [('red','红'),('orange','橙'),('yellow','黄'),('green','绿'),('aqua','青'),('blue','蓝'),('purple','紫'),('magenta','品红')]


def catalog():
    result = []
    for key, title, fields in GROUPS:
        items = ([dict(id=f'hsl.{band}.{channel}', title=f'{name} · {label}')
                  for band,name in BANDS for channel,label in [('h','色相'),('s','饱和度'),('l','明亮度')]]
                 if key == 'hsl' else [dict(id=f, title=FIELD_TITLES.get(f,f)) for f in fields if f != 'geometry_source'])
        result.append(dict(id=key, title=title, selected=key in DEFAULT_GROUPS, fields=items))
    order = ['whiteBalance','exposure','tone','color','curves','hsl','detail','effects','film','inversion','gamma','levels','crop','orientation','samples','reference','input']
    return sorted(result, key=lambda g: order.index(g['id']))


def fields_patch(fields, source, current, defaults):
    from native_film import is_emulsion_mirrored, emulsion_patch
    if not isinstance(source, dict):
        raise ValueError('缺少源照片调整')
    known = {f['id'] for group in catalog() for f in group['fields']}
    if not isinstance(fields,list) or not fields or any(f not in known for f in fields):
        raise ValueError('请选择有效的同步项目')
    result = emulsion_patch(current, is_emulsion_mirrored(source)) if 'emulsion_mirrored' in fields and not {'rotate','flip'}.intersection(fields) else {}
    for field in fields:
        if field.startswith('hsl.'):
            _, band, channel = field.split('.')
            hsl = result.setdefault('hsl', copy.deepcopy(current.get('hsl') or {}))
            hsl.setdefault(band, {})[channel] = copy.deepcopy((source.get('hsl') or {}).get(band,{}).get(channel,0))
        else:
            result[field] = is_emulsion_mirrored(source) if field == 'emulsion_mirrored' else copy.deepcopy(source.get(field, defaults.get(field)))
    if 'crop_rect' in result or 'level_angle' in result:
        result['geometry_source'] = source.get('geometry_source','manual')
    validate(result)
    return result


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


def orientation_patch(params, operation):
    """Apply a display-space operation to each frame's own crop and sample regions."""
    from native_film import REGIONS, emulsion_patch
    if isinstance(operation, bool):
        return emulsion_patch(params, operation)
    if operation not in ('cw', 'ccw', 'h', 'v'):
        raise ValueError('旋转操作无效')
    p = copy.deepcopy(params)
    mirrored = p.get('flip') in ('h','v')
    rotation = int(p.get('rotate',0) or 0)
    if operation in ('cw','ccw'):
        rotation += (90 if operation == 'cw' else -90) * (-1 if mirrored else 1)
    else:
        old = p.get('flip','none')
        p['flip'] = 'none' if old == operation or mirrored else operation
        if mirrored and old != operation:
            rotation += 180
        p['level_angle'] = -float(p.get('level_angle',0) or 0)
    p['rotate'] = rotation % 360
    p['geometry_source'] = 'manual'
    def point(x,y):
        return {'cw':(1-y,x),'ccw':(y,1-x),'h':(1-x,y),'v':(x,1-y)}[operation]
    for key in REGIONS:
        value = p.get(key)
        if value is None:
            continue
        coords = [value[k] for k in ('x0','y0','x1','y1')] if isinstance(value,dict) else value
        a,b = point(*coords[:2]),point(*coords[2:])
        rect = [min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])]
        p[key] = dict(zip(('x0','y0','x1','y1'),rect)) if isinstance(value,dict) else rect
    if p.get('wb_point') is not None:
        p['wb_point'] = list(point(*p['wb_point']))
    return {k:v for k,v in p.items() if v != params.get(k) or k == 'geometry_source'}

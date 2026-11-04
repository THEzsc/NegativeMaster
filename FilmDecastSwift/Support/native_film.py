"""Native film import defaults and idempotent emulsion-side orientation correction."""
import copy

REGIONS = ('crop_rect', 'wb_rect', 'film_base_rect', 'shadow_rect', 'highlight_rect')
EMULSION_KEYS = set(REGIONS) | {'wb_point', 'rotate', 'flip', 'level_angle',
                                'geometry_source', 'emulsion_mirrored'}


def is_emulsion_mirrored(params):
    value = params.get('emulsion_mirrored')
    # Old saved edits have no marker: preserve an existing reflection rather than doubling it.
    return value if isinstance(value, bool) else params.get('flip') in ('h', 'v')


def fresh_params(defaults):
    result = copy.deepcopy(defaults)
    result.update(flip='h', emulsion_mirrored=True)
    return result


def emulsion_patch(params, enabled):
    if not isinstance(enabled, bool):
        raise ValueError('药膜面翻拍设置无效')
    patch = {'emulsion_mirrored': enabled}
    if is_emulsion_mirrored(params) == enabled:
        return patch
    rotation = int(params.get('rotate', 0) or 0)
    # Correct the captured film, before the user's orientation: a quarter turn exchanges axes.
    axis = 'v' if rotation % 180 else 'h'
    current = params.get('flip', 'none')
    patch['flip'] = 'none' if current == axis else axis
    if current in ('h', 'v') and current != axis:
        patch.update(flip='none', rotate=(rotation + 180) % 360)
    patch['level_angle'] = -float(params.get('level_angle', 0) or 0)
    patch['geometry_source'] = 'manual'

    def point(x, y):
        return (1-x, y) if axis == 'h' else (x, 1-y)

    for key in REGIONS:
        value = params.get(key)
        if value is None:
            continue
        values = [value[k] for k in ('x0', 'y0', 'x1', 'y1')] if isinstance(value, dict) else value
        a, b = point(*values[:2]), point(*values[2:])
        rect = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
        patch[key] = dict(value, **dict(zip(('x0', 'y0', 'x1', 'y1'), rect))) if isinstance(value, dict) else rect
    if params.get('wb_point') is not None:
        patch['wb_point'] = list(point(*params['wb_point']))
    return patch

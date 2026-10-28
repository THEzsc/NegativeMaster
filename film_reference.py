"""Read-only, leave-one-out geometry references from nearby edited film frames."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np


def orient_rect(rect, old_rotate, old_flip, rotate, flip):
    x0, y0, x1, y1 = rect
    pts = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float)
    if old_flip in ('h', 'v'):
        axis = 0 if old_flip == 'h' else 1
        pts[:, axis] = 1 - pts[:, axis]
    for _ in range((old_rotate // 90) % 4):
        pts = np.column_stack([pts[:, 1], 1 - pts[:, 0]])
    for _ in range((rotate // 90) % 4):
        pts = np.column_stack([1 - pts[:, 1], pts[:, 0]])
    if flip in ('h', 'v'):
        axis = 0 if flip == 'h' else 1
        pts[:, axis] = 1 - pts[:, axis]
    return [*pts.min(axis=0), *pts.max(axis=0)]


def reference_for(path, rotate=0, flip='none'):
    """Never use the target's own settings or infer a reference across folders.

    Require five nearby, consistently framed edits. Duplicated RAW/JPEG sidecars
    count once. Creative tight crops and inconsistent sessions are excluded.
    """
    if not path:
        return None
    target = Path(path)
    by_stem = {}
    for sidecar in sorted(target.parent.glob('*.decast.xml')):
        source = Path(str(sidecar)[:-len('.decast.xml')])
        if source.stem == target.stem or source.stem in by_stem:
            continue
        try:
            if sidecar.stat().st_size > 65536:
                continue
            root = ET.fromstring(sidecar.read_text())
            view = root.find('view')
            if view is not None and view.get('geometry_source') == 'auto':
                continue
            params = {p.get('name'): p.get('value') for p in root.findall('./params/param')}
            crop = root.find('crop')
            rect = [float(crop.get(k)) for k in ('x0', 'y0', 'x1', 'y1')]
            old_rot = int(params.get('rotate', 0))
            old_flip = params.get('flip', 'none')
            angle = float(params.get('level_angle', 0))
            if old_rot % 90 or not np.isfinite(rect + [angle]).all() or abs(angle) > 8:
                continue
            if old_flip not in ('none', 'h', 'v'):
                continue
            if min(rect) < 0 or max(rect) > 1:
                continue
            rect = orient_rect(rect, old_rot, old_flip, rotate, flip)
            width, height = rect[2] - rect[0], rect[3] - rect[1]
            if min(width, height) < .76 or not .88 < width / height < 1.12:
                continue
            if (old_flip != 'none') != (flip != 'none'):
                angle = -angle
            by_stem[source.stem] = dict(rect=rect, angle=angle, file=source.name)
        except (OSError, ET.ParseError, TypeError, ValueError, AttributeError):
            continue
    if len(by_stem) < 5:
        return None
    ordered = sorted([*by_stem, target.stem])
    index = ordered.index(target.stem)
    names = sorted(by_stem, key=lambda name: abs(ordered.index(name) - index))[:9]
    refs = [by_stem[name] for name in names]
    rects = np.asarray([r['rect'] for r in refs])
    rect = np.median(rects, axis=0)
    mad = np.median(np.abs(rects - rect), axis=0)
    stable = mad <= .008
    angles = np.asarray([r['angle'] for r in refs])
    angle = float(np.median(angles))
    angle_stable = np.median(np.abs(angles - angle)) <= .20
    if stable.sum() < 3:
        return None
    return dict(rect=rect.tolist(), angle=angle if angle_stable else None,
                stable_edges=[name for name, good in zip(('left','top','right','bottom'), stable) if good],
                samples=len(refs), files=[r['file'] for r in refs])

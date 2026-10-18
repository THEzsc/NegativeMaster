"""Conservative, explainable display-tone suggestions for negatives and rolls.

No camera/film response calibration is inferred from scene content. Suggestions
are optional creative starting points, never automatic per-frame corrections.
The caller owns decoding, persistence and deciding which frames belong to a roll.
"""

from collections.abc import Mapping
from types import SimpleNamespace

import numpy as np

import decast


METHOD = "robust-display-midtones-v1"
HEURISTIC_NOTE = "这是基于画面统计的影调建议，不是实测胶片 gamma；夜景、高调或低调作品请保留创作意图。"
# BT.709 coefficients describe the sRGB primaries. Here RGB is rendered display
# code, so this is explicitly a luma proxy, not scene-linear luminance in cd/m².
DISPLAY_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _config(params):
    return dict(params) if isinstance(params, Mapping) else vars(params).copy()


def _report(params, scope="frame"):
    mode = params.get("mode", "color")
    nd = mode == "color" and bool(params.get("negadoctor", False))
    return dict(scope=scope, parameter_key="nd_gamma" if nd else "gamma",
                recommendation=None, confidence="none", confidence_score=0.0,
                warnings=[HEURISTIC_NOTE], stats={}, mode=mode,
                engine="negadoctor" if nd else "positive" if mode == "positive" else "density",
                method=METHOD)


def _reject(report, message):
    report["warnings"].append(message)
    return report


def _region(lin, params):
    """Mirror conversion geometry for input-quality statistics only."""
    view = decast.orient_image(lin, params.get("rotate", 0), params.get("flip", "none"))
    angle = float(params.get("level_angle", 0) or 0)
    rect = params.get("crop_rect")
    if abs(angle) >= .1:
        view = decast._deskew_lin(view, angle)
        rect = decast._rect_intersect(rect, decast._safe_inset_rect(view.shape[:2], angle))
    if rect:
        h, w = view.shape[:2]
        x0, y0, x1, y1 = decast._rect_px(rect, w, h)
        return view[y0:y1, x0:x1]
    margin = float(params.get("crop", 0) or params.get("margin", 0) or 0)
    if margin > 0:
        h, w = view.shape[:2]
        dy, dx = int(h * margin), int(w * margin)
        if h - 2 * dy > 4 and w - 2 * dx > 4:
            return view[dy:h-dy, dx:w-dx]
    return view


def _midpoint(rgb):
    q = np.percentile(rgb @ DISPLAY_LUMA, [35, 50, 65])
    return float(q @ np.array([.25, .5, .25]))


def analyze_frame(lin, params):
    """Return a JSON-safe suggestion without mutating the image or parameters.

    ``lin`` is decoded linear RGB transmittance, H×W×3. ``params`` is a mapping
    or argparse namespace accepted by decast.convert_base. Crop/sample geometry
    is honored. Finishing edits, current gamma and contrast do not influence the
    estimate; film-base, inversion and white-balance settings do.

    The result's ``parameter_key`` identifies gamma vs negadoctor paper gamma.
    A null ``recommendation`` means the evidence is insufficient; do not apply.
    """
    params = _config(params)
    report = _report(params)
    if params.get("use_match") or params.get("_ref_cdfs") is not None:
        return _reject(report, "正在使用参照图匹配，gamma 不参与当前输出；请先关闭匹配再分析。")
    lin = np.asarray(lin)
    if lin.ndim != 3 or lin.shape[-1] != 3 or min(lin.shape[:2], default=0) < 8:
        return _reject(report, "画面太小或不是 RGB 图像，无法可靠分析。")
    if not np.isfinite(lin).all():
        return _reject(report, "输入包含非有限数值，请检查扫描文件或解码设置。")

    step = max(1, int(np.ceil(max(lin.shape[:2]) / 384)))
    sample = np.asarray(lin[::step, ::step], dtype=np.float32)
    opts = params.copy()
    opts.update(gamma=1.0, contrast=0.0, _ref_cdfs=None, _ref_centers=None)
    # A preview statistics rectangle becomes an actual analysis crop; frame
    # borders must not influence the rendered statistics used by the advisor.
    opts["crop_rect"] = params.get("crop_rect") or params.get("stats_rect")
    opts["stats_rect"] = None
    if opts.get("base_rect"):
        opts["base_rect"] = [max(1 if i > 1 else 0, int(round(v / step)))
                             for i, v in enumerate(opts["base_rect"])]
    region = _region(sample, opts)
    if region.size < 192:
        return _reject(report, "有效裁切区域太小，无法可靠分析。")
    flat = region.reshape(-1, 3)
    clipped_dark = float(np.mean(np.any(flat <= 1e-5, axis=1)))
    clipped_bright = float(np.mean(np.any(flat >= .99999, axis=1)))
    density = -np.log10(np.clip(flat, 1e-5, 1))
    density_span = float(np.median(np.percentile(density, 99, axis=0) -
                                   np.percentile(density, 1, axis=0)))
    report["stats"].update(sample_pixels=int(len(flat)), density_span=round(density_span, 4),
                           input_dark_clip_fraction=round(clipped_dark, 4),
                           input_bright_clip_fraction=round(clipped_bright, 4),
                           target_midpoint=.5)
    if density_span < .015:
        return _reject(report, "有效画面密度变化过小；可能是片基、空白帧或近乎均匀的画面，保留当前 gamma。")
    if max(clipped_dark, clipped_bright) > .5:
        return _reject(report, "超过一半像素存在输入通道截断，无法给出可靠 gamma；请先检查翻拍曝光和裁切。")

    namespace = SimpleNamespace(**opts)
    is_nd = report["engine"] == "negadoctor"
    if is_nd:
        namespace.nd_gamma = 1.0
    neutral, _ = decast.convert_base(sample, namespace)
    if not np.isfinite(neutral).all():
        return _reject(report, "反转结果包含无效数值，请检查片基、黑白点及引擎参数。")
    luma = neutral @ DISPLAY_LUMA
    q = np.percentile(luma, [5, 25, 50, 75, 95])
    report["stats"].update(neutral_luma_percentiles=[round(float(v), 4) for v in q],
                           output_dark_clip_fraction=round(float(np.mean(luma <= .001)), 4),
                           output_bright_clip_fraction=round(float(np.mean(luma >= .999)), 4))
    if q[4] - q[0] < .025 or q[2] <= .005 or q[2] >= .995:
        return _reject(report, "反转后有效中间调不足；请先检查片基、黑白点、裁切或曝光设置。")

    low, high = (1.0, 6.0) if is_nd else (.8, 2.8)
    if is_nd:
        # Paper gamma acts in the opposite direction from the density engine's
        # display gamma, and precedes highlight compression / white balance.
        # Evaluate the real pipeline; do not pretend a gamma power commutes with
        # those operations. A bounded grid tolerates small non-monotonic changes.
        candidates = np.geomspace(low, high, 21)
        errors = []
        for value in candidates:
            namespace.nd_gamma = float(value)
            rendered, _ = decast.convert_base(sample, namespace)
            errors.append(abs(_midpoint(rendered) - .5))
        index = int(np.argmin(errors))
        candidate = float(candidates[index])
        residual = errors[index]
        refine = np.linspace(candidates[max(0, index-1)], candidates[min(20, index+1)], 9)
        for value in refine:
            namespace.nd_gamma = float(value)
            rendered, _ = decast.convert_base(sample, namespace)
            error = abs(_midpoint(rendered) - .5)
            if error < residual:
                candidate, residual = float(value), error
    else:
        # Transform RGB first, then measure luma. pow(luma) would be inaccurate
        # for colorful scenes because the nonlinear transform does not commute.
        left, right = low, high
        for _ in range(16):
            mid = (left + right) / 2
            if _midpoint(np.power(neutral, 1 / mid)) < .5:
                left = mid
            else:
                right = mid
        candidate = (left + right) / 2
        residual = abs(_midpoint(np.power(neutral, 1 / candidate)) - .5)

    confidence = .7  # One frame cannot establish the intended scene brightness.
    if max(clipped_dark, clipped_bright) > .01:
        confidence -= .2
        report["warnings"].append("输入存在通道截断；gamma 无法恢复已丢失的细节。")
    if q[2] < .12 or q[2] > .85:
        confidence -= .15
        report["warnings"].append("画面中间调偏向一端，建议与同卷其他照片一起判断。")
    if candidate < low + .025 or candidate > high - .025 or residual > .05:
        confidence -= .25
        report["warnings"].append("建议触及保守范围或不能充分平衡中间调；请手动复核，不继续自动扩大 gamma。")
    report.update(recommendation=round(candidate, 3),
                  confidence="medium" if confidence >= .55 else "low",
                  confidence_score=round(max(confidence, .1), 3))
    report["stats"].update(midpoint_residual=round(residual, 4), gamma_bounds=[low, high])
    return report


def analyze_roll(reports):
    """Combine frame reports into one common gamma, with equal weight per frame.

    Use representative frames from a single film roll / scan setup. A robust
    median in log-gamma space ignores minority outliers. Different engines,
    modes or methods are deliberately not pooled. Caller applies the result to
    the roll; this module never changes per-frame exposure or any saved edits.
    """
    reports = list(reports)
    result = _report({}, "roll")
    result.update(sample_count=len(reports), accepted_count=0, rejected_count=len(reports), spread=None)
    valid = [r for r in reports if r.get("recommendation") is not None
             and np.isfinite(r["recommendation"]) and r["recommendation"] > 0
             and r.get("confidence") != "none"]
    if not valid:
        return _reject(result, "没有可用的画面建议，请选取同卷具有细节的代表照片。")
    signatures = {(r.get("engine"), r.get("mode"), r.get("parameter_key"), r.get("method")) for r in valid}
    if len(signatures) != 1:
        return _reject(result, "所选照片的反转引擎或胶片模式不一致，请按相同模式分组分析。")
    engine, mode, key, method = signatures.pop()
    result.update(engine=engine, mode=mode, parameter_key=key, method=method)
    values = np.log([r["recommendation"] for r in valid])
    center = float(np.median(values))
    mad = float(np.median(np.abs(values - center)))
    # A floor avoids excluding ordinary noise when several frames are identical.
    keep = np.abs(values - center) <= max(.12, 3 * 1.4826 * mad)
    retained = values[keep]
    count = int(keep.sum())
    score = float(np.median([r.get("confidence_score", .3) for r, k in zip(valid, keep) if k]))
    spread = float(np.expm1(np.percentile(retained, 75) - np.percentile(retained, 25)))
    if count < 3:
        score = min(score, .4)
        result["warnings"].append("可用样本不足 3 张，当前建议不能充分代表整卷。")
    elif count >= 5 and spread < .15 and score >= .55:
        score = min(.85, score + .12)
    if spread > .35:
        score = min(score, .4)
        result["warnings"].append("同卷建议差异较大；检查是否混入不同胶卷、翻拍设置或特殊明暗场景。")
    rejected = len(reports) - count
    if rejected:
        result["warnings"].append(f"已排除 {rejected} 张无效或离群样本。")
    result.update(recommendation=round(float(np.exp(np.median(retained))), 3),
                  confidence="high" if score >= .8 else "medium" if score >= .55 else "low",
                  confidence_score=round(score, 3), accepted_count=count,
                  rejected_count=rejected, spread=round(spread, 4))
    result["stats"] = {"gamma_min": round(float(np.exp(retained.min())), 3),
                       "gamma_max": round(float(np.exp(retained.max())), 3)}
    result["warnings"].append("整卷共用一个 gamma，保留各张曝光与精调；不同拍摄意图仍需单独判断。")
    return result

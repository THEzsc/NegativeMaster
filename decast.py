#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decast.py —— 胶片翻拍负片「去色罩 + 反转」工具

把翻拍（数码相机拍摄）彩色负片得到的文件，自动去掉橙色色罩（orange mask）、
反转为正片，并做白平衡 / 色阶 / 影调处理。

支持输入：
  - 相机 RAW：.ARW .ARQ .CR2 .CR3 .NEF .RAF .DNG .RW2 等（需 rawpy）
  - 普通图像：.tif .tiff .png .jpg .jpeg

核心原理（按通道在「密度/对数」空间做反转与归一化）：
  1. 读入并转成线性 RGB（透过率），值域 (0,1]。
  2. 转成密度 D = -log10(透过率)。负片越亮(透光多)→密度越小；场景越亮→负片越密→D越大。
  3. 橙色色罩在密度空间里相当于「每个通道一个固定加性偏移」。
     对每个通道各自减去黑点(对应片基/色罩)、除以白黑点差，
     就能同时完成：去色罩 + 反转 + 通道白平衡 + 拉对比。
  4. 黑点白点用百分位自动估计；也可以用 --base-rect 指定片基区域来精确锚定色罩。
  5. 最后做可选的灰世界白平衡、gamma、对比度 S 曲线，输出 8/16bit。

用法示例：
  # 单张 RAW
  ./run.sh -i "../2026-07-01 3252 翻拍/TZP06733.ARW" -o out.tif

  # 批量处理一个文件夹里的所有 tif，输出到 positives/
  ./run.sh -i "../某文件夹" -o positives --recursive

  # 用片基矩形精确去色罩（x,y,w,h，像素坐标，取一块没有影像的橙色片基）
  ./run.sh -i neg.tif -o pos.tif --base-rect 50,50,200,200
"""

import argparse
import json
import os
import sys
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # 翻拍文件像素很大，关掉解压炸弹保护上限

RAW_EXTS = {".arw", ".arq", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".rw2",
            ".orf", ".pef", ".srw", ".raw", ".3fr", ".iiq"}
IMG_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}

try:
    import rawpy
    HAVE_RAWPY = True
except Exception:
    HAVE_RAWPY = False

# 亮度权重（BT.601，与本文件其余部分保持一致）
LUMA_W = np.array([0.299, 0.587, 0.114], dtype=np.float32)


# --------------------------------------------------------------------------- #
# 预设：把常用色调参数存成 JSON，CLI 与 gui.py 共用
# --------------------------------------------------------------------------- #
PRESET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")
# 预设里保存的键（只存「色调相关」参数，不存输入输出路径等）
PRESET_KEYS = ("black_pct", "white_pct", "wb", "gamma", "contrast",
               "saturation", "temp", "tint", "sharpen", "sharpen_radius",
               "denoise", "mode",
               # LR 风格精调（曝光/高光阴影/白黑场、曲线、HSL、鲜艳度、晕影）
               "exposure", "highlights", "shadows", "whites", "blacks",
               "curve", "curve_r", "curve_g", "curve_b",
               "hsl", "vibrance", "vignette")


def list_presets():
    """列出 presets/ 目录下所有预设名（不含扩展名），按名字排序。"""
    if not os.path.isdir(PRESET_DIR):
        return []
    return sorted(os.path.splitext(n)[0] for n in os.listdir(PRESET_DIR)
                  if n.lower().endswith(".json"))


def load_preset(name):
    """读取一个预设，返回参数字典（只含 PRESET_KEYS 里认识的键）。"""
    path = os.path.join(PRESET_DIR, name + ".json")
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return {k: v for k, v in d.items() if k in PRESET_KEYS}


def save_preset(name, d):
    """把参数字典存成预设 JSON，返回文件路径。多余的键会被过滤掉。"""
    os.makedirs(PRESET_DIR, exist_ok=True)
    path = os.path.join(PRESET_DIR, name + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: d[k] for k in PRESET_KEYS if k in d}, f,
                  ensure_ascii=False, indent=2)
    return path


# --------------------------------------------------------------------------- #
# 读取
# --------------------------------------------------------------------------- #
def srgb_to_linear(x):
    """sRGB EOTF：编码值 -> 线性光。x 为 [0,1] float。"""
    a = 0.055
    return np.where(x <= 0.04045, x / 12.92,
                    (np.maximum(x + a, 0) / (1 + a)) ** 2.4)


def load_image(path, args):
    """返回 (linear_rgb float32 [0,1] HxWx3, was_raw bool)。"""
    ext = os.path.splitext(path)[1].lower()

    if ext in RAW_EXTS:
        if not HAVE_RAWPY:
            raise RuntimeError(
                f"需要 rawpy 才能读取 RAW 文件 {path}。请先安装：pip install rawpy")
        with rawpy.imread(path) as raw:
            # 线性输出（gamma=1）、不自动提亮、16bit。
            # 用相机白平衡只是给一个相对正常的起点；后面按通道归一化会再校正。
            pp = dict(
                gamma=(1, 1),
                no_auto_bright=True,
                output_bps=16,
                use_camera_wb=not args.no_camera_wb,
                use_auto_wb=False,
                output_color=rawpy.ColorSpace.sRGB,
                user_flip=0 if args.no_autorotate else -1,
            )
            if args.raw_denoise:
                # RAW 阶段的 FBDD 降噪，反转前就先压一遍传感器噪声
                pp["fbdd_noise_reduction"] = rawpy.FBDDNoiseReductionMode.Full
            rgb16 = raw.postprocess(**pp)
        lin = rgb16.astype(np.float32) / 65535.0
        return lin, True

    if ext in IMG_EXTS:
        # Pillow converts RGB 16-bit TIFF to RGB 8-bit on read. Preserve the
        # original samples: small transmittance errors grow after -log10().
        if ext in (".tif", ".tiff"):
            import tifffile
            with tifffile.TiffFile(path) as tif:
                series = tif.series[0]
                page = tif.pages[0]
                if page.photometric.name in ("RGB", "MINISBLACK", "MINISWHITE"):
                    arr = series.asarray()
                    if arr.ndim == 3 and "S" in series.axes:
                        arr = np.moveaxis(arr, series.axes.index("S"), -1)
                    if page.photometric.name == "MINISWHITE":
                        peak = np.iinfo(arr.dtype).max if arr.dtype.kind == "u" else 1.0
                        arr = peak - arr
                else:
                    with Image.open(path) as im:
                        arr = np.asarray(im.convert("RGB"))
        else:
            with Image.open(path) as im:
                if im.mode not in ("RGB", "RGBA", "L", "LA", "I", "I;16", "F"):
                    im = im.convert("RGB")
                arr = np.asarray(im)
        if arr.ndim == 2:  # 灰度 -> 复制成三通道
            arr = np.stack([arr] * 3, axis=-1)
        if arr.ndim != 3 or arr.shape[-1] not in (2, 3, 4):
            raise ValueError("需要单幅灰度或 RGB 图像，不支持多页/多维图像")
        if arr.shape[-1] == 2:  # 灰度 + alpha
            arr = np.repeat(arr[..., :1], 3, axis=-1)
        if arr.shape[-1] == 4:  # 去 alpha
            arr = arr[..., :3]
        if arr.dtype.kind == "u":
            maxv = float(np.iinfo(arr.dtype).max)
        elif arr.dtype.kind == "f":
            maxv = 1.0  # floating TIFF values are normalized transmittance
        elif arr.dtype.kind == "i" and arr.min() >= 0 and arr.max() <= 65535:
            maxv = 65535.0  # Pillow may expose 16-bit PNG as mode I
        else:
            raise ValueError("图像必须使用无符号整数或归一化浮点 RGB 数据")
        enc = arr.astype(np.float32) / maxv
        if not np.isfinite(enc).all():
            raise ValueError("图像包含 NaN 或无穷值，无法计算胶片密度")
        enc = np.clip(enc, 0.0, 1.0)
        # 普通图像默认按 sRGB 反伽马回到线性，使密度运算正确
        if args.input_gamma == "srgb":
            lin = srgb_to_linear(enc)
        elif args.input_gamma == "linear":
            lin = enc
        else:
            input_gamma = float(args.input_gamma)
            if not np.isfinite(input_gamma) or input_gamma <= 0:
                raise ValueError("输入 gamma 必须是正有限数、srgb 或 linear")
            lin = np.power(enc, input_gamma)
        return lin.astype(np.float32), False

    raise RuntimeError(f"不支持的文件类型：{ext}")


# --------------------------------------------------------------------------- #
# 降噪：色度降噪（只糊颜色噪声，保留亮度细节 -> 去彩色颗粒不掉锐度）
# --------------------------------------------------------------------------- #
def _box1d(x, r, axis):
    k = 2 * r + 1
    pad = [(r, r) if a == axis else (0, 0) for a in range(x.ndim)]
    xp = np.pad(x, pad, mode="edge")
    cs = np.cumsum(xp, axis=axis)
    zero = np.zeros_like(np.take(cs, [0], axis=axis))
    cs = np.concatenate([zero, cs], axis=axis)
    n = x.shape[axis]
    hi = [slice(None)] * x.ndim
    lo = [slice(None)] * x.ndim
    hi[axis] = slice(k, k + n)
    lo[axis] = slice(0, n)
    return (cs[tuple(hi)] - cs[tuple(lo)]) / k


def box_blur(x, r):
    if r < 1:
        return x
    return _box1d(_box1d(x, r, 0), r, 1)


def build_ref_cdf(ref, nbins=512):
    """由参照图（[0,1] HxWx3）建立每通道 CDF，供直方图匹配用。"""
    edges = np.linspace(0, 1, nbins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    cdfs = []
    for c in range(3):
        hist, _ = np.histogram(ref[..., c].ravel(), edges)
        cdf = np.cumsum(hist).astype(np.float64)
        cdf /= max(cdf[-1], 1.0)
        cdfs.append(cdf)
    return centers, cdfs


def hist_match(P, centers, ref_cdfs, nbins=512):
    """把 P 每个通道的分布映射到参照 CDF（转移参照的色调与色彩）。"""
    edges = np.linspace(0, 1, nbins + 1)
    src_centers = (edges[:-1] + edges[1:]) / 2
    view = stats_view(P)  # 下采样求源 CDF，够用且快
    out = np.empty_like(P)
    for c in range(3):
        hist, _ = np.histogram(view[..., c].ravel(), edges)
        scdf = np.cumsum(hist).astype(np.float64)
        scdf /= max(scdf[-1], 1.0)
        s_at = np.interp(P[..., c], src_centers, scdf)
        out[..., c] = np.interp(s_at, ref_cdfs[c], centers)
    return np.clip(out, 0.0, 1.0)


def saturation_adjust(P, s):
    """在亮度轴上缩放色度调整饱和度（s<1 降饱和，s>1 增）。"""
    if abs(s - 1.0) < 1e-3:
        return P
    Y = (P @ np.array([0.299, 0.587, 0.114], dtype=P.dtype))[..., None]
    return np.clip(Y + (P - Y) * s, 0.0, 1.0)


def chroma_denoise(P, radius):
    """在亮度/色度空间给色度做模糊，去掉彩色颗粒，亮度细节原样保留。"""
    if radius < 1:
        return P
    R, G, B = P[..., 0], P[..., 1], P[..., 2]
    Y = 0.299 * R + 0.587 * G + 0.114 * B
    Pr = box_blur(R - Y, radius)   # 模糊色度
    Pb = box_blur(B - Y, radius)
    R2 = Y + Pr
    B2 = Y + Pb
    G2 = (Y - 0.299 * R2 - 0.114 * B2) / 0.587
    return np.clip(np.stack([R2, G2, B2], axis=-1), 0.0, 1.0)


def apply_temp_tint(P, temp, tint):
    """色温/色调微调（在反转后的线性正片上做通道乘法）。

    temp: -100~100。>0 偏暖（R 增、B 减），<0 偏冷（R 减、B 增）。
    tint: -100~100。>0 偏品红（G 减），<0 偏绿（G 增）。
    三个通道增益按均值归一，避免整体曝光漂移。
    注意：--match（直方图匹配）模式下该调整会被跳过，因为匹配会
    直接把色调映射到参照图，再叠 temp/tint 没有意义。
    """
    if abs(temp) < 1e-3 and abs(tint) < 1e-3:
        return P
    t = float(np.clip(temp, -100.0, 100.0)) / 100.0
    ti = float(np.clip(tint, -100.0, 100.0)) / 100.0
    k = 0.3  # 满档时通道最大偏移 30%
    gains = np.array([1.0 + k * t, 1.0 - k * ti, 1.0 - k * t], dtype=P.dtype)
    gains = gains / gains.mean()  # 均值归一，保持整体曝光
    return np.clip(P * gains, 0.0, 1.0)


def unsharp_luma(P, amount, radius):
    """只对亮度 Y 做 USM 锐化，色度不动（不会放大彩色颗粒/彩边）。

    amount: 锐化量 0~3，0 表示不锐化。radius: 模糊半径（像素）。
    """
    r = int(round(radius))
    if amount <= 1e-3 or r < 1:
        return P
    Y = P @ LUMA_W.astype(P.dtype)
    delta = (Y - box_blur(Y, r)) * float(amount)
    return np.clip(P + delta[..., None], 0.0, 1.0)


def wb_from_sample(P, rect=None, px=None, py=None, half=5):
    """白点取样白平衡。

    新版 UI 传 rect：取框选范围内每通道平均值，减少单点噪声影响。
    旧参数文件可能只有 px/py：仍按 11x11 邻域取中值以保持兼容。
    """
    hh, ww = P.shape[:2]
    if rect is not None:
        x0, y0, x1, y1 = rect
        x0 = min(max(int(x0), 0), ww - 1)
        x1 = min(max(int(x1), x0 + 1), ww)
        y0 = min(max(int(y0), 0), hh - 1)
        y1 = min(max(int(y1), y0 + 1), hh)
        color = P[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    else:
        px = min(max(int(px), 0), ww - 1)
        py = min(max(int(py), 0), hh - 1)
        x0, x1 = max(0, px - half), min(ww, px + half + 1)
        y0, y1 = max(0, py - half), min(hh, py + half + 1)
        color = np.median(P[y0:y1, x0:x1].reshape(-1, 3), axis=0)
    g = float(color.mean())
    scale = np.clip(g / np.clip(color, 1e-4, None), 0.4, 2.5)
    return np.clip(P * scale.astype(P.dtype), 0.0, 1.0)


def wb_from_point(P, px, py, half=5):
    """兼容旧调用：取点附近 11x11 中值做白平衡。"""
    return wb_from_sample(P, px=px, py=py, half=half)


# --------------------------------------------------------------------------- #
# LR 风格精调：曝光/高光/阴影/白黑场、色调曲线、HSL、鲜艳度、晕影
# --------------------------------------------------------------------------- #
def tone_adjust(P, exposure=0.0, highlights=0.0, shadows=0.0,
                whites=0.0, blacks=0.0):
    """LR 风格影调五件套（作用在显示值 0~1 上）。

    exposure:  曝光 EV（-3~3），2^ev 增益。
    highlights/shadows: -100~100。权重分别集中在高光(Y²(1-Y))与
      阴影(Y(1-Y)²)，纯黑/纯白端点被钉住不动，>0 提亮 <0 压暗。
    whites/blacks: -100~100，移动白场/黑场端点（levels 式重映射，
      blacks>0 是「褪色」抬黑，blacks<0 压黑；whites 同理动白场）。
    曝光与高光/阴影经亮度比值作用到 RGB（保色相），白黑场直接按通道重映射。
    """
    ev = float(np.clip(exposure, -3.0, 3.0))
    h = float(np.clip(highlights, -100, 100)) / 100.0
    s = float(np.clip(shadows, -100, 100)) / 100.0
    w = float(np.clip(whites, -100, 100)) / 100.0
    b = float(np.clip(blacks, -100, 100)) / 100.0
    if (abs(ev) < 1e-4 and abs(h) < 1e-3 and abs(s) < 1e-3
            and abs(w) < 1e-3 and abs(b) < 1e-3):
        return P
    eps = 1e-6
    out = np.clip(P, 0.0, 1.0)

    if abs(ev) >= 1e-4 or abs(h) >= 1e-3 or abs(s) >= 1e-3:
        Y = np.clip(out @ LUMA_W.astype(out.dtype), 0.0, 1.0)
        Y2 = Y * np.float32(2.0 ** ev)
        Yc = np.clip(Y2, 0.0, 1.0)
        if abs(s) >= 1e-3:   # 阴影：权重 Y(1-Y)³，峰值在 Y≈1/4，几乎不碰高光
            Y2 = Y2 + np.float32(2.2 * s) * Yc * (1.0 - Yc) ** 3
        if abs(h) >= 1e-3:   # 高光：权重 Y³(1-Y)，峰值在 Y≈3/4，几乎不碰阴影
            Y2 = Y2 + np.float32(2.2 * h) * (Yc ** 3) * (1.0 - Yc)
        ratio = np.clip(Y2, 0.0, None) / np.maximum(Y, eps)
        out = np.clip(out * ratio[..., None].astype(out.dtype), 0.0, 1.0)

    # 白场/黑场：按通道 levels 重映射（能真正抬起纯黑/拉爆纯白）
    w0 = 0.30 * w
    b0 = 0.30 * b
    if abs(w0) >= 1e-4:
        if w0 > 0:
            out = out / np.float32(max(1.0 - w0, 0.1))
        else:
            out = out * np.float32(1.0 + w0)
    if abs(b0) >= 1e-4:
        if b0 > 0:
            out = np.float32(b0) + out * np.float32(1.0 - b0)
        else:
            out = (out + np.float32(b0)) / np.float32(1.0 + b0)
    return np.clip(out, 0.0, 1.0)


def _pchip_lut(points, n=1024):
    """控制点 → 单调 PCHIP 曲线 LUT。

    points: [[x,y], ...]（0~1）。返回 (xs_grid, ys_lut) 供 np.interp 用；
    点不足 / 恒等（只有 (0,0)-(1,1) 两点）时返回 None 表示跳过。
    斜率用 Fritsch-Carlson 限幅，保证不过冲、单调段保单调。
    """
    try:
        pts = sorted((float(x), float(y)) for x, y in points)
    except (TypeError, ValueError):
        return None
    ded = []
    for x, y in pts:  # x 去重（后值覆盖前值）
        if ded and abs(x - ded[-1][0]) < 1e-6:
            ded[-1] = (x, y)
        else:
            ded.append((x, y))
    if len(ded) < 2:
        return None
    xs = np.clip(np.array([p[0] for p in ded], dtype=np.float64), 0, 1)
    ys = np.clip(np.array([p[1] for p in ded], dtype=np.float64), 0, 1)
    if (len(ded) == 2 and abs(xs[0]) < 1e-6 and abs(ys[0]) < 1e-6
            and abs(xs[1] - 1) < 1e-6 and abs(ys[1] - 1) < 1e-6):
        return None  # 恒等曲线
    h = np.diff(xs)
    h[h < 1e-6] = 1e-6
    d = np.diff(ys) / h
    m = np.zeros(len(xs))
    if len(xs) == 2:
        m[:] = d[0]
    else:
        m[0], m[-1] = d[0], d[-1]
        for i in range(1, len(xs) - 1):
            if d[i - 1] * d[i] <= 0:
                m[i] = 0.0
            else:
                w1 = 2 * h[i] + h[i - 1]
                w2 = h[i] + 2 * h[i - 1]
                m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
        for i in range(len(d)):  # Fritsch-Carlson 限幅
            if abs(d[i]) < 1e-12:
                m[i] = m[i + 1] = 0.0
            else:
                a, b = m[i] / d[i], m[i + 1] / d[i]
                q = a * a + b * b
                if q > 9.0:
                    t = 3.0 / np.sqrt(q)
                    m[i] = t * a * d[i]
                    m[i + 1] = t * b * d[i]
    grid = np.linspace(0.0, 1.0, n)
    idx = np.clip(np.searchsorted(xs, grid) - 1, 0, len(xs) - 2)
    t = (grid - xs[idx]) / h[idx]
    lut = (ys[idx] * (2 * t ** 3 - 3 * t ** 2 + 1)
           + m[idx] * h[idx] * (t ** 3 - 2 * t ** 2 + t)
           + ys[idx + 1] * (-2 * t ** 3 + 3 * t ** 2)
           + m[idx + 1] * h[idx] * (t ** 3 - t ** 2))
    lut = np.where(grid <= xs[0], ys[0], lut)   # 定义域外钳到端点值
    lut = np.where(grid >= xs[-1], ys[-1], lut)
    return grid.astype(np.float32), np.clip(lut, 0.0, 1.0).astype(np.float32)


def apply_curves(P, curve=None, curve_r=None, curve_g=None, curve_b=None):
    """色调曲线（单调 PCHIP 过控制点）。

    curve 是 RGB 主曲线，curve_r/g/b 是单通道曲线；每条为 [[x,y],...]。
    应用顺序：先各单通道，再主曲线（与 LR 点曲线习惯一致）。
    None / 恒等曲线自动跳过，全部恒等时原样返回。
    """
    per = [(_pchip_lut(c) if c else None)
           for c in (curve_r, curve_g, curve_b)]
    lut_m = _pchip_lut(curve) if curve else None
    if lut_m is None and all(v is None for v in per):
        return P

    def _lookup(x, lut_y):
        # LUT 网格是均匀的，直接取整索引比 np.interp 的二分查找快一个量级
        n = lut_y.shape[0]
        idx = (x * (n - 1) + 0.5).astype(np.int32)
        np.clip(idx, 0, n - 1, out=idx)
        return lut_y[idx]

    out = np.clip(P, 0.0, 1.0).copy()
    for i, lut in enumerate(per):
        if lut is not None:
            out[..., i] = _lookup(out[..., i], lut[1])
    if lut_m is not None:
        out = _lookup(out, lut_m[1])
    return np.clip(out, 0.0, 1.0)


def _rgb_to_hsv(P):
    """向量化 RGB→HSV。输入 [0,1] HxWx3，返回 (H,S,V)，H 为 0~1。"""
    r, g, b = P[..., 0], P[..., 1], P[..., 2]
    mx = np.max(P, axis=-1)
    mn = np.min(P, axis=-1)
    diff = mx - mn
    H = np.zeros_like(mx)
    mask = diff > 1e-8
    safe = np.where(mask, diff, 1.0)
    rm = mask & (mx == r)
    gm = mask & (mx == g) & ~rm
    bm = mask & ~rm & ~gm
    H = np.where(rm, ((g - b) / safe) % 6.0, H)
    H = np.where(gm, (b - r) / safe + 2.0, H)
    H = np.where(bm, (r - g) / safe + 4.0, H)
    H = (H / 6.0) % 1.0
    S = np.where(mx > 1e-8, diff / np.maximum(mx, 1e-8), 0.0)
    return H.astype(P.dtype), S.astype(P.dtype), mx


def _hsv_to_rgb(H, S, V):
    """向量化 HSV→RGB。H 为 0~1，返回 HxWx3。
    按色相扇区用布尔掩码就地赋值，比 np.choose 少建一堆中间大数组。"""
    h6 = (H % 1.0) * 6.0
    fi = np.floor(h6)
    i = fi.astype(np.int8) % 6
    f = (h6 - fi).astype(V.dtype)
    p = V * (1.0 - S)
    q = V * (1.0 - S * f)
    t = V * (1.0 - S * (1.0 - f))
    out = np.empty(V.shape + (3,), dtype=V.dtype)
    sectors = ((V, t, p), (q, V, p), (p, V, t),
               (p, q, V), (t, p, V), (V, p, q))
    for k, (rr, gg, bb) in enumerate(sectors):
        m = i == k
        out[..., 0][m] = rr[m]
        out[..., 1][m] = gg[m]
        out[..., 2][m] = bb[m]
    return out


# HSL 八色区（与 LR 一致的分区习惯），中心色相角（度）
HSL_BANDS = ("red", "orange", "yellow", "green",
             "aqua", "blue", "purple", "magenta")
_HSL_CENTERS = np.array([0.0, 30.0, 60.0, 120.0,
                         180.0, 240.0, 280.0, 320.0])


def hsl_adjust(P, hsl=None, vibrance=0.0):
    """LR 风格 HSL 八色调整 + 鲜艳度。

    hsl: {色区: {"h":±100, "s":±100, "l":±100}}，色区为 HSL_BANDS 里的名字。
      色相满档 ≈ ±30°，饱和度/明亮度满档 ±60%。八个色区的参数沿色相环做
      分段线性插值，相邻色区平滑过渡；低饱和(接近灰)的像素自动少受影响。
    vibrance: -100~100 鲜艳度。低饱和像素受力大、已经很艳的动得少
      （S' = S + v·(1-S)·S·2），比饱和度更不容易把肤色推爆。
    """
    hsl = hsl or {}
    has_hsl = any(abs(float((v or {}).get(k, 0))) > 1e-3
                  for v in hsl.values() for k in ("h", "s", "l"))
    vib = float(np.clip(vibrance, -100, 100)) / 100.0
    if not has_hsl and abs(vib) < 1e-3:
        return P
    H, S, V = _rgb_to_hsv(np.clip(P, 0.0, 1.0))
    if has_hsl:
        hv = np.zeros(8)
        sv = np.zeros(8)
        lv = np.zeros(8)
        for i, band in enumerate(HSL_BANDS):
            d = hsl.get(band) or {}
            hv[i] = np.clip(float(d.get("h", 0)), -100, 100) / 100.0 * 30.0
            sv[i] = np.clip(float(d.get("s", 0)), -100, 100) / 100.0 * 0.6
            lv[i] = np.clip(float(d.get("l", 0)), -100, 100) / 100.0 * 0.6
        deg = H * 360.0
        # 沿色相环 wrap 的分段线性插值（首尾各补一个周期点）
        cx = np.concatenate([[_HSL_CENTERS[-1] - 360.0], _HSL_CENTERS,
                             [_HSL_CENTERS[0] + 360.0]])

        def wint(vals):
            vy = np.concatenate([[vals[-1]], vals, [vals[0]]])
            return np.interp(deg, cx, vy).astype(P.dtype)

        wS = np.clip(S / 0.15, 0.0, 1.0)  # 近灰像素不吃 HSL，避免放大彩噪
        H = (H + wint(hv) / 360.0 * wS) % 1.0
        S = np.clip(S * (1.0 + wint(sv) * wS), 0.0, 1.0)
        V = np.clip(V * (1.0 + wint(lv) * wS), 0.0, 1.0)
    if abs(vib) >= 1e-3:
        S = np.clip(S + np.float32(vib * 2.0) * (1.0 - S) * S, 0.0, 1.0)
    return np.clip(_hsv_to_rgb(H, S, V), 0.0, 1.0).astype(P.dtype)


def apply_vignette(P, amount, rect=None):
    """晕影。amount -100~100：<0 四角压暗（常用），>0 提亮四角。

    rect 给出归一化 [x0,y0,x1,y1] 时以该矩形为「画面」算径向落影——
    预览（整幅显示+裁切框）时传裁切框进来，效果就和导出裁切后完全一致。
    中心 35% 半径内不受影响，向角落平滑(smoothstep)过渡。
    """
    a = float(np.clip(amount, -100, 100)) / 100.0
    if abs(a) < 1e-3:
        return P
    h, w = P.shape[:2]
    if rect:
        xa, ya, xb, yb = _rect_px(rect, w, h)
        cx, cy = (xa + xb - 1) / 2.0, (ya + yb - 1) / 2.0
        rx, ry = max((xb - xa) / 2.0, 1.0), max((yb - ya) / 2.0, 1.0)
    else:
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        rx, ry = max(w / 2.0, 1.0), max(h / 2.0, 1.0)
    yy = ((np.arange(h, dtype=np.float32) - cy) / ry) ** 2
    xx = ((np.arange(w, dtype=np.float32) - cx) / rx) ** 2
    r = np.sqrt(yy[:, None] + xx[None, :]) / np.float32(np.sqrt(2.0))
    t = np.clip((r - 0.35) / 0.65, 0.0, 1.0)
    fall = t * t * (3.0 - 2.0 * t)  # smoothstep
    gain = (1.0 + np.float32(a * 0.7) * fall).astype(P.dtype)
    return np.clip(P * gain[..., None], 0.0, 1.0)


def _longest_run(mask):
    """一维布尔数组里最长连续 True 段，返回 (长度, 起点, 终点含)。"""
    best_len, best_s, best_e = 0, -1, -1
    cur, s = 0, 0
    for i, v in enumerate(mask):
        if v:
            if cur == 0:
                s = i
            cur += 1
            if cur > best_len:
                best_len, best_s, best_e = cur, s, i
        else:
            cur = 0
    return best_len, best_s, best_e


def _film_edge_image(lin):
    """Area-average before analysis: narrow borders survive without RAW aliasing."""
    a = np.asarray(lin, dtype=np.float32)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    if a.ndim != 3 or a.shape[2] < 3 or min(a.shape[:2]) < 24:
        raise ValueError("Image is too small for frame detection")
    a = np.nan_to_num(a[..., :3], nan=0.0, posinf=1.0, neginf=0.0)
    h, w = a.shape[:2]
    scale = min(1.0, 1400.0 / max(h, w))
    size = (max(24, round(w * scale)), max(24, round(h * scale)))
    a = np.stack([np.asarray(Image.fromarray(a[..., c]).resize(
        size, Image.Resampling.BOX)) for c in range(3)], axis=-1)
    lo, hi = np.percentile(a, [0.5, 99.5], axis=(0, 1))
    # Normalize channels independently so orange film base does not dominate.
    return np.sqrt(np.clip((a - lo) / np.maximum(hi - lo, 0.02), 0, 1))


def _detect_outer_edge(a, soft=False):
    """Find one border, with inward distance on axis 0.

    A bounded line search votes across 160 scanlines. Candidates need a long
    contrast edge AND a relatively uniform exterior band. This rejects most
    subject edges. Unknown boundaries remain at the image edge.
    Returns d(t)=offset+slope*(t-center), residual, and confidence.
    """
    h, w = a.shape[:2]
    ts = np.linspace(w * 0.08, w * 0.92 - 1, min(160, w - 2)).astype(int)
    center = (w - 1) / 2
    tx = ts - center
    limit = max(4, int(h * (0.05 if soft else 0.36)))
    # A three-pixel step captures narrow bright film base as well as dark holders.
    smooth = (a[:, np.maximum(ts - 1, 0)] + a[:, ts] +
              a[:, np.minimum(ts + 1, w - 1)]) / 3
    if soft:
        # Pool along a physical edge, not through it. Weak narrow borders can be
        # lost beneath RAW grain and stronger scene edges in the broad search.
        radius = max(2, round(w * .011))
        smooth = sum(a[:, np.clip(ts + i, 0, w - 1)] for i in range(-radius, radius + 1)) / (2 * radius + 1)
    grad = np.zeros((h, len(ts)), np.float32)
    grad[1:-1] = np.max(np.abs(smooth[2:] - smooth[:-2]), axis=2) / 2
    noise = np.median(grad[:limit], axis=0)
    threshold = np.maximum(0.003, noise * 2.5)
    if soft:
        noise = np.median(grad[1:max(5, int(h * .012))], axis=0)
        threshold = np.maximum(.0005, noise * 2.0)
    # Search slopes first; all candidates must have support distributed along edge.
    candidates = []
    ds = np.arange(1, limit)
    cols = np.arange(len(ts))[None, :]
    # Fine near-level angles matter for scan alignment; coarse voting previously
    # quantized weak edges to about 0.33 degrees or missed them altogether.
    slopes = np.tan(np.radians(np.unique(np.r_[np.arange(-2., 2.01, .05),
                                               np.arange(-8., 8.01, .25)])))
    for slope in slopes:
        yy = np.rint(ds[:, None] + slope * tx).astype(int)
        valid = (yy >= 1) & (yy < limit)
        strength = grad[np.clip(yy, 1, h - 2), cols]
        supported = (strength > threshold) & valid
        support = supported.mean(axis=1)
        score = np.mean(np.minimum(strength / threshold, 5) * valid, axis=1)
        score *= support ** 2
        # Non-maximum suppression keeps weaker inner film-base edges even when
        # the outer holder edge has much higher contrast.
        for _ in range(8):
            j = int(np.argmax(score))
            if score[j] <= 0:
                break
            if support[j] >= 0.50:
                candidates.append((float(score[j]), float(ds[j]), float(slope)))
            score[max(0, j - 3):j + 4] = 0
    # Prioritize actual peripheral edges before deep subject lines.
    candidates.sort(key=lambda v: v[0] / (1 + 12 * v[1] / h), reverse=True)
    tested = []
    accepted = []
    for score, offset, slope in candidates:
        if any(abs(offset - d) < 3 and abs((slope - m) * w) < 5 for d, m in tested):
            continue
        tested.append((offset, slope))
        if len(tested) > 64:
            break
        pred = offset + slope * tx
        # Refine the voted line from nearby local maxima, then reject outliers.
        ys = np.rint(pred).astype(int)[None, :] + np.arange(-3, 4)[:, None]
        strengths = grad[np.clip(ys, 1, h - 2), np.arange(len(ts))]
        best = np.argmax(strengths, axis=0)
        points = ys[best, np.arange(len(ts))].astype(float)
        good = (strengths[best, np.arange(len(ts))] > threshold) & (points >= 1)
        for _ in range(3):
            if good.sum() < len(ts) * 0.45:
                break
            slope, offset = np.polyfit(tx[good], points[good], 1)
            residuals = np.abs(points - (offset + slope * tx))
            good &= residuals <= 2.0
        if good.mean() < 0.5 or abs(slope) > np.tan(np.radians(8)):
            continue
        # A local subject edge must not pass by only occupying one end of the frame.
        if min(g.mean() for g in np.array_split(good, 4)) < 0.25:
            continue
        boundary = offset + slope * tx
        if np.percentile(boundary, 10) < 1 or np.max(boundary) > limit:
            continue
        # Sample several depths OUTSIDE the candidate. Across-edge consistency is
        # robust to dust, film markings and occasional sprocket holes (IQR).
        depths = np.linspace(0.08, 0.85, 9)[:, None] * np.maximum(boundary - 2, 0)
        exterior = smooth[np.rint(depths).astype(int), np.arange(len(ts))]
        spread = np.max(np.percentile(exterior, 75, axis=1) -
                        np.percentile(exterior, 25, axis=1), axis=1)
        uniformity = float(np.median(spread))
        if uniformity > (0.04 if soft else 0.12):
            continue
        if soft:
            # A median/IQR alone can hide minority leaves, buildings or a horizon
            # in the outside band. Do not erase that content to chase a weak edge.
            flat = exterior.reshape(-1, exterior.shape[-1])
            if np.max(np.percentile(flat, 90, axis=0) - np.percentile(flat, 10, axis=0)) > .08:
                continue
        # Wide trims require particularly consistent outside regions.
        if offset > h * 0.08:
            # A wide holder is flat through its depth as well as along its edge.
            # Smooth roads/skies with a gradient must not become huge crop bands.
            flat = exterior.reshape(-1, exterior.shape[-1])
            if np.max(np.percentile(flat, 90, axis=0) -
                      np.percentile(flat, 10, axis=0)) > 0.08:
                continue
        # Reject the holder-to-base boundary when the next band is still empty:
        # the crop belongs at base-to-image, even if that transition is weaker.
        inner_y = np.clip(np.rint(boundary[None, :] + np.array([2, 4, 6])[:, None]),
                          0, h - 1).astype(int)
        interior = smooth[inner_y, np.arange(len(ts))]
        inside_spread = np.max(np.percentile(interior, 75, axis=1) -
                               np.percentile(interior, 25, axis=1), axis=1)
        if soft and np.max(inside_spread) < max(.018, uniformity * 1.25):
            continue
        if np.max(inside_spread) < 0.018:
            # Textureless dark sky behind bright film base is still a frame.
            # A uniform bright band behind a dark holder is usually more base.
            if offset > h * 0.06 or np.median(interior) >= np.median(exterior) - 0.03:
                continue
        if soft:
            # A film-base transition has a common polarity across the frame.
            # Texture/noise ridges oscillate in sign and must not become a crop.
            reach = max(3, round(h * .005))
            outer = smooth[np.clip(np.rint(boundary - reach).astype(int), 0, h - 1), np.arange(len(ts))].mean(axis=1)
            inner = smooth[np.clip(np.rint(boundary + reach).astype(int), 0, h - 1), np.arange(len(ts))].mean(axis=1)
            delta = inner - outer
            signed = delta * np.sign(np.median(delta))
            exterior_noise = float(np.median(np.std(exterior, axis=0)))
            if np.mean(signed > 0) < .75 or abs(float(np.median(delta))) < max(.002, 2.5 * exterior_noise):
                continue
        residual = float(np.percentile(np.abs(points[good] - boundary[good]), 95))
        confidence = float(good.mean() * max(0, 1 - uniformity / 0.24))
        if offset > h * .08 and confidence < .92:
            continue
        accepted.append((confidence, offset, slope, residual))
    if not accepted:
        return None
    # Favor the strongest supported boundary; avoid walking deep into the subject
    # when a comparably well-supported exterior boundary already exists.
    best_conf = max(v[0] for v in accepted)
    viable = [v for v in accepted if v[0] >= max(0.45 if soft else 0.50, best_conf * 0.85)]
    if not viable:
        return None
    confidence, offset, slope, residual = min(viable, key=lambda v: v[1])
    return dict(offset=offset, slope=slope, residual=residual,
                confidence=round(min(confidence, .54) if soft else confidence, 3), center=center,
                method='soft-border' if soft else 'contrast-edge')


def detect_film_frame(lin_oriented):
    """Detect four physical borders independently; never invent a fallback crop.

    rect is an axis-aligned rectangle inside the detected lines. Unknown sides
    keep their full extent. The original detect_film_rect API wraps this result.
    """
    full = dict(rect=[0.0, 0.0, 1.0, 1.0], confidence=0.0,
                detected_edges=0, status="uncertain", edges={}, analysis_shape=list(np.shape(lin_oriented)[:2]))
    try:
        a = _film_edge_image(lin_oriented)
    except (ValueError, TypeError):
        return full
    h, w = a.shape[:2]
    edges = dict(top=_detect_outer_edge(a), bottom=_detect_outer_edge(a[::-1]),
                 left=_detect_outer_edge(a.transpose(1, 0, 2)),
                 right=_detect_outer_edge(a[:, ::-1].transpose(1, 0, 2)))
    # Weak-edge recovery requires independent physical-frame evidence. It never
    # discovers a frame in a borderless scene and never determines leveling.
    strong_angles = [(1 if name in ('top', 'right') else -1) * np.degrees(np.arctan(edge['slope']))
                     for name, edge in edges.items() if edge is not None and edge['confidence'] >= .75]
    if strong_angles:
        views = dict(top=a, bottom=a[::-1], left=a.transpose(1, 0, 2), right=a[:, ::-1].transpose(1, 0, 2))
        for name, view in views.items():
            if edges[name] is not None:
                continue
            edge = _detect_outer_edge(view, soft=True)
            if edge is not None:
                angle = (1 if name in ('top', 'right') else -1) * np.degrees(np.arctan(edge['slope']))
                if min(abs(angle - reference) for reference in strong_angles) <= 1.0:
                    edges[name] = edge
    # Stay inside even tilted borders. The margin is tied to fit uncertainty,
    # not to a fixed percentage of the photograph.
    def inset(edge, span):
        if edge is None:
            return 0.0
        endpoints = [edge['offset'] + edge['slope'] * (t - edge['center'])
                     for t in (0, span - 1)]
        return max(0, max(endpoints) + 1.0 + edge['residual'])
    rect = [inset(edges['left'], h) / w, inset(edges['top'], w) / h,
            1 - inset(edges['right'], h) / w, 1 - inset(edges['bottom'], w) / h]
    if rect[2] - rect[0] < 0.3 or rect[3] - rect[1] < 0.3:
        return full
    found = [e for e in edges.values() if e is not None]
    return dict(analysis_shape=[h, w], rect=[round(float(v), 5) for v in rect],
                confidence=round(float(np.mean([e['confidence'] for e in found])), 3) if found else 0.0,
                detected_edges=len(found), status="detected" if len(found) == 4 else
                "partial" if found else "uncertain", edges=edges)


def detect_film_rect(lin_oriented):
    """Return normalized crop coordinates; uncertain sides retain the full image."""
    return detect_film_frame(lin_oriented)['rect']


def _robust_slope(x, y, max_tan, iters=240, thresh=1.5):
    """RANSAC + 总体最小二乘(TLS)拟合直线斜率（借鉴 darktable ashift 的做法）：
    随机取两点定线、统计内点，取内点最多的模型，再对内点用 SVD 精修方向。
    比普通最小二乘更抗齿孔/灰尘/片边文字/漏光等离群点。
    内点太少或斜率超过 max_tan（角度过大，多半误检）则返回 None。"""
    n = len(x)
    if n < 12:
        return None
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    rng = np.random.default_rng(12345)   # 固定种子：同一张图结果可复现
    best_inl = None
    for _ in range(iters):
        i = int(rng.integers(n)); j = int(rng.integers(n))
        if x[i] == x[j]:
            continue
        m = (y[j] - y[i]) / (x[j] - x[i])
        b = y[i] - m * x[i]
        d = np.abs(y - (m * x + b)) / np.hypot(m, 1.0)   # 到直线的垂直距离
        inl = d < thresh
        if best_inl is None or int(inl.sum()) > int(best_inl.sum()):
            best_inl = inl
    if best_inl is None or int(best_inl.sum()) < max(12, int(0.35 * n)):
        return None
    P = np.column_stack([x[best_inl], y[best_inl]])
    P = P - P.mean(axis=0)
    _, _, Vt = np.linalg.svd(P, full_matrices=False)
    dx, dy = Vt[0]
    if abs(dx) < 1e-9:
        return None
    m = dy / dx
    if abs(m) > max_tan:
        return None
    return float(m)


def _frame_level(frame, max_angle=8.0):
    """Consensus of measured frame edges; returns None when angle is unknown."""
    candidates = []
    for name, edge in frame['edges'].items():
        if edge is not None and edge['confidence'] >= 0.55:
            sign = 1 if name in ('top', 'right') else -1
            angle = sign * np.degrees(np.arctan(edge['slope']))
            candidates.append((float(angle), edge['confidence'], name))
    if len(candidates) < 2:
        return None
    # Two adjacent edges can agree accidentally on a bent film edge or subject.
    # Require an opposite pair or three agreeing borders before replacing a manual angle.
    groups = []
    for angle, _, _ in candidates:
        group = [v for v in candidates if abs(v[0] - angle) <= 0.25]
        names = {v[2] for v in group}
        opposite = {'top', 'bottom'} <= names or {'left', 'right'} <= names
        if opposite or len(group) >= 3:
            groups.append((sum(v[1] for v in group) + (0.35 if opposite else 0), group))
    if not groups:
        return None
    group = max(groups, key=lambda v: v[0])[1]
    angle = float(np.average([v[0] for v in group], weights=[v[1] for v in group]))
    if abs(angle) > max_angle:
        return None
    return round(angle, 2) if abs(angle) >= 0.08 else 0.0


def _aligned_frame_rect(frame, angle):
    """Transform frame half-planes, then inscribe a safe axis-aligned rectangle.

    Include the original sensor bounds so rotation can never introduce black
    corners. All calculations use image-edge coordinates (PIL's rotation center).
    No second edge detection on an interpolated/rotated image is needed.
    """
    h, w = frame['analysis_shape']
    center = np.array([w / 2, h / 2])
    rad = np.radians(angle)
    rotation = np.array([[np.cos(rad), np.sin(rad)], [-np.sin(rad), np.cos(rad)]])
    planes = [(np.array([1., 0.]), 0.), (np.array([-1., 0.]), -float(w)),
              (np.array([0., 1.]), 0.), (np.array([0., -1.]), -float(h))]
    for name, edge in frame['edges'].items():
        if edge is None:
            continue
        m = edge['slope']
        # Narrow clean-up margin, sized in analysis pixels plus fit uncertainty.
        margin = 1.0 + edge['residual'] + min(h, w) * 0.002
        b = edge['offset'] + .5 - m * (edge['center'] + .5) + margin
        if name == 'top':
            n = np.array([-m, 1.])
        elif name == 'bottom':
            n = np.array([-m, -1.]); b -= h
        elif name == 'left':
            n = np.array([1., -m])
        else:
            n = np.array([-1., -m]); b -= w
        planes.append((n, b))
    transformed = [(rotation @ n, b + (rotation @ n - n) @ center) for n, b in planes]
    # Near-horizontal/vertical boundaries yield monotone inward updates.
    rect = np.array([0., 0., float(w), float(h)])
    for _ in range(24):
        previous = rect.copy()
        for n, b in transformed:
            nx, ny = n
            if abs(nx) >= abs(ny):
                y = rect[1] if ny >= 0 else rect[3]
                value = (b - ny * y) / nx
                if nx > 0:
                    rect[0] = max(rect[0], value)
                else:
                    rect[2] = min(rect[2], value)
            else:
                x = rect[0] if nx >= 0 else rect[2]
                value = (b - nx * x) / ny
                if ny > 0:
                    rect[1] = max(rect[1], value)
                else:
                    rect[3] = min(rect[3], value)
        if np.max(np.abs(rect - previous)) < 1e-5:
            break
    rect /= np.array([w, h, w, h])
    if rect[2] - rect[0] < .3 or rect[3] - rect[1] < .3:
        return None
    # Round inward, not toward a potentially invalid pixel beyond the boundary.
    rect[:2] = np.ceil(rect[:2] * 1e6) / 1e6
    rect[2:] = np.floor(rect[2:] * 1e6) / 1e6
    return rect.tolist()


def detect_film_alignment(lin_oriented, current_angle=0.0, auto_level=True, reference=None):
    """Joint crop/level from the original image; current angle is an absolute angle.

    Repeated Auto clicks are idempotent. If angle evidence is insufficient, keep
    the user's existing angle and still crop any reliable boundaries.
    """
    def diagnostics(result):
        # Confidence must describe the edges still used after angle-consistency
        # filtering, not the stronger edges we discarded as probable subjects.
        found = [e for e in result.get('edges', {}).values() if e is not None]
        count = len(found)
        mean = float(np.mean([e['confidence'] for e in found])) if found else 0.0
        evidence = mean * count / 4 if result['status'] != 'uncertain' else 0.0
        warnings = []
        if count < 4:
            warnings.append(f"仅实测到 {count} 条片边，请复核其余方向的裁切范围。")
        if result.get('reference_edges'):
            warnings.append("部分边界来自同卷手动参考，不是本张实测结果。")
        if result.get('angle_status') == 'reference':
            warnings.append("校平角来自同卷手动参考，请检查翻拍机位是否一致。")
        elif auto_level and result.get('angle_status') == 'preserved':
            warnings.append("片边角度证据不足，已保留当前校平角。")
        result.update(confidence=round(mean, 3), detected_edges=count,
                      geometry_confidence=round(evidence, 3),
                      confidence_label='high' if evidence >= .8 else
                      'medium' if evidence >= .45 else 'low' if evidence > 0 else 'none',
                      edge_coverage=round(count / 4, 2), warnings=warnings)
        return result

    frame = detect_film_frame(lin_oriented)
    # A moved copy stand / different framing must not borrow an unrelated crop.
    if reference is not None:
        measured = _aligned_frame_rect(frame, float(current_angle))
        conflicts = [i for i, name in enumerate(('left', 'top', 'right', 'bottom'))
                     if frame['edges'].get(name) is not None
                     and frame['edges'][name]['confidence'] >= .75
                     and measured is not None and abs(measured[i] - reference['rect'][i]) > .05]
        if conflicts:
            reference = None
    estimated = _frame_level(frame) if auto_level else None
    angle = float(current_angle) if estimated is None else estimated
    borrowed_angle = False
    if (estimated is None and auto_level and abs(current_angle) < 0.01 and
            reference is not None and reference.get('angle') is not None):
        angle = float(reference['angle'])
        borrowed_angle = True
    result = dict(frame, angle=round(angle, 2), leveled=estimated is not None,
                  angle_status='detected' if estimated is not None else 'preserved')
    if frame['status'] == 'uncertain' and reference is None:
        result.update(angle=float(current_angle), leveled=False, angle_status='preserved')
        return diagnostics(result)
    if borrowed_angle:
        result.update(angle_status='reference', leveled=True)
    # A deep edge inconsistent with the rest is probably a road/horizon.
    consistency_angle = estimated
    if consistency_angle is None and reference is not None:
        consistency_angle = reference.get('angle')
    if consistency_angle is not None:
        for name, edge in frame['edges'].items():
            if edge is None:
                continue
            sign = 1 if name in ('top', 'right') else -1
            edge_angle = sign * np.degrees(np.arctan(edge['slope']))
            if abs(edge_angle - consistency_angle) > 1.2:
                result['edges'] = dict(result['edges'])
                result['edges'][name] = None
    rect = _aligned_frame_rect(result, angle)
    if rect is None:
        result.update(rect=[0., 0., 1., 1.], status='uncertain',
                      angle=float(current_angle), leveled=False, angle_status='preserved')
    else:
        reference_edges = []
        if reference is not None:
            for i, name in enumerate(('left', 'top', 'right', 'bottom')):
                if result['edges'].get(name) is None and name in reference.get('stable_edges', ('left', 'top', 'right', 'bottom')):
                    value = reference['rect'][i]
                    rect[i] = max(rect[i], value) if i < 2 else min(rect[i], value)
                    reference_edges.append(name)
        count = sum(e is not None for e in result['edges'].values())
        result.update(rect=rect, detected_edges=count,
                      reference_edges=reference_edges,
                      reference_samples=reference['samples'] if reference_edges or borrowed_angle else 0,
                      status='referenced' if reference_edges else 'detected' if count == 4 else 'partial')
    return diagnostics(result)


def estimate_skew(lin, max_angle=8.0):
    """Return the absolute leveling angle, or zero when evidence is insufficient."""
    angle = _frame_level(detect_film_frame(lin), max_angle)
    return 0.0 if angle is None else angle


def _deskew_lin(lin, angle):
    """按 angle（度，正=逆时针）旋转线性图；每通道用 PIL 'F' 模式保精度，
    expand=False 保持画幅（旋转带入的黑角随后由裁切内缩去掉）。"""
    if abs(angle) < 0.0001:
        return lin
    out = [np.asarray(Image.fromarray(np.ascontiguousarray(lin[..., c]), mode="F")
                      .rotate(angle, resample=Image.BILINEAR, expand=False))
           for c in range(3)]
    return np.ascontiguousarray(np.stack(out, axis=-1))


def _safe_inset_rect(shape, angle):
    """旋转 angle 后能避开黑角的最大居中矩形，返回 [x0,y0,x1,y1]（0~1）。
    旋转产生的黑区只在四角，所以对称向内收，直到矩形四角都落在有效区即可。"""
    h, w = shape[:2]
    if abs(angle) < .0001:
        return [0., 0., 1., 1.]
    theta = np.radians(abs(angle))
    c, s = abs(np.cos(theta)), abs(np.sin(theta))
    # Analytic same-aspect inscribed rectangle; preserve sub-degree precision.
    # Leave one source pixel for bilinear interpolation instead of rounding to 0.5% bands.
    scale = min((w - 2) / (w*c + h*s), (h - 2) / (w*s + h*c))
    if scale <= 0:
        return None
    inset = (1 - min(1, scale)) / 2
    return [inset, inset, 1-inset, 1-inset]


def _rect_intersect(a, b):
    """两个 [x0,y0,x1,y1] 归一化矩形取交集；退化时退回 b（安全框）。"""
    if a is None:
        return b
    x0 = max(a[0], b[0]); y0 = max(a[1], b[1])
    x1 = min(a[2], b[2]); y1 = min(a[3], b[3])
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:
        return b
    return [x0, y0, x1, y1]


def orient_image(lin, rotate=0, flip="none"):
    """按 rotate/flip 调整图像方向（与 crop_rect 的坐标系一致）。

    rotate 是「顺时针」角度（与 CLI --rotate、界面「右转」一致）；
    np.rot90 的正 k 是逆时针，所以这里取负。
    """
    if rotate:
        lin = np.rot90(lin, k=-(rotate // 90) % 4, axes=(0, 1))
    if flip == "h":
        lin = lin[:, ::-1]
    elif flip == "v":
        lin = lin[::-1, :]
    return np.ascontiguousarray(lin)


# --------------------------------------------------------------------------- #
# 核心：去色罩 + 反转
# --------------------------------------------------------------------------- #
def stats_view(lin, max_side=1000):
    """为求百分位做的下采样视图，避免在超大图上算得太慢。"""
    h, w = lin.shape[:2]
    scale = max(h, w) / max_side
    if scale <= 1:
        return lin
    step = int(np.ceil(scale))
    return lin[::step, ::step]


def _rect_px(rect, w, h):
    """把 [x0,y0,x1,y1]（0~1 比例）换成像素整数，做好边界与顺序保护。"""
    x0, y0, x1, y1 = rect
    xa, xb = sorted((int(round(w * x0)), int(round(w * x1))))
    ya, yb = sorted((int(round(h * y0)), int(round(h * y1))))
    xa = max(0, min(xa, w - 2)); xb = max(xa + 2, min(xb, w))
    ya = max(0, min(ya, h - 2)); yb = max(ya + 2, min(yb, h))
    return xa, ya, xb, yb


def _tone_curve(P, gamma, contrast):
    """影调：gamma（提亮中间调）+ 对比度 S 曲线（与旧版逻辑一致）。"""
    if gamma and abs(gamma - 1.0) > 1e-3:
        P = np.power(P, 1.0 / gamma)
    if contrast and abs(contrast) > 1e-3:
        # 以 0.5 为中心的平滑 S 曲线
        k = float(contrast)
        P = np.clip(0.5 + (P - 0.5) * (1 + k) -
                    k * (P - 0.5) ** 3 * 4, 0.0, 1.0) if k > 0 else \
            np.clip(0.5 + (P - 0.5) * (1 + k), 0.0, 1.0)
    return P


def negadoctor(lin, dmin, args, stats_lin=None):
    """darktable negadoctor 负转正（逐通道），比线性密度拉伸更"胶片化"：
    密度相对片基 Dmin 取对数、D_max 定反差、相纸 gamma、外加高光指数柔化(soft-clip)。

    darktable 的默认参数假定扫描件已归一化到片基≈1、且密度范围完整；翻拍负片往往偏暗、
    动态范围压缩，直接套会一片死黑。因此这里在保持公式结构的前提下做标量自动曝光：
    让最亮的场景（负片最密处）映到接近白，三个通道共用曝光系数。
    nd_exposure 作为全局亮度增益微调（默认 1.0），nd_gamma 控制反差。"""
    THR = 2.3283e-10
    Dmax = float(getattr(args, "nd_dmax", 2.046))
    offset = float(getattr(args, "nd_offset", -0.05))
    black = float(getattr(args, "nd_black", 0.0755))
    gamma = float(getattr(args, "nd_gamma", 4.0))
    softclip = float(getattr(args, "nd_softclip", 0.75))
    gain = float(getattr(args, "nd_exposure", 1.0))
    if not np.isfinite([Dmax, offset, black, gamma, softclip, gain]).all():
        raise ValueError("negadoctor 参数必须是有限数")
    if Dmax <= 0 or gamma <= 0 or gain < 0 or not 0 <= softclip <= 1:
        raise ValueError("negadoctor 需要 Dmax/gamma > 0、exposure >= 0、softclip 在 0~1")
    dmin = np.asarray(dmin, dtype=np.float32).reshape(1, 1, 3)
    if not np.isfinite(dmin).all():
        raise ValueError("片基取样无效，请重新选择有效区域")
    dmin = np.maximum(dmin, THR)
    x = np.maximum(lin.astype(np.float32), THR)
    log_density = np.log10(x / dmin)                      # 相对片基的密度（逐通道）
    corrected = log_density / Dmax + offset               # wb_high=wb_low=1
    # float64 also covers the documented Dmax=0.1 / offset=1 range.
    ten = np.power(10.0, np.clip(corrected.astype(np.float64), -300, 300))
    # 标量自动曝光：按亮度取最亮场景（负片最密处）映到接近印相白点；
    # 用同一系数缩放三通道，不动色彩平衡（残留偏色交给后面的灰世界白平衡）。
    if stats_lin is None:
        view = stats_view(ten).reshape(-1, 3)
    else:
        stats_density = np.log10(np.maximum(stats_lin, THR) / dmin)
        stats_corrected = stats_density / Dmax + offset
        view = np.power(10.0, np.clip(stats_corrected.astype(np.float64), -300, 300)).reshape(-1, 3)
    ten_lo = float(np.percentile(view @ np.array([0.299, 0.587, 0.114],
                                                 dtype=view.dtype), 0.5))
    auto_exp = 1.0 / max(1.0 + black - ten_lo, 1e-3)
    exp = auto_exp * gain
    print_lin = np.maximum(exp * (1.0 + black - ten), 0.0)
    # Values far above white are indistinguishable after highlight compression.
    pg = np.power(np.minimum(print_lin, 100.0), min(gamma, 100.0))
    scc = max(1.0 - softclip, 1e-4)
    out = np.where(pg > softclip,
                   softclip - np.expm1(-np.maximum(pg - softclip, 0.0) / scc) * scc,
                   pg)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def convert_base(lin, args):
    """管线前半（重活）：方向 → 裁切 → (按 mode 反转/拉伸)
    → 白平衡(取样点优先于灰世界) → 色温/色调
    → [直方图匹配] 或 [gamma → 对比度]。

    返回 (P, vin_rect)：P 是 0~1 显示值，vin_rect 是晕影的参照矩形
    （预览「整幅显示+裁切框」时=裁切框，其余=None）。
    界面把这半段的结果按参数缓存起来，拖 LR 精调滑杆时只重算后半段
    （参考 darktable pixelpipe 的分阶段缓存思路）。
    """
    eps = 1e-5
    mode = getattr(args, "mode", "color")  # color / bw / positive

    # 1) 方向先做（旋转/镜像）——这样裁切坐标就是最终显示方向，所见即所裁
    lin = orient_image(lin, getattr(args, "rotate", 0),
                       getattr(args, "flip", "none"))

    # 1.5) 自动校平：按 level_angle 去斜。旋转会带入黑角，没有显式裁切框时
    #      用 _safe_inset_rect 算出避开黑角的最大矩形当裁切框。
    _lvl = float(getattr(args, "level_angle", 0.0) or 0.0)
    _safe_rect = None
    if abs(_lvl) >= 0.0001:
        lin = _deskew_lin(lin, _lvl)
        # 非「整幅预览」时算安全内缩框；下面裁切框会和它取交集，任意角度都不出黑角
        if not getattr(args, "stats_rect", None):
            _safe_rect = _safe_inset_rect(lin.shape[:2], _lvl)

    # Film base usually lies outside the final crop. Sampling must retain the
    # oriented, leveled full image rather than clamp a removed border onto the
    # nearest image pixel (which previously produced a false base measurement).
    sample_source = lin

    # 2) 裁切
    #    crop_rect: 任意位置矩形裁切（会真正裁掉，用于导出/最终结果）
    #    stats_rect: 只把这块区域用于算色阶/白平衡，但输出仍是整幅（预览定位裁切框用）
    #    crop: 老的居中比例裁切（向后兼容）
    crop_rect = getattr(args, "crop_rect", None)
    if _safe_rect is not None:               # 去斜后：用户裁切框与安全框取交集去黑角
        crop_rect = _rect_intersect(crop_rect, _safe_rect)
    stats_rect = getattr(args, "stats_rect", None)
    h, w = lin.shape[:2]
    off_x, off_y = 0, 0  # 裁切偏移，用于把 wb_point 换算到裁切后坐标

    if crop_rect:
        xa, ya, xb, yb = _rect_px(crop_rect, w, h)
        lin = lin[ya:yb, xa:xb]
        off_x, off_y = xa, ya
        stats_lin = lin
    elif getattr(args, "crop", 0) and not stats_rect:
        cy, cx = int(h * args.crop), int(w * args.crop)
        if h - 2 * cy > 4 and w - 2 * cx > 4:
            lin = lin[cy:h - cy, cx:w - cx]
            off_x, off_y = cx, cy
        stats_lin = lin
    elif stats_rect:
        xa, ya, xb, yb = _rect_px(stats_rect, w, h)
        stats_lin = lin[ya:yb, xa:xb]
    else:
        stats_lin = lin

    # 晕影参照矩形：预览（整幅显示+裁切框）时以裁切框为画面，导出/CLI 用整幅
    vin_rect = stats_rect if (stats_rect and not crop_rect) else None

    # 白点取样坐标：0~1 比例，基于「方向调整后的整幅图」（与 crop_rect 同一坐标系），
    # 这里换算成裁切后图像里的像素坐标。新版 UI 传 wb_rect，旧参数可继续传 wb_point。
    wb_rect = getattr(args, "wb_rect", None)
    wb_point = getattr(args, "wb_point", None)
    wb_sample_rect = None
    wb_px = None
    if wb_rect is not None and mode != "bw":
        if isinstance(wb_rect, dict):
            x0, y0, x1, y1 = (wb_rect.get("x0"), wb_rect.get("y0"),
                              wb_rect.get("x1"), wb_rect.get("y1"))
        else:
            x0, y0, x1, y1 = wb_rect
        x0, y0, x1, y1 = [float(v) for v in (x0, y0, x1, y1)]
        xa = int(round(min(x0, x1) * w)) - off_x
        xb = int(round(max(x0, x1) * w)) - off_x
        ya = int(round(min(y0, y1) * h)) - off_y
        yb = int(round(max(y0, y1) * h)) - off_y
        wb_sample_rect = (xa, ya, xb, yb)
    elif wb_point is not None and mode != "bw":
        wb_px = (int(round(float(wb_point[0]) * w)) - off_x,
                 int(round(float(wb_point[1]) * h)) - off_y)

    # darktable negadoctor 式引导取样（都可选，缺省走自动流程）：
    #   film_base_rect 片基 → 去色罩锚点；shadow_rect 暗部 → 黑点；
    #   highlight_rect 亮部 → 白点。坐标同 wb_rect（方向调整后整幅 0~1 比例）。
    def _sample_lin_median(rect):
        if rect is None:
            return None
        if isinstance(rect, dict):
            x0, y0, x1, y1 = (rect.get("x0"), rect.get("y0"),
                              rect.get("x1"), rect.get("y1"))
        else:
            x0, y0, x1, y1 = rect
        x0, y0, x1, y1 = [float(v) for v in (x0, y0, x1, y1)]
        xa = int(round(min(x0, x1) * w))
        xb = int(round(max(x0, x1) * w))
        ya = int(round(min(y0, y1) * h))
        yb = int(round(max(y0, y1) * h))
        hh2, ww2 = sample_source.shape[:2]
        xa = max(0, min(xa, ww2 - 1)); xb = max(xa + 1, min(xb, ww2))
        ya = max(0, min(ya, hh2 - 1)); yb = max(ya + 1, min(yb, hh2))
        return np.median(np.clip(sample_source[ya:yb, xa:xb], eps, 1.0)
                         .reshape(-1, 3), axis=0)

    _fb = _sample_lin_median(getattr(args, "film_base_rect", None))
    _sh = _sample_lin_median(getattr(args, "shadow_rect", None))
    _hl = _sample_lin_median(getattr(args, "highlight_rect", None))
    film_base_density = None if _fb is None else -np.log10(_fb)
    shadow_density = None if _sh is None else -np.log10(_sh)
    highlight_density = None if _hl is None else -np.log10(_hl)

    use_margin = (getattr(args, "margin", 0) > 0
                  and not crop_rect and not stats_rect)

    def _trim_margin(V):
        # 只用中心区域统计，避开片基边框 / 漏光（仅在没有裁切/统计矩形时）
        if not use_margin:
            return V
        hh, ww = V.shape[:2]
        m = args.margin
        y0, y1 = int(hh * m), int(hh * (1 - m))
        x0, x1 = int(ww * m), int(ww * (1 - m))
        if y1 > y0 and x1 > x0:
            return V[y0:y1, x0:x1]
        return V

    black_pct = getattr(args, "black_pct", 0.5)
    white_pct = getattr(args, "white_pct", 99.7)

    # 3) 按 mode 做反转 / 拉伸
    if mode == "bw":
        # 黑白负片：用线性亮度算密度 D=-log10(luma)，单通道黑白点归一，
        # 输出 R=G=B。跳过 白平衡/temp/tint/饱和度/色度降噪/直方图匹配。
        Wl = LUMA_W.astype(lin.dtype)
        luma = np.clip(lin @ Wl, eps, 1.0)
        D1 = -np.log10(luma)
        Dv = _trim_margin(-np.log10(
            np.clip(stats_view(stats_lin) @ Wl, eps, 1.0)))
        bp = np.percentile(Dv, black_pct)
        wp = np.percentile(Dv, white_pct)
        if wp - bp < 1e-6:
            wp = bp + 1e-6
        P1 = np.clip((D1 - bp) / (wp - bp), 0.0, 1.0)
        P1 = _tone_curve(P1, getattr(args, "gamma", 1.8),
                         getattr(args, "contrast", 0.08))
        P = np.clip(np.stack([P1] * 3, axis=-1), 0.0, 1.0)
        return P, vin_rect  # 后续 LR 精调/锐化/晕影在 apply_finishing 里做

    if mode == "positive":
        # 正片（E-6/幻灯片）：不做密度反转。用亮度的黑白点做统一线性拉伸
        # （三通道同一系数，保留原片色彩），其余影调管线照常。
        Wl = LUMA_W.astype(lin.dtype)
        lv = _trim_margin(np.clip(stats_view(stats_lin), 0.0, 1.0)) @ Wl
        bp = float(np.percentile(lv, black_pct))
        wp = float(np.percentile(lv, white_pct))
        if wp - bp < 1e-6:
            wp = bp + 1e-6
        P = np.clip((lin - bp) / (wp - bp), 0.0, 1.0)
    elif getattr(args, "negadoctor", False):
        # 彩色负片 · negadoctor 引擎（可选）：先定每通道片基 Dmin，再套 darktable 公式
        N = np.clip(lin, eps, 1.0)
        if film_base_density is not None:           # 片基取样最准
            dmin = np.power(10.0, -film_base_density)
        elif getattr(args, "base_rect", None):
            x, y, bw, bh = args.base_rect
            dmin = np.median(np.clip(lin[y:y + bh, x:x + bw], eps, 1.0)
                             .reshape(-1, 3), axis=0)
        else:                                       # 自动：片基≈负片最亮（高百分位）
            Vv = _trim_margin(np.clip(stats_view(stats_lin), eps, 1.0))
            dmin = np.percentile(Vv.reshape(-1, 3), 99.5, axis=0)
        P = negadoctor(N, dmin, args,
                       stats_lin=_trim_margin(np.clip(stats_view(stats_lin), eps, 1.0)))
    else:
        # 彩色负片：密度空间去色罩 + 反转（原有算法，保持不变）
        N = np.clip(lin, eps, 1.0)
        D = -np.log10(N)  # 密度，>=0；场景越亮 D 越大

        Dv = _trim_margin(-np.log10(
            np.clip(stats_view(stats_lin), eps, 1.0)))  # 下采样统计用

        P = np.empty_like(D)
        base_density = None
        if getattr(args, "base_rect", None):
            # 老参数：像素坐标片基矩形（橙色片基，无影像区）锚定色罩黑点
            x, y, bw, bh = args.base_rect
            patch = np.clip(lin[y:y + bh, x:x + bw], eps, 1.0)
            base_lin = np.median(patch.reshape(-1, 3), axis=0)
            base_density = -np.log10(base_lin)  # 每通道片基密度 = 黑点

        # 黑点优先级：暗部取样 > 片基取样(新/老) > 自动百分位
        # 白点优先级：亮部取样 > 自动百分位
        for c in range(3):
            Dc = D[..., c]
            col = Dv[..., c].reshape(-1)
            if shadow_density is not None:
                bp = shadow_density[c]
            elif film_base_density is not None:
                bp = film_base_density[c]
            elif base_density is not None:
                bp = base_density[c]
            else:
                bp = np.percentile(col, black_pct)
            if highlight_density is not None:
                wp = highlight_density[c]
            else:
                wp = np.percentile(col, white_pct)
            if wp < bp:            # 取样反了也不崩坏：黑白点自动摆正
                bp, wp = wp, bp
            if wp - bp < 1e-6:
                wp = bp + 1e-6
            P[..., c] = (Dc - bp) / (wp - bp)

        P = np.clip(P, 0.0, 1.0)

    # 4) 白平衡：框选/取样点优先于灰世界
    if wb_sample_rect is not None:
        P = wb_from_sample(P, rect=wb_sample_rect)
    elif wb_px is not None:
        P = wb_from_point(P, wb_px[0], wb_px[1])

    if getattr(args, "_ref_cdfs", None) is not None:
        # 有参照图：直接做直方图匹配，转移参照的色调与色彩
        # （覆盖手动色调；temp/tint 与灰世界白平衡在此模式下跳过）
        P = hist_match(P, args._ref_centers, args._ref_cdfs)
    else:
        # 灰世界白平衡（在已反转的正片上做，去掉残留偏色）
        # 只用「中间调」像素估计：排除接近黑的片基/边框和过曝高光，更稳健
        if wb_sample_rect is None and wb_px is None and getattr(args, "wb", "gray") == "gray":
            wb_stats = P
            if stats_rect and not crop_rect:
                xa, ya, xb, yb = _rect_px(stats_rect, w, h)
                wb_stats = P[ya:yb, xa:xb]
            flat = _trim_margin(wb_stats).reshape(-1, 3)
            lum = flat @ np.array([0.299, 0.587, 0.114], dtype=flat.dtype)
            mask = (lum > 0.15) & (lum < 0.9)
            sample = flat[mask] if mask.sum() > 0.02 * len(flat) else flat
            mean = sample.mean(axis=0)
            g = mean.mean()
            scale = np.clip(g / np.clip(mean, 1e-4, None), 0.5, 2.0)
            P = np.clip(P * scale, 0.0, 1.0)

        # 5) 色温/色调（通道乘法，match 模式下跳过）
        P = apply_temp_tint(P, getattr(args, "temp", 0.0),
                            getattr(args, "tint", 0.0))

        # 6) 影调：gamma + 对比度 S 曲线（negadoctor 自带相纸 gamma/柔化，故跳过）
        if mode == "positive" or not getattr(args, "negadoctor", False):
            P = _tone_curve(P, getattr(args, "gamma", 1.8),
                            getattr(args, "contrast", 0.08))

    return np.clip(P, 0.0, 1.0), vin_rect


def apply_finishing(P, args, vin_rect=None):
    """管线后半（轻活，LR 精调）：曝光/高光阴影/白黑场 → 曲线
    → HSL/鲜艳度 → 饱和度 → 锐化 → 色度降噪 → 晕影。

    输入是 convert_base 的输出（或其缓存），全程不改写传入数组，
    所以缓存的 base 可以反复复用。黑白模式跳过 单通道曲线/HSL/
    饱和度/色度降噪（与旧版行为一致）。
    """
    mode = getattr(args, "mode", "color")
    P = tone_adjust(P,
                    getattr(args, "exposure", 0.0),
                    getattr(args, "highlights", 0.0),
                    getattr(args, "shadows", 0.0),
                    getattr(args, "whites", 0.0),
                    getattr(args, "blacks", 0.0))
    if mode == "bw":
        # 黑白只吃主曲线（单通道曲线会给黑白上色）
        P = apply_curves(P, getattr(args, "curve", None))
    else:
        P = apply_curves(P,
                         getattr(args, "curve", None),
                         getattr(args, "curve_r", None),
                         getattr(args, "curve_g", None),
                         getattr(args, "curve_b", None))
        P = hsl_adjust(P, getattr(args, "hsl", None),
                       getattr(args, "vibrance", 0.0))
        P = saturation_adjust(P, getattr(args, "saturation", 1.0))

    P = np.clip(P, 0.0, 1.0)

    # 锐化：只锐化亮度，不碰色度
    P = unsharp_luma(P, getattr(args, "sharpen", 0.0),
                     getattr(args, "sharpen_radius", 2.0))

    # 色度降噪：去掉反转放大出来的彩色颗粒（黑白无色度，跳过）
    if mode != "bw" and getattr(args, "denoise", 0) > 0:
        P = chroma_denoise(P, int(args.denoise))

    # 晕影（最后做）：预览时以裁切框为画面中心，与导出裁切后一致
    P = apply_vignette(P, getattr(args, "vignette", 0.0), vin_rect)

    return np.ascontiguousarray(P)


def convert_negative(lin, args):
    """完整转换管线 = convert_base（重活）+ apply_finishing（LR 精调）。
    顺序与行为与拆分前完全一致；新参数一律 getattr 读取，
    gui.py 传旧 Namespace 也能跑。
    """
    P, vin_rect = convert_base(lin, args)
    return apply_finishing(P, args, vin_rect)


# --------------------------------------------------------------------------- #
# 保存
# --------------------------------------------------------------------------- #
_ICC_CACHE = {"loaded": False, "bytes": None}


def _srgb_icc_bytes():
    """生成 sRGB ICC 配置文件字节串（缓存），失败返回 None。"""
    if not _ICC_CACHE["loaded"]:
        _ICC_CACHE["loaded"] = True
        try:
            from PIL import ImageCms
            _ICC_CACHE["bytes"] = ImageCms.ImageCmsProfile(
                ImageCms.createProfile("sRGB")).tobytes()
        except Exception:
            _ICC_CACHE["bytes"] = None
    return _ICC_CACHE["bytes"]


def _resize_long_edge(P, long_edge):
    """把 float [0,1] 图像的长边缩到 long_edge 像素（LANCZOS，量化前做保画质）。
    长边本来就不超过 long_edge 时原样返回，不放大。"""
    h, w = P.shape[:2]
    m = max(h, w)
    if long_edge <= 0 or m <= long_edge:
        return P
    s = long_edge / m
    nw = max(1, int(round(w * s)))
    nh = max(1, int(round(h * s)))
    chans = [np.asarray(Image.fromarray(
                 np.ascontiguousarray(P[..., c], dtype=np.float32), mode="F")
                 .resize((nw, nh), Image.LANCZOS))
             for c in range(3)]
    return np.clip(np.stack(chans, axis=-1), 0.0, 1.0)


def save_image(P, path, bits, quality=92, resize=0, icc=True):
    """保存图像。

    quality: jpg 压缩质量(1~100)，默认 92。
    resize:  >0 时把长边缩到该像素数（LANCZOS，不放大），默认 0 不缩放。
    icc:     尽量嵌入 sRGB ICC 配置（tif 用 extratags，jpg/png 用
             icc_profile），失败静默降级为不嵌。
    旧调用 save_image(P, path, bits) 行为不变。
    """
    Pc = np.clip(P, 0, 1)
    if resize and int(resize) > 0:
        Pc = _resize_long_edge(Pc, int(resize))
    ext = os.path.splitext(path)[1].lower()
    icc_bytes = _srgb_icc_bytes() if icc else None

    if bits == 16:
        out = (Pc * 65535.0 + 0.5).astype(np.uint16)
        # Pillow 的 RGB 模式只支持 8bit，16bit RGB 用 tifffile 写
        if ext in (".tif", ".tiff"):
            import tifffile
            if icc_bytes:
                try:
                    tifffile.imwrite(
                        path, out, photometric="rgb", compression="zlib",
                        extratags=[(34675, 7, len(icc_bytes), icc_bytes, True)])
                    return
                except Exception:
                    pass  # 嵌 ICC 失败就不嵌，继续正常写
            tifffile.imwrite(path, out, photometric="rgb", compression="zlib")
            return
        # 非 tif 想要 16bit 时退回 tif
        raise RuntimeError("16bit 仅支持 tif 输出；png/jpg 请用 --bits 8")

    out = (Pc * 255.0 + 0.5).astype(np.uint8)
    im = Image.fromarray(out, mode="RGB")
    kw = {}
    if ext in (".jpg", ".jpeg"):
        kw["quality"] = int(quality)
    if icc_bytes:
        kw["icc_profile"] = icc_bytes
    try:
        im.save(path, **kw)
    except Exception:
        # 带 ICC 保存失败时降级重存（去掉 icc_profile）
        kw.pop("icc_profile", None)
        im.save(path, **kw)


def copy_exif_best_effort(src_path, dst_path):
    """尽力而为地从源文件（RAW/图像）抄 EXIF 到导出的 jpg。

    只抄 拍摄时间(DateTimeOriginal/DateTimeDigitized/DateTime) 与
    机身(Make/Model)。ARW 是 TIFF 容器，piexif.load 通常可直接读。
    任何异常（没装 piexif、格式读不了等）都静默跳过，绝不影响主流程。
    """
    try:
        import piexif
        ed = piexif.load(src_path)
        new = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        for tag in (piexif.ImageIFD.Make, piexif.ImageIFD.Model,
                    piexif.ImageIFD.DateTime):
            if tag in ed.get("0th", {}):
                new["0th"][tag] = ed["0th"][tag]
        for tag in (piexif.ExifIFD.DateTimeOriginal,
                    piexif.ExifIFD.DateTimeDigitized):
            if tag in ed.get("Exif", {}):
                new["Exif"][tag] = ed["Exif"][tag]
        if new["0th"] or new["Exif"]:
            piexif.insert(piexif.dump(new), dst_path)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 文件搜集 / 主流程
# --------------------------------------------------------------------------- #
def gather_inputs(inp, recursive):
    if os.path.isfile(inp):
        return [inp]
    files = []
    exts = RAW_EXTS | IMG_EXTS
    if recursive:
        for root, _, names in os.walk(inp):
            for n in names:
                if os.path.splitext(n)[1].lower() in exts:
                    files.append(os.path.join(root, n))
    else:
        for n in sorted(os.listdir(inp)):
            p = os.path.join(inp, n)
            if os.path.isfile(p) and os.path.splitext(n)[1].lower() in exts:
                files.append(p)
    return sorted(files)


def out_path_for(src, out, batch, ext, suffix):
    base = os.path.splitext(os.path.basename(src))[0] + suffix + "." + ext
    if batch:
        os.makedirs(out, exist_ok=True)
        return os.path.join(out, base)
    if out:
        # 若 out 是已存在目录或以分隔符结尾，则当目录用
        if os.path.isdir(out) or out.endswith((os.sep, "/")):
            os.makedirs(out, exist_ok=True)
            return os.path.join(out, base)
        return out
    return os.path.join(os.path.dirname(src) or ".", base)


def parse_rect(s):
    parts = [int(v) for v in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--base-rect 需要 4 个整数：x,y,w,h")
    return parts


def parse_rect_f(s):
    parts = [float(v) for v in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--crop-rect 需要 4 个比例：x0,y0,x1,y1")
    return parts


def parse_point_f(s):
    parts = [float(v) for v in s.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--wb-point 需要 2 个比例：x,y（0~1）")
    return parts


def parse_curve(s):
    """曲线控制点："0,0;0.3,0.28;1,1" → [[x,y],...]"""
    try:
        pts = [[float(a) for a in seg.split(",")]
               for seg in s.split(";") if seg.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("曲线形如 0,0;0.3,0.28;1,1")
    for p in pts:
        if len(p) != 2:
            raise argparse.ArgumentTypeError("曲线每个控制点是 x,y（0~1）")
    if len(pts) < 2:
        raise argparse.ArgumentTypeError("曲线至少两个控制点")
    return pts


def parse_hsl(s):
    """HSL："orange:h=-10,s=15,l=5;blue:s=-20" → {色区:{h,s,l}}"""
    out = {}
    for seg in s.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        band, _, kv = seg.partition(":")
        band = band.strip().lower()
        if band not in HSL_BANDS:
            raise argparse.ArgumentTypeError(
                "HSL 色区应为 " + "/".join(HSL_BANDS))
        d = {}
        for item in kv.split(","):
            item = item.strip()
            if not item:
                continue
            k, _, v = item.partition("=")
            k = k.strip().lower()
            if k not in ("h", "s", "l"):
                raise argparse.ArgumentTypeError("HSL 每项键只能是 h/s/l")
            try:
                d[k] = float(v)
            except ValueError:
                raise argparse.ArgumentTypeError(f"HSL 值不是数字：{item}")
        out[band] = d
    return out


def main():
    ap = argparse.ArgumentParser(
        description="胶片翻拍负片去色罩 + 反转为正片",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--input", required=True,
                    help="输入文件或文件夹")
    ap.add_argument("-o", "--output", default=None,
                    help="输出文件或文件夹（输入为文件夹时这里当输出文件夹）")
    ap.add_argument("--recursive", action="store_true",
                    help="递归处理子文件夹")
    ap.add_argument("--format", default="tif",
                    choices=["tif", "tiff", "png", "jpg", "jpeg"],
                    help="输出格式，默认 tif")
    ap.add_argument("--bits", type=int, default=16, choices=[8, 16],
                    help="输出位深，默认 16（jpg/png 会强制 8，16bit 仅 tif 支持）")
    ap.add_argument("--suffix", default="_pos",
                    help="输出文件名后缀，默认 _pos")

    ap.add_argument("--black-pct", type=float, default=0.5,
                    help="自动黑点百分位（去片基/色罩），默认 0.5")
    ap.add_argument("--white-pct", type=float, default=99.7,
                    help="自动白点百分位，默认 99.7")
    ap.add_argument("--base-rect", type=parse_rect, default=None,
                    help="片基取样矩形 x,y,w,h（精确去色罩）")
    ap.add_argument("--margin", type=float, default=0.0,
                    help="统计时忽略四周比例(0~0.4)，避开边框漏光，默认 0")
    ap.add_argument("--crop", type=float, default=0.0,
                    help="处理前按比例裁掉四周(0~0.45)，去掉片基/齿孔边框，默认 0")
    ap.add_argument("--crop-rect", type=parse_rect_f, default=None,
                    dest="crop_rect",
                    help="任意位置矩形裁切 x0,y0,x1,y1（0~1 比例，非居中）")

    ap.add_argument("--auto-crop", action="store_true", dest="auto_crop",
                    help="自动检测胶片画面区域并当作 --crop-rect 用"
                         "（已显式给 --crop-rect 时不生效）")
    ap.add_argument("--auto-level", action="store_true", dest="auto_level",
                    help="自动校平：检测画面倾斜角并旋正（和 --auto-crop 一起用最好）")
    ap.add_argument("--negadoctor", action="store_true", dest="negadoctor",
                    help="用 darktable negadoctor 负转正引擎（默认关；彩负模式生效，"
                         "自带相纸 gamma/高光柔化，跳过普通 gamma/对比度）")
    ap.add_argument("--nd-gamma", type=float, default=2.4, dest="nd_gamma",
                    help="negadoctor 相纸反差 gamma（1~8，越大越硬），默认 2.4")
    ap.add_argument("--nd-exposure", type=float, default=1.0, dest="nd_exposure",
                    help="negadoctor 亮度增益微调（自动曝光基础上乘，默认 1.0）")
    ap.add_argument("--nd-dmax", type=float, default=2.046, dest="nd_dmax",
                    help="negadoctor 片基最大密度 D_max（0.1~6），默认 2.046")
    ap.add_argument("--nd-offset", type=float, default=-0.05, dest="nd_offset",
                    help="negadoctor 扫描曝光偏移（-1~1），默认 -0.05")
    ap.add_argument("--nd-black", type=float, default=0.0755, dest="nd_black",
                    help="negadoctor 相纸黑（-0.5~0.5），默认 0.0755")
    ap.add_argument("--nd-softclip", type=float, default=0.75, dest="nd_softclip",
                    help="negadoctor 高光柔化（1e-4~1），默认 0.75")
    ap.add_argument("--level-angle", type=float, default=0.0, dest="level_angle",
                    help="手动旋转/拉直角度（度，正=逆时针）；会自动内缩去黑角")

    ap.add_argument("--wb", default="gray", choices=["gray", "none"],
                    help="反转后白平衡：gray=灰世界(默认)，none=不做")
    ap.add_argument("--wb-point", type=parse_point_f, default=None,
                    dest="wb_point",
                    help="白点取样白平衡 x,y（0~1 比例，基于方向调整后的整幅图，"
                         "与 --crop-rect 同一坐标系）；设了它就取代灰世界")
    ap.add_argument("--wb-rect", type=parse_rect_f, default=None,
                    dest="wb_rect",
                    help="框选范围白平衡 x0,y0,x1,y1（0~1 比例，取平均颜色，"
                         "优先于 --wb-point）")
    ap.add_argument("--temp", type=float, default=0.0,
                    help="色温 -100~100（>0 偏暖 R↑B↓），默认 0；"
                         "--match 模式下跳过")
    ap.add_argument("--tint", type=float, default=0.0,
                    help="色调 -100~100（>0 偏品红 G↓，<0 偏绿），默认 0；"
                         "--match 模式下跳过")
    ap.add_argument("--mode", default="color",
                    choices=["color", "bw", "positive"],
                    help="胶片类型：color=彩色负片(默认)，bw=黑白负片，"
                         "positive=正片(E-6/幻灯片，不反转)")
    ap.add_argument("--sharpen", type=float, default=0.0,
                    help="锐化量 0~3（只锐化亮度，USM），默认 0 不锐化")
    ap.add_argument("--sharpen-radius", type=float, default=2.0,
                    dest="sharpen_radius",
                    help="锐化半径(像素)，默认 2")
    ap.add_argument("--gamma", type=float, default=1.8,
                    help="输出 gamma（>1 提亮中间调），默认 1.8")
    ap.add_argument("--contrast", type=float, default=0.08,
                    help="对比度 S 曲线强度(-1~1)，默认 0.08")
    ap.add_argument("--saturation", type=float, default=1.0,
                    help="饱和度(<1 降，>1 增)，默认 1.0")

    # LR 风格精调（match 模式下也生效，叠加在匹配结果之上）
    ap.add_argument("--exposure", type=float, default=0.0,
                    help="曝光 EV（-3~3），默认 0")
    ap.add_argument("--highlights", type=float, default=0.0,
                    help="高光 -100~100（<0 压高光/找回细节），默认 0")
    ap.add_argument("--shadows", type=float, default=0.0,
                    help="阴影 -100~100（>0 提亮暗部），默认 0")
    ap.add_argument("--whites", type=float, default=0.0,
                    help="白色色阶 -100~100（移动白场端点），默认 0")
    ap.add_argument("--blacks", type=float, default=0.0,
                    help="黑色色阶 -100~100（>0 抬黑褪色，<0 压黑），默认 0")
    ap.add_argument("--curve", type=parse_curve, default=None,
                    help='RGB 主曲线控制点，如 "0,0;0.25,0.22;0.75,0.8;1,1"')
    ap.add_argument("--curve-r", type=parse_curve, default=None,
                    dest="curve_r", help="红通道曲线（写法同 --curve）")
    ap.add_argument("--curve-g", type=parse_curve, default=None,
                    dest="curve_g", help="绿通道曲线")
    ap.add_argument("--curve-b", type=parse_curve, default=None,
                    dest="curve_b", help="蓝通道曲线")
    ap.add_argument("--hsl", type=parse_hsl, default=None,
                    help='HSL 八色调整，如 "orange:h=-10,s=15,l=5;blue:s=-20"；'
                         "色区: " + "/".join(HSL_BANDS))
    ap.add_argument("--vibrance", type=float, default=0.0,
                    help="鲜艳度 -100~100（低饱和像素受力大，比饱和度温和），默认 0")
    ap.add_argument("--vignette", type=float, default=0.0,
                    help="晕影 -100~100（<0 四角压暗），默认 0")

    ap.add_argument("--match", default=None,
                    help="参照图路径：直方图匹配到该图的色调与色彩"
                         "（有实验室扫描件时最好用；会覆盖 gamma/对比度/白平衡）")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                    help="顺时针旋转角度，默认 0")
    ap.add_argument("--flip", default="none", choices=["none", "h", "v"],
                    help="水平/垂直翻转，默认 none")
    ap.add_argument("--denoise", type=float, default=0,
                    help="色度降噪半径(像素)，去彩色颗粒不掉锐度，建议 2~4，默认 0")
    ap.add_argument("--raw-denoise", action="store_true",
                    help="RAW 阶段再开 FBDD 降噪（更干净但稍慢）")

    ap.add_argument("--quality", type=int, default=92,
                    help="jpg 压缩质量 1~100，默认 92")
    ap.add_argument("--resize", type=int, default=0,
                    help="导出时长边缩到该像素数（LANCZOS，不放大），默认 0 不缩")

    ap.add_argument("--preset", default=None,
                    help="加载 presets/ 里的预设名（显式命令行参数仍可覆盖）")
    ap.add_argument("--save-preset", default=None, dest="save_preset",
                    help="把本次生效的色调参数存成预设（存到 presets/名.json）")

    ap.add_argument("--input-gamma", default="srgb",
                    help="普通图像输入的伽马：srgb(默认)/linear/数字")
    ap.add_argument("--no-camera-wb", action="store_true",
                    help="RAW 不使用相机白平衡作为起点")
    ap.add_argument("--no-autorotate", action="store_true",
                    help="RAW 不按 EXIF 自动旋转")

    # 预设：在正式 parse_args 前先偷看 --preset，把预设值设为默认值，
    # 这样命令行里显式给出的参数仍然可以覆盖预设
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--preset", default=None)
    pre_args, _ = pre.parse_known_args()
    if pre_args.preset:
        try:
            d = load_preset(pre_args.preset)
        except FileNotFoundError:
            print(f"找不到预设 {pre_args.preset}"
                  f"（可用：{', '.join(list_presets()) or '无'}）",
                  file=sys.stderr)
            sys.exit(1)
        ap.set_defaults(**d)
        print(f"已加载预设：{pre_args.preset}")

    args = ap.parse_args()

    # 保存预设：把本次生效的色调相关参数存盘
    if args.save_preset:
        p = save_preset(args.save_preset,
                        {k: getattr(args, k) for k in PRESET_KEYS})
        print(f"预设已保存：{p}")

    files = gather_inputs(args.input, args.recursive)
    if not files:
        print("没有找到可处理的文件。", file=sys.stderr)
        sys.exit(1)

    # 参照图：一次性载入并建 CDF
    args._ref_cdfs = None
    if args.match:
        ref_raw = np.asarray(Image.open(args.match).convert("RGB"))
        maxv = 65535.0 if ref_raw.dtype == np.uint16 else 255.0
        ref = ref_raw.astype(np.float32) / maxv
        step = max(1, int(np.ceil(max(ref.shape[:2]) / 1000)))
        args._ref_centers, args._ref_cdfs = build_ref_cdf(ref[::step, ::step])
        print(f"参照图：{os.path.basename(args.match)}（直方图匹配）")

    batch = os.path.isdir(args.input)
    ext = "jpg" if args.format in ("jpg", "jpeg") else \
          ("tif" if args.format in ("tif", "tiff") else args.format)
    # jpg/png 只能 8bit（16bit RGB 仅 tif 能写），强制降到 8 避免整批报错
    bits = 8 if ext in ("jpg", "png") else args.bits

    print(f"共 {len(files)} 个文件，输出 {ext}/{bits}bit"
          f"{'（rawpy 可用）' if HAVE_RAWPY else '（无 rawpy，RAW 将跳过）'}")
    ok = 0
    for idx, src in enumerate(files, 1):
        try:
            lin, _ = load_image(src, args)
            fargs = args
            do_level = getattr(args, "auto_level", False)
            do_crop = getattr(args, "auto_crop", False) and not args.crop_rect
            if do_level or do_crop:
                # Use one geometry solution for both leveling and cropping.
                fargs = argparse.Namespace(**vars(args))
                small = orient_image(stats_view(lin, max_side=1500), args.rotate, args.flip)
                alignment = detect_film_alignment(small, args.level_angle, auto_level=do_level)
                if do_level:
                    fargs.level_angle = alignment['angle']
                    print(f"[{idx}/{len(files)}] 自动校平：{fargs.level_angle:+.2f}°")
                if do_crop:
                    fargs.crop_rect = alignment['rect']
                    print(f"[{idx}/{len(files)}] 自动画面区域："
                          f"{','.join(f'{v:.3f}' for v in alignment['rect'])}")
            P = convert_negative(lin, fargs)
            dst = out_path_for(src, args.output, batch, ext, args.suffix)
            save_image(P, dst, bits, quality=args.quality, resize=args.resize)
            if ext == "jpg":
                copy_exif_best_effort(src, dst)  # 尽力抄 EXIF，失败静默
            print(f"[{idx}/{len(files)}] {os.path.basename(src)} -> {dst}")
            ok += 1
        except Exception as e:
            print(f"[{idx}/{len(files)}] 跳过 {os.path.basename(src)}：{e}",
                  file=sys.stderr)
    print(f"完成：{ok}/{len(files)} 成功。")


if __name__ == "__main__":
    main()

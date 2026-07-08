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
    return np.where(x <= 0.04045, x / 12.92, ((x + a) / (1 + a)) ** 2.4)


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
        im = Image.open(path)
        arr = np.asarray(im)
        if arr.ndim == 2:  # 灰度 -> 复制成三通道
            arr = np.stack([arr] * 3, axis=-1)
        if arr.shape[-1] == 4:  # 去 alpha
            arr = arr[..., :3]
        maxv = 65535.0 if arr.dtype == np.uint16 else 255.0
        enc = arr.astype(np.float32) / maxv
        # 普通图像默认按 sRGB 反伽马回到线性，使密度运算正确
        if args.input_gamma == "srgb":
            lin = srgb_to_linear(enc)
        elif args.input_gamma == "linear":
            lin = enc
        else:
            lin = np.power(np.clip(enc, 0, 1), float(args.input_gamma))
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


def detect_film_rect(lin_oriented):
    """自动检测胶片画面区域（去掉片基/齿孔间隔/暗边框）。

    输入：方向已调整（rotate/flip 已做）的线性负片 HxWx3。
    输出：[x0,y0,x1,y1]，0~1 比例坐标，可直接当 crop_rect 用。

    做法：下采样后取线性亮度。翻拍负片里画面外只有两种东西：
      - 片基/无片裸光：接近整幅最亮（≈ 99.5 百分位）
      - 片夹/黑边框：远暗于画面中值
    把这两类都排除后剩下的就是「内容」像素，按行/列统计内容占比 > 0.2
    的最大连续区间（等价于在快速反转的正片亮度上做中间调分离），
    最后向内收 1%。检测不到合理区域时兜底返回 [0.03, 0.03, 0.97, 0.97]。
    """
    fallback = [0.03, 0.03, 0.97, 0.97]
    try:
        V = np.asarray(stats_view(lin_oriented, max_side=600),
                       dtype=np.float32)
        luma = np.clip(V, 0.0, 1.0) @ LUMA_W
        hh, ww = luma.shape
        med = float(np.median(luma))
        p_hi = float(np.percentile(luma, 99.5))
        if p_hi <= 1e-4:
            return fallback
        # 内容像素：既不接近片基/裸光的最亮档，也不掉进黑边框的暗档
        content = (luma < 0.8 * p_hi) & (luma > 0.3 * med)

        # 行/列上「内容像素占比 > 0.2」的最大连续区间
        rl, rs, re = _longest_run(content.mean(axis=1) > 0.2)
        cl, cs, ce = _longest_run(content.mean(axis=0) > 0.2)
        if rl < 0.3 * hh or cl < 0.3 * ww:
            return fallback

        # 向内收 1%，并做边界保护
        x0 = max(0.0, cs / ww + 0.01)
        x1 = min(1.0, (ce + 1) / ww - 0.01)
        y0 = max(0.0, rs / hh + 0.01)
        y1 = min(1.0, (re + 1) / hh - 0.01)
        if x1 - x0 < 0.2 or y1 - y0 < 0.2:
            return fallback
        return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
    except Exception:
        return fallback


def _robust_slope(x, y, max_tan):
    """稳健拟合直线斜率：先最小二乘，剔除残差离群点后重拟合。
    斜率超过 max_tan（对应角度过大、多半是误检）则返回 None。"""
    if len(x) < 12:
        return None
    m, b = np.polyfit(x, y, 1)
    resid = np.abs(y - (m * x + b))
    thr = 2.0 * np.median(resid) + 1e-6
    keep = resid < thr
    if keep.sum() >= 12:
        m, b = np.polyfit(x[keep], y[keep], 1)
        if (keep.sum()) < 0.4 * len(x):   # 边缘太散，不可信
            return None
    if abs(m) > max_tan:
        return None
    return float(m)


def estimate_skew(lin, max_angle=8.0):
    """估计画面倾斜角（度），用于自动校平。

    只用【画面/片框的边界】测倾斜，不受图像内容干扰：
    先按 detect_film_rect 同法分出「内容」像素，再对上下边逐列取
    内容起止行、对左右边逐行取内容起止列，各自稳健拟合直线求斜率，
    四条边的角度取中位数。这样测的是胶片画幅本身的水平，
    比"旋转让边缘投影最尖"的老办法稳得多（后者会被砖缝、树枝带偏）。
    返回应施加的旋转角（PIL rotate 同向，正=逆时针）；测不准返回 0。
    """
    V = np.clip(np.asarray(stats_view(lin, max_side=760), np.float32), 0.0, 1.0)
    luma = V @ LUMA_W if V.ndim == 3 else V
    H, W = luma.shape
    med = float(np.median(luma))
    p_hi = float(np.percentile(luma, 99.5))
    if p_hi <= 1e-4:
        return 0.0
    content = (luma < 0.8 * p_hi) & (luma > 0.3 * med)
    max_tan = np.tan(np.radians(max_angle))
    angs = []

    # 上/下边：逐列取「首个/末个内容行」，拟合出的斜率 m=dy/dx → 角 = atan(m)
    xs = np.where(content.sum(axis=0) > 0.3 * H)[0]
    if len(xs) > 0.3 * W:
        top = np.array([np.argmax(content[:, x]) for x in xs], float)
        bot = np.array([H - 1 - np.argmax(content[::-1, x]) for x in xs], float)
        xf = xs.astype(float)
        for e in (top, bot):
            m = _robust_slope(xf, e, max_tan)
            if m is not None:
                angs.append(np.degrees(np.arctan(m)))

    # 左/右边：逐行取「首个/末个内容列」，斜率 m=dx/dy → 角 = -atan(m)
    ys = np.where(content.sum(axis=1) > 0.3 * W)[0]
    if len(ys) > 0.3 * H:
        lef = np.array([np.argmax(content[y]) for y in ys], float)
        rig = np.array([W - 1 - np.argmax(content[y][::-1]) for y in ys], float)
        yf = ys.astype(float)
        for e in (lef, rig):
            m = _robust_slope(yf, e, max_tan)
            if m is not None:
                angs.append(-np.degrees(np.arctan(m)))

    if len(angs) < 2:            # 至少两条边一致才敢转
        return 0.0
    ang = float(np.median(angs))
    if abs(ang) > max_angle:
        return 0.0
    return ang if abs(ang) >= 0.25 else 0.0


def _deskew_lin(lin, angle):
    """按 angle（度，正=逆时针）旋转线性图；每通道用 PIL 'F' 模式保精度，
    expand=False 保持画幅（旋转带入的黑角随后由裁切内缩去掉）。"""
    if abs(angle) < 0.1:
        return lin
    out = [np.asarray(Image.fromarray(np.ascontiguousarray(lin[..., c]), mode="F")
                      .rotate(angle, resample=Image.BILINEAR, expand=False))
           for c in range(3)]
    return np.ascontiguousarray(np.stack(out, axis=-1))


def _safe_inset_rect(shape, angle):
    """旋转 angle 后能避开黑角的最大居中矩形，返回 [x0,y0,x1,y1]（0~1）。
    旋转产生的黑区只在四角，所以对称向内收，直到矩形四角都落在有效区即可。"""
    h, w = shape[:2]
    hs = 240
    ws = max(2, int(round(hs * w / h)))
    ones = np.ones((hs, ws), np.float32)
    r = np.asarray(Image.fromarray(ones, mode="F")
                   .rotate(angle, resample=Image.NEAREST, expand=False))
    valid = r > 0.999
    for f in np.linspace(0.0, 0.45, 91):          # 每步 0.5%，对称内缩
        x0 = int(f * ws); x1 = int(round((1 - f) * ws)) - 1
        y0 = int(f * hs); y1 = int(round((1 - f) * hs)) - 1
        if x1 <= x0 or y1 <= y0:
            break
        if (valid[y0, x0] and valid[y0, x1]
                and valid[y1, x0] and valid[y1, x1]):
            f = float(round(f, 4))
            return [f, f, 1 - f, 1 - f]
    return None


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
    if abs(_lvl) >= 0.1:
        lin = _deskew_lin(lin, _lvl)
        # 没有显式裁切框、且不是「整幅预览+统计框」模式时，自动内缩去黑角
        if (not getattr(args, "crop_rect", None)
                and not getattr(args, "stats_rect", None)):
            _safe_rect = _safe_inset_rect(lin.shape[:2], _lvl)

    # 2) 裁切
    #    crop_rect: 任意位置矩形裁切（会真正裁掉，用于导出/最终结果）
    #    stats_rect: 只把这块区域用于算色阶/白平衡，但输出仍是整幅（预览定位裁切框用）
    #    crop: 老的居中比例裁切（向后兼容）
    crop_rect = getattr(args, "crop_rect", None) or _safe_rect
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
    else:
        # 彩色负片：密度空间去色罩 + 反转（原有算法，保持不变）
        N = np.clip(lin, eps, 1.0)
        D = -np.log10(N)  # 密度，>=0；场景越亮 D 越大

        Dv = _trim_margin(-np.log10(
            np.clip(stats_view(stats_lin), eps, 1.0)))  # 下采样统计用

        P = np.empty_like(D)
        base_density = None
        if getattr(args, "base_rect", None):
            # 用指定片基矩形（橙色片基，无影像区）锚定色罩黑点
            x, y, bw, bh = args.base_rect
            patch = np.clip(lin[y:y + bh, x:x + bw], eps, 1.0)
            base_lin = np.median(patch.reshape(-1, 3), axis=0)
            base_density = -np.log10(base_lin)  # 每通道片基密度 = 黑点

        for c in range(3):
            Dc = D[..., c]
            col = Dv[..., c].reshape(-1)
            if base_density is not None:
                bp = base_density[c]
            else:
                bp = np.percentile(col, black_pct)
            wp = np.percentile(col, white_pct)
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
            flat = P.reshape(-1, 3)
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

        # 6) 影调：gamma + 对比度 S 曲线
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
        if os.path.isdir(out) or out.endswith(os.sep):
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
                # 在「方向调整后」的下采样图上检测：先算校平角、按角旋正小图，
                # 再检测画面区域，使裁切框与全图去斜后同一坐标系；逐张各用各的
                fargs = argparse.Namespace(**vars(args))
                small = orient_image(stats_view(lin, max_side=800),
                                     args.rotate, args.flip)
                if do_level:
                    ang = estimate_skew(small)
                    fargs.level_angle = ang
                    if abs(ang) >= 0.1:
                        small = _deskew_lin(small, ang)
                    print(f"[{idx}/{len(files)}] 自动校平：{ang:+.2f}°")
                if do_crop:
                    rect = detect_film_rect(small)
                    fargs.crop_rect = rect
                    print(f"[{idx}/{len(files)}] 自动画面区域："
                          f"{','.join(f'{v:.3f}' for v in rect)}")
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

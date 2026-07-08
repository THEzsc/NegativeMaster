#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui.py —— 去色罩工具的可视化界面（本地网页）

在浏览器里实时调参数、看效果，满意后一键导出全分辨率成品。
底层直接复用 decast.py 的真实算法，预览和导出结果一致。

功能：
  - 彩负 / 黑白 / 正片 三种模式，色温/色调/锐化滑杆
  - LR 风格精调：曝光/高光/阴影/白色/黑色、可拖点曲线（RGB+单通道）、
    HSL 八色（色相/饱和/明亮）、鲜艳度、晕影
  - 取白点白平衡、自动检测画面区域、直方图、按住看负片
  - 预览滚轮缩放 + 平移，裁切框画幅比例锁定
  - 每张图自动记忆参数（settings/），色调预设（presets/，与 CLI 共用，含内置胶片风格）
  - 批量导出、JPG 质量 / 长边缩放导出选项
  - 快捷键：r 右转 / R 左转 / f 镜像 / e 导出 / 空格按住看负片

启动：
  ./gui.sh                      # 默认列出「胶片扫描」和「下载」里的片子
  ./gui.sh "/some/folder"       # 指定一个文件夹
  ./gui.sh --port 8766          # 换端口（默认 8765）

然后浏览器打开 http://127.0.0.1:8765
"""

import io
import os
import sys
import json
import hashlib
import argparse
import subprocess
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from flask import Flask, request, jsonify, send_file, Response

import decast  # 复用真实转换算法

Image.MAX_IMAGE_PIXELS = None

PREVIEW_MAXSIDE = 1500  # 预览用的下采样边长
HIST_BINS = 64          # 直方图 bin 数

# 每张图的参数记忆目录（文件名 = sha1(绝对路径).json）
SETTINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings")

DEFAULTS = dict(
    crop=0.0, crop_rect=None, base_rect=None, margin=0.0,
    black_pct=0.5, white_pct=99.7,
    wb="gray", gamma=1.8, contrast=0.08, saturation=1.0,
    denoise=0.0, rotate=0, flip="none", level_angle=0.0,
    negadoctor=False, nd_gamma=2.4, nd_exposure=1.0,
    nd_dmax=2.046, nd_offset=-0.05, nd_black=0.0755, nd_softclip=0.75,
    mode="color", temp=0.0, tint=0.0,
    sharpen=0.0, sharpen_radius=2.0, wb_point=None, wb_rect=None,
    film_base_rect=None, shadow_rect=None, highlight_rect=None,
    # LR 风格精调
    exposure=0.0, highlights=0.0, shadows=0.0, whites=0.0, blacks=0.0,
    curve=None, curve_r=None, curve_g=None, curve_b=None,
    hsl=None, vibrance=0.0, vignette=0.0,
    raw_denoise=False, no_camera_wb=False, no_autorotate=False,
    input_gamma="srgb",
)

app = Flask(__name__)

# 当前载入图像的缓存（只留当前一张，控内存）；lastP = 最近一次预览结果（算直方图用）
# raw_dn = 解码这张图时是否开了 RAW FBDD 降噪（开关变化要重新解码）
# base/base_key/base_vrect = 管线前半（反转+白平衡+影调）的分阶段缓存——
# 拖 LR 精调滑杆（曝光/曲线/HSL 等）时只重算后半段，参考 darktable pixelpipe
CACHE = {"path": None, "full": None, "prev": None, "scale": 1.0,
         "lastP": None, "raw_dn": False,
         "base": None, "base_key": None, "base_vrect": None}

# 影响管线前半（convert_base）的参数——它们变了才重算 base 缓存
BASE_PARAM_KEYS = ("mode", "rotate", "flip", "level_angle",
                   "black_pct", "white_pct",
                   "wb", "wb_point", "wb_rect", "temp", "tint", "gamma", "contrast",
                   "margin", "base_rect", "input_gamma",
                   "film_base_rect", "shadow_rect", "highlight_rect",
                   "negadoctor", "nd_gamma", "nd_exposure",
                   "nd_dmax", "nd_offset", "nd_black", "nd_softclip")


def _base_cache_key(params, cr):
    """算 base 缓存键：文件 + RAW降噪 + 裁切框 + 所有前半段参数 + 匹配参照。"""
    d = {k: params.get(k, DEFAULTS.get(k)) for k in BASE_PARAM_KEYS}
    d["crop_rect"] = cr
    use_match = bool(params.get("use_match")) and REF["cdfs"] is not None
    d["match"] = REF["path"] if use_match else None
    d["path"] = CACHE["path"]
    d["raw_dn"] = CACHE["raw_dn"]
    return json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
REF = {"path": None, "centers": None, "cdfs": None}
START_DIRS = []


def make_opts(params):
    """把前端参数字典拼成 decast 需要的 options 命名空间。"""
    d = dict(DEFAULTS)
    for k, v in params.items():
        if k in d:
            d[k] = v
    ns = argparse.Namespace(**d)
    ns._ref_centers = REF["centers"]
    ns._ref_cdfs = REF["cdfs"] if params.get("use_match") else None
    return ns


def color_to_temp_tint(color):
    """把一块「应为中性」的取样色换算成 色温/色调 值（与 decast.apply_temp_tint
    的通道增益模型对应，k=0.3、均值归一），供框选白点后回填两条滑杆。"""
    c = np.clip(np.asarray(color, dtype=np.float64), 1e-4, None)
    d = c.mean() / c                 # 中和到中性所需的每通道增益
    dn = d / d.mean()                # 均值归一（apply_temp_tint 也做了归一）
    k = 0.3
    temp = float(np.clip((dn[0] - dn[2]) / (2 * k) * 100.0, -100, 100))
    tint = float(np.clip((1.0 - dn[1]) / k * 100.0, -100, 100))
    return round(temp, 1), round(tint, 1)


def to_jpeg(arr_float):
    im = Image.fromarray((np.clip(arr_float, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    buf.seek(0)
    return buf


def load_full(path, raw_denoise=False):
    """解码一张（RAW 或普通图）到线性 RGB，并缓存全分辨率 + 预览两份。

    raw_denoise（RAW 阶段 FBDD 降噪）只在解码时生效，
    所以同一路径下开关变化也要重新解码。
    """
    raw_denoise = bool(raw_denoise)
    if (CACHE["path"] == path and CACHE["full"] is not None
            and CACHE["raw_dn"] == raw_denoise):
        return
    opts = argparse.Namespace(**DEFAULTS)
    opts.raw_denoise = raw_denoise
    lin, _ = decast.load_image(path, opts)
    h, w = lin.shape[:2]
    step = max(1, int(np.ceil(max(h, w) / PREVIEW_MAXSIDE)))
    prev = lin[::step, ::step].copy()
    CACHE.update(path=path, full=lin, prev=prev, lastP=None,
                 base=None, base_key=None, base_vrect=None,
                 raw_dn=raw_denoise, scale=max(prev.shape[:2]) / max(h, w))


def settings_file(path):
    """某个图像文件对应的参数记忆 JSON 路径。"""
    key = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()
    return os.path.join(SETTINGS_DIR, key + ".json")


def sidecar_path(path):
    """调整参数的 XML 边车路径：和源文件放一起，保留原扩展名避免同名冲突。
    如 /a/TZP06758.ARW -> /a/TZP06758.ARW.decast.xml"""
    return os.path.abspath(path) + ".decast.xml"


def _data_to_xml(data, src):
    """把 {P, cropN, curFmt, orient} 序列化成可读、可回读的 XML。"""
    root = ET.Element("decastAdjustments",
                      version="1", source=os.path.basename(src))
    pe = ET.SubElement(root, "params")
    P = data.get("P") or {}
    for k in sorted(P.keys()):
        v = P[k]
        el = ET.SubElement(pe, "param", name=str(k))
        if v is None:
            el.set("null", "1")
        elif isinstance(v, (dict, list)):
            el.set("json", json.dumps(v, ensure_ascii=False))
        elif isinstance(v, str):
            el.set("type", "str"); el.set("value", v)
        else:  # int / float / bool
            el.set("value", json.dumps(v))
    cn = data.get("cropN") or {}
    ET.SubElement(root, "crop", **{k: str(cn.get(k, "")) for k in
                                   ("x0", "y0", "x1", "y1")})
    ET.SubElement(root, "view", fmt=str(data.get("curFmt", "free")),
                  orient=str(data.get("orient", "land")))
    try:
        ET.indent(root)  # Python 3.9+ 美化缩进
    except Exception:
        pass
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _xml_to_data(xmlstr):
    """回读 XML 边车 -> {P, cropN, curFmt, orient}。"""
    root = ET.fromstring(xmlstr)
    P = {}
    for el in root.findall("./params/param"):
        name = el.get("name")
        if name is None:
            continue
        if el.get("null"):
            P[name] = None
        elif el.get("json") is not None:
            P[name] = json.loads(el.get("json"))
        elif el.get("type") == "str":
            P[name] = el.get("value", "")
        elif el.get("value") is not None:
            P[name] = json.loads(el.get("value"))
    data = {"P": P}
    c = root.find("crop")
    if c is not None:
        try:
            data["cropN"] = {k: float(c.get(k)) for k in
                             ("x0", "y0", "x1", "y1")}
        except Exception:
            pass
    v = root.find("view")
    if v is not None:
        data["curFmt"] = v.get("fmt", "free")
        data["orient"] = v.get("orient", "land")
    return data


def bad_preset_name(name):
    """预设名安全检查：非空、不带路径分隔符、不以点开头。"""
    return (not name or "/" in name or "\\" in name
            or os.sep in name or name.startswith("."))


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/api/list")
def api_list():
    d = request.args.get("dir", "").strip()
    dirs = [d] if d else START_DIRS
    items = []
    exts = decast.RAW_EXTS | decast.IMG_EXTS
    for base in dirs:
        if not base or not os.path.isdir(base):
            continue
        for root, _, names in os.walk(base):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in exts and not n.startswith("."):
                    items.append(os.path.join(root, n))
            # 只下钻一层，避免太深太慢
            if root != base and os.path.dirname(root) != base:
                pass
    items = sorted(set(items))[:600]
    return jsonify(dirs=dirs, files=items)


@app.route("/api/load", methods=["POST"])
def api_load():
    path = request.json.get("path", "")
    if not os.path.isfile(path):
        return jsonify(ok=False, err="文件不存在"), 400
    try:
        load_full(path, request.json.get("raw_denoise", False))
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500
    h, w = CACHE["full"].shape[:2]
    return jsonify(ok=True, w=int(w), h=int(h), name=os.path.basename(path))


@app.route("/api/loadref", methods=["POST"])
def api_loadref():
    path = request.json.get("path", "")
    if not path:
        REF.update(path=None, centers=None, cdfs=None)
        return jsonify(ok=True, cleared=True)
    if not os.path.isfile(path):
        return jsonify(ok=False, err="参照图不存在"), 400
    raw = np.asarray(Image.open(path).convert("RGB"))
    maxv = 65535.0 if raw.dtype == np.uint16 else 255.0
    ref = raw.astype(np.float32) / maxv
    step = max(1, int(np.ceil(max(ref.shape[:2]) / 1000)))
    centers, cdfs = decast.build_ref_cdf(ref[::step, ::step])
    REF.update(path=path, centers=centers, cdfs=cdfs)
    return jsonify(ok=True, name=os.path.basename(path))


@app.route("/api/render", methods=["POST"])
def api_render():
    if CACHE["prev"] is None:
        return jsonify(ok=False, err="先载入图片"), 400
    params = dict(request.json or {})

    # 「按住看负片」：只做方向调整，把线性负片按 1/2.2 gamma 编码直接返回，不反转
    if params.get("negative_preview"):
        lin = decast.orient_image(CACHE["prev"],
                                  int(params.get("rotate", 0) or 0),
                                  str(params.get("flip", "none")))
        P = np.power(np.clip(lin, 0.0, 1.0), 1.0 / 2.2)
        return send_file(to_jpeg(P), mimetype="image/jpeg")

    # RAW FBDD 降噪开关变化时重新解码当前图（load_full 内部有缓存判断）
    try:
        load_full(CACHE["path"], params.get("raw_denoise", False))
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500

    cr = params.get("crop_rect")
    # 预览是下采样的，去噪/锐化半径按比例缩小才有代表性
    if params.get("denoise"):
        params["denoise"] = max(0.0, round(float(params["denoise"]) * CACHE["scale"]))
    if params.get("sharpen_radius"):
        params["sharpen_radius"] = max(
            1.0, float(params["sharpen_radius"]) * CACHE["scale"])
    opts = make_opts(params)
    # 预览显示整幅（方便拖裁切框定位），但色阶/白平衡只用框内区域算，
    # 这样框里看到的颜色就是最终裁切后的效果
    opts.crop = 0.0
    opts.crop_rect = None
    opts.stats_rect = cr

    # 分阶段缓存：前半段（反转/白平衡/影调）参数没变就直接用缓存，
    # 只重算 LR 精调后半段——拖曝光/曲线/HSL 这些滑杆时快好几倍
    bkey = _base_cache_key(params, cr)
    if CACHE.get("base") is not None and CACHE.get("base_key") == bkey:
        Pb, vrect = CACHE["base"], CACHE["base_vrect"]
    else:
        Pb, vrect = decast.convert_base(CACHE["prev"], opts)
        CACHE.update(base=Pb, base_key=bkey, base_vrect=vrect)
    P = decast.apply_finishing(Pb, opts, vrect)

    # 存一份下采样结果供 /api/hist 用
    step = max(1, int(np.ceil(max(P.shape[:2]) / 500)))
    CACHE["lastP"] = P[::step, ::step].copy()
    return send_file(to_jpeg(P), mimetype="image/jpeg")


@app.route("/api/hist")
def api_hist():
    """最近一次预览结果的 RGB 直方图，各 64 bins，计数归一到 0~1。"""
    P = CACHE.get("lastP")
    if P is None:
        return jsonify(ok=False, err="还没有渲染结果"), 400
    out = {}
    for i, k in enumerate("rgb"):
        h, _ = np.histogram(P[..., i].ravel(), bins=HIST_BINS, range=(0.0, 1.0))
        m = float(h.max())
        out[k] = [round(float(v) / m, 4) if m > 0 else 0.0 for v in h]
    return jsonify(ok=True, **out)


@app.route("/api/autocrop", methods=["POST"])
def api_autocrop():
    """方向调整后：可选自动校平(测倾斜角)，再自动检测画面区域。
    返回 0~1 比例矩形 rect 和校平角 angle（度，前端存进 level_angle）。"""
    if CACHE["prev"] is None:
        return jsonify(ok=False, err="先载入图片"), 400
    body = request.json or {}
    rot = int(body.get("rotate", 0) or 0)
    flip = str(body.get("flip", "none"))
    oriented = decast.orient_image(CACHE["prev"], rot, flip)
    ang = decast.estimate_skew(oriented) if body.get("level") else 0.0
    src = decast._deskew_lin(oriented, ang) if abs(ang) >= 0.1 else oriented
    rect = decast.detect_film_rect(src)
    return jsonify(ok=True, rect=rect, angle=round(float(ang), 2))


@app.route("/api/wbtemp", methods=["POST"])
def api_wbtemp():
    """框选中性灰后：在「未白平衡」的正片上取该框平均色，换算成 色温/色调 返回。"""
    if CACHE["prev"] is None:
        return jsonify(ok=False, err="先载入图片"), 400
    params = dict(request.json or {})
    rect = params.get("wb_rect")
    if not rect:
        return jsonify(ok=False, err="没有白点框"), 400
    try:
        load_full(CACHE["path"], params.get("raw_denoise", False))
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500
    opts = make_opts(params)
    opts.crop = 0.0
    opts.crop_rect = None
    opts.stats_rect = params.get("crop_rect")   # 预览：整幅显示、按裁切框算色阶
    opts.wb = "none"; opts.wb_rect = None; opts.wb_point = None
    opts.temp = 0.0; opts.tint = 0.0
    opts._ref_cdfs = None                        # 不做匹配，取纯反转色
    Pb, _ = decast.convert_base(CACHE["prev"], opts)
    h, w = Pb.shape[:2]
    if isinstance(rect, dict):
        x0, y0, x1, y1 = rect["x0"], rect["y0"], rect["x1"], rect["y1"]
    else:
        x0, y0, x1, y1 = rect
    xa = max(0, int(min(x0, x1) * w)); xb = max(xa + 1, int(max(x0, x1) * w))
    ya = max(0, int(min(y0, y1) * h)); yb = max(ya + 1, int(max(y0, y1) * h))
    color = Pb[ya:yb, xa:xb].reshape(-1, 3).mean(axis=0)
    temp, tint = color_to_temp_tint(color)
    return jsonify(ok=True, temp=temp, tint=tint)


@app.route("/api/pick")
def api_pick():
    """弹 macOS 原生选择对话框（osascript）。mode=dir 选文件夹 /
    file 选文件 / save 选保存路径。对话框可能弹在浏览器窗口后面。"""
    mode = request.args.get("mode", "dir")
    if mode == "file":
        script = 'POSIX path of (choose file with prompt "选择图片文件")'
    elif mode == "save":
        script = 'POSIX path of (choose file name with prompt "导出为…")'
    else:
        script = 'POSIX path of (choose folder with prompt "选择文件夹")'
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=300)
        p = (r.stdout or "").strip()
        if r.returncode != 0 or not p:
            return jsonify(ok=False, err="已取消")
        return jsonify(ok=True, path=p)
    except subprocess.TimeoutExpired:
        return jsonify(ok=False, err="选择超时"), 408
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """每张图的参数记忆：GET 读取（没有记录时 data 为 null），POST 保存。"""
    if request.method == "GET":
        path = request.args.get("path", "").strip()
        if not path:
            return jsonify(ok=False, err="缺少 path"), 400
        f = settings_file(path)
        data = None
        if os.path.isfile(f):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                data = None
        return jsonify(ok=True, data=data)
    body = request.json or {}
    path = str(body.get("path", "")).strip()
    if not path:
        return jsonify(ok=False, err="缺少 path"), 400
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    try:
        with open(settings_file(path), "w", encoding="utf-8") as fh:
            json.dump(body.get("data") or {}, fh, ensure_ascii=False, indent=1)
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500
    return jsonify(ok=True)


@app.route("/api/sidecar", methods=["GET", "POST"])
def api_sidecar():
    """调整参数的 XML 边车：紧挨源文件保存/回读，随照片一起搬移。
    GET?path= 读取（无边车时 data=null）；POST {path,data} 写入。"""
    if request.method == "GET":
        path = request.args.get("path", "").strip()
        if not path:
            return jsonify(ok=False, err="缺少 path"), 400
        sp = sidecar_path(path)
        if not os.path.isfile(sp):
            return jsonify(ok=True, data=None)
        try:
            with open(sp, "r", encoding="utf-8") as fh:
                return jsonify(ok=True, data=_xml_to_data(fh.read()), file=sp)
        except Exception as e:
            return jsonify(ok=True, data=None, warn=str(e))
    body = request.json or {}
    path = str(body.get("path", "")).strip()
    if not path:
        return jsonify(ok=False, err="缺少 path"), 400
    sp = sidecar_path(path)
    try:
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(_data_to_xml(body.get("data") or {}, path))
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500
    return jsonify(ok=True, file=sp)


@app.route("/api/presets", methods=["GET", "POST", "DELETE"])
def api_presets():
    """色调预设：GET 列表 / GET?name= 读单个 / POST 保存 / DELETE 删除。
    复用 decast 的 list/load/save_preset，与 CLI --preset 共用同一目录。"""
    if request.method == "GET":
        name = request.args.get("name", "").strip()
        if not name:
            return jsonify(ok=True, names=decast.list_presets())
        if bad_preset_name(name):
            return jsonify(ok=False, err="非法预设名"), 400
        try:
            return jsonify(ok=True, name=name, data=decast.load_preset(name))
        except FileNotFoundError:
            return jsonify(ok=False, err="预设不存在"), 404
    if request.method == "POST":
        body = request.json or {}
        name = str(body.get("name", "")).strip()
        if bad_preset_name(name):
            return jsonify(ok=False, err="非法预设名"), 400
        try:
            decast.save_preset(name, dict(body.get("data") or {}))
        except Exception as e:
            return jsonify(ok=False, err=str(e)), 500
        return jsonify(ok=True, names=decast.list_presets())
    # DELETE
    name = request.args.get("name", "").strip()
    if bad_preset_name(name):
        return jsonify(ok=False, err="非法预设名"), 400
    p = os.path.join(decast.PRESET_DIR, name + ".json")
    if not os.path.isfile(p):
        return jsonify(ok=False, err="预设不存在"), 404
    os.remove(p)
    return jsonify(ok=True, names=decast.list_presets())


@app.route("/api/export", methods=["POST"])
def api_export():
    if CACHE["full"] is None:
        return jsonify(ok=False, err="先载入图片"), 400
    body = dict(request.json or {})
    out = str(body.pop("out", "") or "").strip()
    fmt = body.pop("format", "tif")
    bits = int(body.pop("bits", 16))
    quality = int(body.pop("quality", 92) or 92)
    resize = int(body.pop("resize", 0) or 0)
    body.pop("negative_preview", None)

    src = CACHE["path"]
    ext = "jpg" if fmt in ("jpg", "jpeg") else "tif"
    base = os.path.splitext(os.path.basename(src))[0] + "_pos." + ext
    try:
        if not out:
            out = os.path.splitext(src)[0] + "_pos." + ext
        elif out.endswith("/") or os.path.isdir(out):
            # 传目录（或以 / 结尾）时：自动建目录，文件名用 源名_pos.扩展名
            os.makedirs(out, exist_ok=True)
            out = os.path.join(out, base)
        else:
            d = os.path.dirname(out)
            if d:
                os.makedirs(d, exist_ok=True)
    except Exception as e:
        return jsonify(ok=False, err="输出目录创建失败：" + str(e)), 500

    # RAW FBDD 降噪开关与当前缓存不一致时重新解码（保证导出和预览一致）
    try:
        load_full(CACHE["path"], body.get("raw_denoise", False))
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500

    opts = make_opts(body)
    opts.stats_rect = None  # 导出：crop_rect 真正裁切，色阶自然只用框内
    P = decast.convert_negative(CACHE["full"], opts)
    try:
        decast.save_image(P, out, 8 if ext == "jpg" else bits,
                          quality=quality, resize=resize)
        if ext == "jpg":
            decast.copy_exif_best_effort(src, out)  # 尽力抄 EXIF，失败静默
    except Exception as e:
        return jsonify(ok=False, err=str(e)), 500
    return jsonify(ok=True, out=out)


INDEX_HTML = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>胶片去色罩 · 可视化</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0b0c10;
  --panel: #13161c;
  --line: #222631;
  --fg: #e2e8f0;
  --mut: #94a3b8;
  --acc: #fbbf24;
  --acc-hover: #f59e0b;
  --acc-glow: rgba(251, 191, 36, 0.35);
  --hz: 14px;
  --bz: 1px;
}
* { box-sizing: border-box; }
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #272c3a;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #3c445a;
}
body {
  margin: 0;
  font: 13px/1.5 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  background: var(--bg);
  color: var(--fg);
  height: 100vh;
  display: flex;
  overflow: hidden;
}
#stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px 24px 64px;   /* 底部预留底栏空间，避免遮挡照片 */
  overflow: hidden;
  position: relative;
  background: radial-gradient(circle at center, #161823 0%, #08090e 100%);
}
#stagebar {
  position: absolute;
  left: 16px;
  top: 16px;
  display: flex;
  gap: 8px;
  align-items: center;
  z-index: 10;
  padding: 6px 12px;
  border-radius: 20px;
  background: rgba(19, 22, 28, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}
#stagebar button {
  padding: 4px 12px;
  font-size: 11px;
  border-radius: 14px;
}
#zoominfo {
  color: var(--acc);
  font-weight: 600;
  font-size: 11px;
  margin-left: 4px;
}
#rotpad {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  z-index: 10;
  display: none;
  align-items: center;
  gap: 8px;
  background: rgba(19, 22, 28, 0.9);
  backdrop-filter: blur(16px);
  padding: 8px 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.45);
  font-size: 11px;
  white-space: nowrap;
}
#rotpad .rotgroup {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-wrap: wrap;
}
#rotpad .navbtn {
  flex: 0 0 auto;
  font-size: 18px;
  line-height: 1;
  padding: 4px 12px;
  border-radius: 8px;
}
#rotpad .navbtn:disabled { opacity: 0.3; cursor: default; }
#fileselect {
  flex: 0 1 auto;
  max-width: 240px;
  padding: 4px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--fg);
  font-size: 11px;
}
#rotpad button {
  padding: 4px 10px;
  font-size: 11px;
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.05);
}
#rotpad button:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
}
#rotpad button.pill.on {
  background: var(--acc);
  color: #0b0c10;
  border-color: var(--acc);
}
#rotpad .rl {
  color: var(--mut);
  margin: 0 4px;
  font-weight: 500;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
#rotpad .sep {
  width: 1px;
  height: 14px;
  background: rgba(255, 255, 255, 0.1);
  margin: 0 4px;
}
#rotpad #angleval {
  min-width: 32px;
  text-align: right;
  font-family: monospace;
  color: var(--acc);
  font-weight: 600;
}
#panel {
  width: 350px;
  background: var(--panel);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.3);
  z-index: 5;
}
#panel h1 {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin: 0;
  padding: 16px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(135deg, #ffffff 0%, #a1a1aa 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
#spin {
  display: none;
  color: var(--acc);
  animation: pulse 1.5s infinite;
  font-size: 10px;
  margin-left: 8px;
}
@keyframes pulse {
  0% { opacity: 0.3; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.1); }
  100% { opacity: 0.3; transform: scale(0.9); }
}
details.sec {
  border-bottom: 1px solid var(--line);
  transition: background-color 0.2s ease;
}
details.sec:hover {
  background-color: rgba(255, 255, 255, 0.01);
}
details.sec > summary {
  padding: 12px 16px;
  color: var(--mut);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  cursor: pointer;
  user-select: none;
  list-style: none;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
details.sec > summary::-webkit-details-marker {
  display: none;
}
details.sec > summary::after {
  content: "";
  display: inline-block;
  width: 5px;
  height: 5px;
  border-right: 1.5px solid var(--mut);
  border-bottom: 1.5px solid var(--mut);
  transform: rotate(45deg);
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  margin-right: 4px;
}
details.sec[open] > summary::after {
  transform: rotate(-135deg);
}
details.sec[open] > summary {
  color: var(--fg);
}
details.sec .bd {
  padding: 0 16px 16px;
  animation: slideDown 0.25s cubic-bezier(0.4, 0, 0.2, 1) forwards;
  opacity: 0;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
label.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 10px 0 4px;
  font-size: 12px;
  font-weight: 500;
  color: #cbd5e1;
}
label.row .v {
  color: var(--acc);
  font-family: monospace;
  font-weight: 600;
  font-size: 11.5px;
}
input[type=text], select {
  width: 100%;
  padding: 8px 10px;
  background: #0b0c10;
  border: 1px solid #222631;
  border-radius: 6px;
  color: var(--fg);
  font-size: 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
input[type=text]:focus, select:focus {
  border-color: var(--acc);
  outline: none;
  box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.15);
}
button {
  background: #1c1e26;
  color: var(--fg);
  border: 1px solid #2d3345;
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
button:hover {
  background: #252a37;
  border-color: #3f475c;
}
button:active {
  transform: scale(0.97);
}
button.acc {
  background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
  color: #0b0c10;
  border: none;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.25);
}
button.acc:hover {
  background: linear-gradient(135deg, #fcd34d 0%, #fbbf24 100%);
  box-shadow: 0 6px 16px rgba(245, 158, 11, 0.35);
}
button.acc:active {
  transform: scale(0.97);
}
.btnrow {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.pill {
  padding: 5px 12px;
  border-radius: 20px;
  font-size: 11.5px;
  background: #1c1e26;
  border-color: #2d3345;
  color: var(--mut);
}
.pill:hover {
  color: var(--fg);
}
.pill.on {
  background: var(--acc);
  color: #0b0c10;
  border-color: var(--acc);
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(251, 191, 36, 0.25);
}
input[type=range] {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  height: 16px;
  margin: 2px 0 6px;
  cursor: pointer;
}
input[type=range]:focus {
  outline: none;
}
input[type=range]::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 2px;
  background: var(--line);
  border: none;
}
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 12px;
  height: 16px;
  margin-top: -6px;
  background: #ffffff;
  border: none;
  clip-path: polygon(0% 0%, 100% 0%, 100% 60%, 50% 100%, 0% 60%);
  filter: drop-shadow(0 1px 1.5px rgba(0,0,0,0.6));
  transition: transform 0.15s cubic-bezier(0.175, 0.885, 0.32, 1.275), background-color 0.15s;
}
input[type=range]:hover::-webkit-slider-thumb {
  transform: translateY(-1px) scale(1.15);
  background: var(--acc);
}
input[type=range]::-moz-range-track {
  height: 4px;
  border-radius: 2px;
  background: var(--line);
  border: none;
}
input[type=range]::-moz-range-thumb {
  width: 12px;
  height: 16px;
  background: #ffffff;
  border: none;
  clip-path: polygon(0% 0%, 100% 0%, 100% 60%, 50% 100%, 0% 60%);
  filter: drop-shadow(0 1px 1.5px rgba(0,0,0,0.6));
  transition: transform 0.15s, background-color 0.15s;
}
input[type=range]:hover::-moz-range-thumb {
  transform: translateY(-1px) scale(1.15);
  background: var(--acc);
}
#temp::-webkit-slider-runnable-track {
  background: linear-gradient(90deg, #3b82f6, #64748b 50%, #f59e0b) !important;
}
#tint::-webkit-slider-runnable-track {
  background: linear-gradient(90deg, #10b981, #64748b 50%, #d946ef) !important;
}
#saturation::-webkit-slider-runnable-track,
#vibrance::-webkit-slider-runnable-track,
#hsls::-webkit-slider-runnable-track {
  background: linear-gradient(90deg, #475569, #d97706) !important;
}
#exposure::-webkit-slider-runnable-track,
#gamma::-webkit-slider-runnable-track,
#highlights::-webkit-slider-runnable-track,
#shadows::-webkit-slider-runnable-track,
#whites::-webkit-slider-runnable-track,
#blacks::-webkit-slider-runnable-track,
#hsll::-webkit-slider-runnable-track,
#black_pct::-webkit-slider-runnable-track,
#white_pct::-webkit-slider-runnable-track,
#contrast::-webkit-slider-runnable-track {
  background: linear-gradient(90deg, #0f172a, #f8fafc) !important;
}
#hslh::-webkit-slider-runnable-track {
  background: linear-gradient(90deg, #ef4444, #f59e0b, #10b981, #06b6d4, #3b82f6, #8b5cf6, #ef4444) !important;
}
#files {
  max-height: 180px;
  overflow-y: auto;
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #0b0c10;
}
#files .fitem {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  font-size: 11.5px;
  color: #cbd5e1;
  border-bottom: 1px solid rgba(255, 255, 255, 0.02);
  transition: all 0.15s ease;
}
#files .fitem span {
  overflow: hidden;
  text-overflow: ellipsis;
}
#files .fitem:hover {
  background: rgba(255, 255, 255, 0.03);
  color: #ffffff;
}
#files .fitem.on {
  background: rgba(251, 191, 36, 0.08);
  color: var(--acc);
  font-weight: 600;
  border-left: 3px solid var(--acc);
  padding-left: 7px;
}
#files .fck {
  width: auto;
  margin: 0;
  accent-color: var(--acc);
  flex: none;
  cursor: pointer;
}
#hist {
  display: block;
  width: 260px;
  height: 84px;
  background: #0b0c10;
  border: 1px solid var(--line);
  border-radius: 6px;
  margin: 8px auto 0;
}
#curve {
  width: 100%;
  height: auto;
  background: #0b0c10;
  border: 1px solid var(--line);
  border-radius: 6px;
  margin-top: 8px;
  touch-action: none;
}
.hint {
  color: var(--mut);
  font-size: 11px;
  margin-top: 6px;
}
#status {
  padding: 10px 16px;
  color: var(--mut);
  font-size: 11.5px;
  min-height: 20px;
  border-top: 1px solid var(--line);
  background: rgba(0, 0, 0, 0.15);
}
#bprog {
  display: none;
  height: 4px;
  background: #0b0c10;
  border-radius: 2px;
  margin-top: 8px;
  overflow: hidden;
}
#bprog i {
  display: block;
  height: 100%;
  width: 0;
  background: linear-gradient(90deg, #fbbf24, #f59e0b);
  transition: width 0.2s;
}
#blog {
  font: 11px/1.4 monospace;
  color: var(--mut);
  max-height: 100px;
  overflow-y: auto;
  margin-top: 8px;
  white-space: pre-wrap;
  padding: 6px;
  background: #0b0c10;
  border-radius: 4px;
  border: 1px solid var(--line);
}
#helpmodal {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: none;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(8px);
  align-items: center;
  justify-content: center;
  padding: 24px;
}
#helpcard {
  background: var(--panel);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  max-width: 720px;
  max-height: 86vh;
  overflow-y: auto;
  padding: 24px 30px;
  position: relative;
  line-height: 1.65;
  box-shadow: 0 20px 50px rgba(0,0,0,0.5);
}
#helpcard h2 {
  margin: 0 0 12px;
  font-size: 20px;
  font-weight: 700;
  color: #fff;
}
#helpcard h3 {
  margin: 20px 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--acc);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
#helpcard p, #helpcard li {
  font-size: 12.5px;
  color: #cbd5e1;
  margin: 4px 0;
}
#helpcard ul {
  margin: 4px 0;
  padding-left: 20px;
}
#helpcard kbd {
  background: #0b0c10;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: monospace;
  font-size: 11px;
  color: var(--acc);
}
#helpclose {
  position: absolute;
  right: 16px;
  top: 16px;
  font-size: 24px;
  line-height: 1;
  background: none;
  border: none;
  color: var(--mut);
  cursor: pointer;
  padding: 4px;
  transition: color 0.2s;
}
#helpclose:hover {
  color: #fff;
}
#helpbtn {
  background: var(--acc);
  color: #0b0c10;
  font-weight: 700;
}
#empty {
  color: var(--mut);
  text-align: center;
  font-weight: 500;
}
#empty small {
  display: block;
  margin-top: 8px;
  opacity: 0.7;
}
#imgwrap {
  position: relative;
  display: none;
  background: #000;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.7);
  touch-action: none;
  user-select: none;
  border-radius: 4px;
  overflow: hidden;
}
#img {
  display: block;
  width: 100%;
  height: 100%;
}
#crop {
  position: absolute;
  box-sizing: border-box;
  border: var(--bz) dashed rgba(255,255,255,0.85);
  cursor: move;
  box-shadow: 0 0 0 4000px rgba(0, 0, 0, 0.6);
  outline: 1px solid rgba(0, 0, 0, 0.3);
}
#crop::before, #crop::after {
  content: "";
  position: absolute;
  pointer-events: none;
}
#crop::before {
  left: 33.33%;
  right: 33.33%;
  top: 0;
  bottom: 0;
  border-left: 1px dashed rgba(255, 255, 255, 0.25);
  border-right: 1px dashed rgba(255, 255, 255, 0.25);
}
#crop::after {
  top: 33.33%;
  bottom: 33.33%;
  left: 0;
  right: 0;
  border-top: 1px dashed rgba(255, 255, 255, 0.25);
  border-bottom: 1px dashed rgba(255, 255, 255, 0.25);
}
.h {
  position: absolute;
  width: var(--hz);
  height: var(--hz);
  background: #ffffff;
  border: 1px solid #111;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0,0,0,0.5);
}
.h[data-h=nw] { left: calc(var(--hz)/-2); top: calc(var(--hz)/-2); cursor: nwse-resize; }
.h[data-h=ne] { right: calc(var(--hz)/-2); top: calc(var(--hz)/-2); cursor: nesw-resize; }
.h[data-h=sw] { left: calc(var(--hz)/-2); bottom: calc(var(--hz)/-2); cursor: nesw-resize; }
.h[data-h=se] { right: calc(var(--hz)/-2); bottom: calc(var(--hz)/-2); cursor: nwse-resize; }
#cropdim {
  position: absolute;
  left: 0;
  top: -24px;
  font: 10px/1.2 monospace;
  font-weight: 600;
  color: var(--acc);
  background: rgba(11, 12, 16, 0.85);
  backdrop-filter: blur(4px);
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  border: 1px solid rgba(255,255,255,0.05);
}
#wbsel {
  position: absolute;
  box-sizing: border-box;
  border: 2px solid var(--acc);
  background: rgba(251, 191, 36, 0.12);
  display: none;
  pointer-events: none;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.5);
}
.ssel {
  position: absolute;
  box-sizing: border-box;
  display: none;
  pointer-events: none;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.5);
}
#basesel { border: 2px solid #fbbf24; background: rgba(251, 191, 36, 0.12); }
#shadowsel { border: 2px solid #3b82f6; background: rgba(59, 130, 246, 0.12); }
#hlsel { border: 2px solid #fbbf24; background: rgba(251, 191, 36, 0.08); }
.btn-icon {
  width: 14px;
  height: 14px;
  margin-right: 6px;
  stroke: currentColor;
  stroke-width: 2;
  fill: none;
  display: inline-block;
  vertical-align: middle;
}
</style>
</head>
<body>
<div id="stage">
  <div id="stagebar">
    <button id="helpbtn" title="功能说明">功能说明</button>
    <button id="fitbtn" title="恢复 1x 适合窗口">适合窗口</button>
    <button id="negbtn" title="按住显示原始负片（空格键同）">按住看负片</button>
    <span id="zoominfo"></span>
  </div>
  <div id="empty">← 右侧载入一张负片开始<br><small>支持 ARW/ARQ/CR2/NEF/TIF/JPG… · 滚轮缩放 · 双击 2x</small></div>
  <div id="rotpad">
    <button class="navbtn" id="previmg" title="上一张 (←)">‹</button>
    <select id="fileselect" title="选择底片"></select>
    <div class="rotgroup">
      <button id="autocrop" title="自动检测胶片画面区域并框选">Auto</button>
      <span class="sep"></span>
      <button id="rotL" title="左转 90°">↶</button>
      <button id="rotR" title="右转 90°">↷</button>
      <button class="pill" id="fliph" title="水平镜像 H">⇋</button>
      <button class="pill" id="flipv" title="垂直翻转 V">⇅</button>
      <span class="sep"></span>
      <span class="rl">拉直</span>
      <button id="rotm1" title="逆时针 1°">−1°</button>
      <button id="rotm01" title="逆时针 0.1°">−.1</button>
      <span id="angleval">0.0</span>°
      <button id="rotp01" title="顺时针 0.1°">+.1</button>
      <button id="rotp1" title="顺时针 1°">+1°</button>
      <button id="rot0" title="拉直归零">⟲</button>
    </div>
    <button class="navbtn" id="nextimg" title="下一张 (→)">›</button>
  </div>
  <div id="imgwrap"><img id="img">
    <div id="wbsel"></div>
    <div id="basesel" class="ssel"></div>
    <div id="shadowsel" class="ssel"></div>
    <div id="hlsel" class="ssel"></div>
    <div id="crop"><div id="cropdim"></div>
      <div class="h" data-h="nw"></div><div class="h" data-h="ne"></div>
      <div class="h" data-h="sw"></div><div class="h" data-h="se"></div>
    </div></div></div>
<div id="panel">
  <h1>胶片去色罩 · 可视化 <span id="spin">●</span></h1>

  <details class="sec" open><summary>选择底片</summary><div class="bd">
    <input type="text" id="dir" placeholder="文件夹或文件路径，回车列出">
    <div class="btnrow" style="margin-top:6px">
      <button id="pickdir" style="flex: 1;">
        <svg class="btn-icon" viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
        <span>选择文件夹</span>
      </button>
      <button id="pickfile" style="flex: 1;">
        <svg class="btn-icon" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
        <span>选择单张</span>
      </button></div>
    <div class="btnrow" style="margin-top:6px">
      <input type="text" id="filter" placeholder="过滤…" style="flex:1;width:auto">
      <button id="refresh">刷新</button></div>
    <div class="btnrow" style="margin-top:6px">
      <button class="pill" id="selall">全选</button>
      <button class="pill" id="selnone">清空</button></div>
    <div id="files"></div>
    <div class="hint" id="meta"></div>
  </div></details>

  <details class="sec" open><summary>直方图</summary><div class="bd">
    <canvas id="hist" width="260" height="84"></canvas>
  </div></details>

  <details class="sec" open><summary>模式与影调</summary><div class="bd">
    <div class="btnrow" id="modes">
      <button class="pill on" data-m="color">彩负</button>
      <button class="pill" data-m="bw">黑白</button>
      <button class="pill" data-m="positive">正片</button></div>
    <div class="btnrow" style="margin-top:6px">
      <button class="pill" id="ndtoggle" title="darktable negadoctor 负转正引擎（彩负模式）">negadoctor 引擎</button></div>
    <div id="ndrow" style="display:none">
      <label class="row">相纸反差 <span class="v" id="vnd_gamma"></span></label>
      <input type="range" id="nd_gamma" min="1" max="8" step="0.1">
      <label class="row">亮度增益 <span class="v" id="vnd_exposure"></span></label>
      <input type="range" id="nd_exposure" min="0.3" max="3" step="0.05"></div>
    <label class="row">曝光 EV <span class="v" id="vexposure"></span></label>
    <input type="range" id="exposure" min="-3" max="3" step="0.05">
    <label class="row">高光 <span class="v" id="vhighlights"></span></label>
    <input type="range" id="highlights" min="-100" max="100" step="1">
    <label class="row">阴影 <span class="v" id="vshadows"></span></label>
    <input type="range" id="shadows" min="-100" max="100" step="1">
    <label class="row">白色 <span class="v" id="vwhites"></span></label>
    <input type="range" id="whites" min="-100" max="100" step="1">
    <label class="row">黑色 <span class="v" id="vblacks"></span></label>
    <input type="range" id="blacks" min="-100" max="100" step="1">
    <label class="row">亮度 gamma <span class="v" id="vgamma"></span></label>
    <input type="range" id="gamma" min="0.6" max="3" step="0.05">
    <label class="row">对比度 <span class="v" id="vcontrast"></span></label>
    <input type="range" id="contrast" min="-0.5" max="0.6" step="0.02">
    <label class="row">饱和度 <span class="v" id="vsaturation"></span></label>
    <input type="range" id="saturation" min="0" max="1.6" step="0.05">
    <label class="row">鲜艳度 <span class="v" id="vvibrance"></span></label>
    <input type="range" id="vibrance" min="-100" max="100" step="1">
  </div></details>

  <details class="sec"><summary>曲线</summary><div class="bd">
    <div class="btnrow" id="curvech">
      <button class="pill on" data-c="rgb">RGB</button>
      <button class="pill" data-c="r">R</button>
      <button class="pill" data-c="g">G</button>
      <button class="pill" data-c="b">B</button>
      <button id="curvereset">重置本通道</button></div>
    <canvas id="curve" width="300" height="200" style="width:100%;height:auto;background:#141519;border:1px solid var(--line);border-radius:5px;margin-top:8px;touch-action:none"></canvas>
  </div></details>

  <details class="sec"><summary>HSL（八色）</summary><div class="bd">
    <div class="btnrow" id="hslchips"></div>
    <label class="row">色相 <span class="v" id="vhslh">0</span></label>
    <input type="range" id="hslh" min="-100" max="100" step="1" value="0">
    <label class="row">饱和度 <span class="v" id="vhsls">0</span></label>
    <input type="range" id="hsls" min="-100" max="100" step="1" value="0">
    <label class="row">明亮度 <span class="v" id="vhsll">0</span></label>
    <input type="range" id="hsll" min="-100" max="100" step="1" value="0">
    <div class="btnrow" style="margin-top:6px">
      <button id="hslreset">重置全部 HSL</button></div>
  </div></details>

  <details class="sec" open><summary>色彩 / 白点</summary><div class="bd">
    <label class="row" style="margin-top:2px">白平衡</label>
    <div class="btnrow"><button class="pill" id="wbgray">灰世界</button>
      <button class="pill" id="wbnone">不做</button></div>
    <label class="row">色温 <span class="v" id="vtemp"></span></label>
    <input type="range" id="temp" min="-100" max="100" step="1">
    <label class="row">色调 <span class="v" id="vtint"></span></label>
    <input type="range" id="tint" min="-100" max="100" step="1">
    <div class="btnrow" style="margin-top:8px">
      <button class="pill" id="wbpick" title="取色管框选中性灰/白，自动换成色温色调">
        <svg class="btn-icon" viewBox="0 0 24 24"><path d="m2 22 1-1h3l9-9"></path><path d="M3 21v-3l9-9"></path><path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4Z"></path></svg><span>取白点</span></button>
      <button id="wbclear" title="清除白点 / 复位色温色调">
        <svg class="btn-icon" style="margin-right:0" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
      <span class="hint" style="margin:auto 0" id="wbinfo">白点: 未设</span></div>
  </div></details>

  <details class="sec" open><summary>裁切画幅</summary><div class="bd">
    <div class="btnrow" id="fmts">
      <button class="pill on" data-f="free">自由</button>
      <button class="pill" data-f="135">135</button>
      <button class="pill" data-f="645">645</button>
      <button class="pill" data-f="66">6×6</button>
      <button class="pill" data-f="67">6×7</button>
      <button class="pill" data-f="69">6×9</button>
    </div>
    <div class="btnrow" style="margin-top:6px">
      <button class="pill on" id="oland">横 ▭</button>
      <button class="pill" id="oport">竖 ▯</button>
      <button id="cropfull">占满</button>
      <button id="cropreset">重置框</button></div>
  </div></details>

  <details class="sec"><summary>分区取样（片基 / 暗部 / 亮部）</summary><div class="bd">
    <div class="btnrow" style="margin-top:2px">
      <button class="pill" id="pbase" style="color:#e0a24a">框选片基</button>
      <button class="pill" id="pshadow" style="color:#5aa0ff">框选暗部</button>
      <button class="pill" id="phl" style="color:#ffe14a">框选亮部</button>
      <button id="sclear" title="清除取样">
        <svg class="btn-icon" style="margin-right:0" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button></div>
    <span class="hint" id="sinfo">取样: 未设</span>
  </div></details>


  <details class="sec" open><summary>降噪 / 锐化 / 晕影</summary><div class="bd">
    <label class="row">色度降噪 <span class="v" id="vdenoise"></span></label>
    <input type="range" id="denoise" min="0" max="12" step="1">
    <label class="row">锐化 <span class="v" id="vsharpen"></span></label>
    <input type="range" id="sharpen" min="0" max="3" step="0.1">
    <label class="row">晕影 <span class="v" id="vvignette"></span></label>
    <input type="range" id="vignette" min="-100" max="100" step="1">
    <label class="row" style="margin-top:6px"><input type="checkbox" id="raw_denoise" style="width:auto;margin-right:6px">RAW 阶段 FBDD 降噪</label>
  </div></details>

  <details class="sec"><summary>高级</summary><div class="bd">
    <label class="row">黑点% <span class="v" id="vblack_pct"></span></label>
    <input type="range" id="black_pct" min="0" max="3" step="0.1">
    <label class="row">白点% <span class="v" id="vwhite_pct"></span></label>
    <input type="range" id="white_pct" min="97" max="100" step="0.1">
  </div></details>

  <details class="sec"><summary>扫描件配色匹配</summary><div class="bd">
    <input type="text" id="ref" placeholder="参照图路径（同一张/同卷成品）">
    <div class="btnrow" style="margin-top:6px">
      <button id="pickref">选择…</button>
      <button class="pill" id="usematch">应用匹配</button>
      <button id="clearref">清除</button></div>
  </div></details>

  <details class="sec"><summary>预设（色调参数）</summary><div class="bd">
    <select id="presel"><option value="">— 选择预设即应用 —</option></select>
    <div class="btnrow" style="margin-top:6px">
      <input type="text" id="prename" placeholder="预设名" style="flex:1;width:auto">
      <button id="presave">存预设</button>
      <button id="predel">删预设</button></div>
  </div></details>

  <details class="sec" open><summary>导出</summary><div class="bd">
    <div class="btnrow">
      <input type="text" id="out" placeholder="输出路径（留空=原图旁 _pos）" style="flex:1;width:auto">
      <button id="pickout">选…</button></div>
    <div class="btnrow" style="margin:6px 0">
      <button class="pill on" id="ftif">TIF 16bit</button>
      <button class="pill" id="fjpg">JPG</button></div>
    <div id="qrow">
      <label class="row">JPG 质量 <span class="v" id="vquality">92</span></label>
      <input type="range" id="quality" min="60" max="100" step="1" value="92"></div>
    <label class="row">长边缩到（像素，空=原大）</label>
    <input type="text" id="resize" placeholder="如 3000">
    <button class="acc" id="export" style="width:100%;margin-top:8px">导出</button>
    <div class="btnrow" style="margin-top:6px">
      <button id="savepar" style="flex:1">保存参数</button>
      <button id="reset" style="flex:1">恢复默认</button></div>
    <button id="applyroll" style="width:100%;margin-top:6px">套用当前参数到整卷</button>
    <button id="wbroll" style="width:100%;margin-top:4px">仅把白平衡套整卷（保留各自裁切等）</button>
    <label class="row" style="margin-top:12px">批量导出（勾选的文件）</label>
    <div class="btnrow">
      <input type="text" id="batchout" placeholder="输出目录（留空=各自同目录/去色罩输出/）" style="flex:1;width:auto">
      <button id="pickbatch">选…</button></div>
    <label class="row" style="margin-top:4px"><span><input type="checkbox" id="usesaved" checked style="width:auto;margin-right:6px">优先用各自已存参数</span></label>
    <button id="batch" style="width:100%;margin-top:4px">批量导出</button>
    <div id="bprog"><i></i></div>
    <div id="blog"></div>
  </div></details>

  <details class="sec" open><summary>载入行为</summary><div class="bd">
    <label class="row"><span><input type="checkbox" id="resetdefault" style="width:auto;margin-right:6px">载入即重置为默认参数（不勾选＝恢复该图已存参数）</span></label>
  </div></details>
  <div id="status"></div>
</div>

<div id="helpmodal">
  <div id="helpcard">
    <button id="helpclose" title="关闭">×</button>
    <h2>功能说明</h2>
    <p>把数码翻拍的彩色负片去色罩、反转成正片。左侧预览边看边调，参数自动记忆并写入照片旁的 XML 边车。</p>

    <h3>载入与预览</h3>
    <ul>
      <li>左栏「选择底片」填文件夹或文件路径回车列出，点文件名载入。</li>
      <li>滚轮缩放，双击 2×，「适合窗口」复位，按住空格（或「按住看负片」）看原始负片。</li>
    </ul>

    <h3>裁切画幅</h3>
    <ul>
      <li><b>自动框</b>：自动检测胶片画面区域并框好（只框不旋转）。</li>
      <li>拖动裁切框四边/四角手动微调；可锁定 135 / 645 / 6×6 等画幅比例。</li>
      <li>「占满」= 全画幅，「重置框」= 回到默认留边。</li>
    </ul>

    <h3>方向（左下角浮层）</h3>
    <ul>
      <li>↶ ↷ 转 90°；⇋ 水平镜像、⇅ 垂直翻转。</li>
      <li>「拉直」按 ±1° / ±0.1° 微调倾斜，⟲ 归零；导出会自动内缩去掉旋转黑角。</li>
      <li>镜像 / 旋转时，裁切框与所有取样框会一起变换，修改不会错位。</li>
    </ul>

    <h3>模式与影调</h3>
    <ul>
      <li>模式：彩色负片 / 黑白负片 / 正片（反转片）。</li>
      <li>gamma、对比度、饱和度，以及曝光 / 高光 / 阴影 / 白色 / 黑色等细调。</li>
    </ul>

    <h3>色彩与白点</h3>
    <ul>
      <li>默认灰世界白平衡；色温 / 色调可手动偏移。</li>
      <li>「框选白点」：在图上圈出应为中性灰/白的区域，取框内平均色做白平衡。</li>
    </ul>

    <h3>分区取样（片基 / 暗部 / 亮部）</h3>
    <ul>
      <li>在图上框选覆盖自动色阶：<b style="color:#e0a24a">片基</b>定去色罩基准、<b style="color:#5aa0ff">暗部</b>定黑场、<b style="color:#ffe14a">亮部</b>定白场。</li>
      <li>都留空则走自动流程。</li>
    </ul>

    <h3>曲线 / HSL</h3>
    <ul>
      <li>曲线：空白处点击加点、拖动调整（端点只能上下）、双击删点。</li>
      <li>HSL：八个色区分别调色相/饱和/明度，加粗的色区表示已调整。</li>
    </ul>

    <h3>降噪 / 锐化 / 晕影</h3>
    <p>色度降噪去彩噪、亮度 USM 锐化、暗角。</p>

    <h3>扫描件配色匹配</h3>
    <p>给一张已调好的扫描件作参照，用直方图匹配把当前片子的色调 / 影调对齐过去（仅配色，不涉及裁切对齐）。开启后会覆盖上面的 gamma / 对比度 / 白平衡 / 饱和度。</p>

    <h3>预设与批量</h3>
    <ul>
      <li>预设只保存色调类参数（不含裁切 / 方向），与命令行 <kbd>--preset</kbd> 共用。</li>
      <li>「当前参数套整卷」把当前参数复制给整卷；「批量导出」按勾选文件导出，可优先用各自已存参数。</li>
    </ul>

    <h3>参数保存</h3>
    <p>调整后自动写入照片旁的 <kbd>&lt;文件名&gt;.decast.xml</kbd> 边车，随照片一起搬移；重新载入自动恢复。</p>

    <h3>快捷键</h3>
    <p><kbd>r</kbd> 右转 · <kbd>R</kbd> 左转 · <kbd>f</kbd> 镜像 · <kbd>e</kbd> 导出 · <kbd>空格</kbd> 按住看负片</p>
  </div>
</div>

<script>
const HJ={"Content-Type":"application/json"};
const D={crop:0,black_pct:0.5,white_pct:99.7,wb:"gray",gamma:1.8,contrast:0.08,
  saturation:1.0,denoise:0,rotate:0,flip:"h",level_angle:0,raw_denoise:false,use_match:false,
  negadoctor:false,nd_gamma:2.4,nd_exposure:1.0,
  mode:"color",temp:0,tint:0,sharpen:0,sharpen_radius:2.0,wb_point:null,wb_rect:null,
  film_base_rect:null,shadow_rect:null,highlight_rect:null,
  exposure:0,highlights:0,shadows:0,whites:0,blacks:0,vibrance:0,vignette:0,
  curve:null,curve_r:null,curve_g:null,curve_b:null,hsl:{}};
const dclone=o=>JSON.parse(JSON.stringify(o));  // D 里有嵌套对象，复制要用深拷贝
// 预设只保存这套「色调类」键（与 decast.PRESET_KEYS 一致）
const PKEYS=["black_pct","white_pct","wb","gamma","contrast","saturation",
  "temp","tint","sharpen","sharpen_radius","denoise","mode",
  "exposure","highlights","shadows","whites","blacks",
  "curve","curve_r","curve_g","curve_b","hsl","vibrance","vignette"];
let P=dclone(D), curFile=null, fmt="tif", timer=null, loaded=false;
const $=id=>document.getElementById(id);
const SL=["gamma","contrast","saturation","denoise","sharpen","black_pct","white_pct","temp","tint",
  "exposure","highlights","shadows","whites","blacks","vibrance","vignette",
  "nd_gamma","nd_exposure"];

// ---- 裁切框（比例坐标，可自由定位 + 画幅比例锁定）----
let cropN={x0:.06,y0:.06,x1:.94,y1:.94};
let curFmt="free", orient="land", aspect=null, fullW=0, fullH=0;
const FMT={free:null,"135":1.5,"645":4/3,"66":1,"67":1.25,"69":1.5};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function dispWH(){ return (P.rotate%180===0)?[fullW,fullH]:[fullH,fullW]; }
function imgAspect(){ const wh=dispWH(); return wh[1]? wh[0]/wh[1] : 1.5; }
function fitWrap(){
  const im=$("img"), st=$("stage");
  const a=(im.naturalWidth&&im.naturalHeight)?im.naturalWidth/im.naturalHeight:imgAspect();
  const availH=st.clientHeight-24-64;   // 顶部内边距 + 底部预留底栏
  let w=st.clientWidth-48, h=w/a; if(h>availH){h=availH;w=h*a;}
  const wr=$("imgwrap"); wr.style.width=w+"px"; wr.style.height=h+"px"; drawCrop(); drawWBRect(); drawSamples();
}
function drawCrop(){
  const c=$("crop");
  c.style.left=(cropN.x0*100)+"%"; c.style.top=(cropN.y0*100)+"%";
  c.style.width=((cropN.x1-cropN.x0)*100)+"%"; c.style.height=((cropN.y1-cropN.y0)*100)+"%";
  const wh=dispWH();
  $("cropdim").textContent=Math.round((cropN.x1-cropN.x0)*wh[0])+"×"+Math.round((cropN.y1-cropN.y0)*wh[1]);
}
function normalizedRect(a,b,minSize=0.015){
  let x0=clamp(Math.min(a.x,b.x),0,1), x1=clamp(Math.max(a.x,b.x),0,1);
  let y0=clamp(Math.min(a.y,b.y),0,1), y1=clamp(Math.max(a.y,b.y),0,1);
  if(x1-x0<minSize){const cx=(x0+x1)/2; x0=clamp(cx-minSize/2,0,1-minSize); x1=x0+minSize;}
  if(y1-y0<minSize){const cy=(y0+y1)/2; y0=clamp(cy-minSize/2,0,1-minSize); y1=y0+minSize;}
  return {x0:+x0.toFixed(4),y0:+y0.toFixed(4),x1:+x1.toFixed(4),y1:+y1.toFixed(4)};
}
function drawWBRect(rect){
  const r=rect||P.wb_rect, el=$("wbsel");
  if(!r){ el.style.display="none"; return; }
  el.style.display="block";
  el.style.left=(r.x0*100)+"%"; el.style.top=(r.y0*100)+"%";
  el.style.width=((r.x1-r.x0)*100)+"%"; el.style.height=((r.y1-r.y0)*100)+"%";
}
function applyFormat(name){
  curFmt=name; aspect=FMT[name]; if(aspect&&orient==="port") aspect=1/aspect;
  if(aspect){
    const r=aspect/imgAspect();
    let cx=(cropN.x0+cropN.x1)/2, cy=(cropN.y0+cropN.y1)/2;
    let h=cropN.y1-cropN.y0, w=h*r;
    if(w>1){w=1;h=w/r;} if(h>1){h=1;w=h*r;}
    let x0=clamp(cx-w/2,0,1-w), y0=clamp(cy-h/2,0,1-h);
    cropN={x0,y0,x1:x0+w,y1:y0+h};
  }
  drawCrop();
}
// 只同步画幅按钮高亮和 aspect 变量，不改动 cropN（恢复参数时用）
function syncFmtPills(){
  aspect=FMT[curFmt]||null; if(aspect&&orient==="port") aspect=1/aspect;
  document.querySelectorAll("#fmts button").forEach(b=>b.classList.toggle("on",b.dataset.f===curFmt));
  $("oland").classList.toggle("on",orient==="land");
  $("oport").classList.toggle("on",orient==="port");
}
function lockAspect(n,m){
  const r=aspect/imgAspect(); let w=n.x1-n.x0, h=w/r;
  if(m.includes("n")) n.y0=n.y1-h; else n.y1=n.y0+h;
  if(n.y0<-1e-6||n.y1>1+1e-6){
    if(m.includes("n")) n.y0=Math.max(0,n.y0); else n.y1=Math.min(1,n.y1);
    h=n.y1-n.y0; w=h*r;
    if(m.includes("w")) n.x0=n.x1-w; else n.x1=n.x0+w;
  }
  return n;
}

// ---- 预览缩放 / 平移（transform 作用在 imgwrap 上，裁切框随图缩放）----
let Z=1, TX=0, TY=0;
function applyTransform(){
  const wr=$("imgwrap");
  wr.style.transformOrigin="0 0";
  wr.style.transform="translate("+TX+"px,"+TY+"px) scale("+Z+")";
  // 手柄/边框/尺寸标签按 1/Z 反向缩放，视觉大小恒定
  document.documentElement.style.setProperty("--hz",(14/Z)+"px");
  document.documentElement.style.setProperty("--bz",(1/Z)+"px");
  $("cropdim").style.transform="scale("+(1/Z)+")";
  $("cropdim").style.transformOrigin="left bottom";
  $("zoominfo").textContent=Z>1.01?Z.toFixed(1)+"×":"";
}
function resetView(){ Z=1;TX=0;TY=0;applyTransform(); }
function zoomAt(cx,cy,z2){
  const r=$("imgwrap").getBoundingClientRect();
  const u=(cx-r.left)/r.width, v=(cy-r.top)/r.height;
  const W0=r.width/Z, H0=r.height/Z, Lx=r.left-TX, Ly=r.top-TY;
  z2=clamp(z2,1,8);
  TX=cx-Lx-u*W0*z2; TY=cy-Ly-v*H0*z2; Z=z2;
  if(Z<=1.001){TX=0;TY=0;Z=1;}
  applyTransform();
}
$("stage").addEventListener("wheel",e=>{
  if(!loaded) return; e.preventDefault();
  zoomAt(e.clientX,e.clientY,Z*Math.exp(-e.deltaY*0.0015));
},{passive:false});
$("imgwrap").addEventListener("dblclick",e=>{
  if(!loaded) return;
  if(Z>1) resetView(); else zoomAt(e.clientX,e.clientY,2);
});
$("fitbtn").onclick=resetView;

// ---- 取白点 ----
let pickWB=false, wbdrag=null;
function setPickWB(on){
  pickWB=on; $("wbpick").classList.toggle("on",on);
  $("imgwrap").style.cursor=on?"crosshair":"";
  if(on&&typeof pickS!=="undefined"&&pickS){ pickS=null;
    for(const k in SBTN) $(SBTN[k]).classList.remove("on"); }
  if(!on&&wbdrag){wbdrag=null; drawWBRect();}
}
$("wbpick").onclick=()=>setPickWB(!pickWB);
$("wbclear").onclick=()=>{P.wb_point=null;P.wb_rect=null;P.temp=0;P.tint=0;drawWBRect();refl();render();};

// ---- 引导取样：片基 / 暗部 / 亮部（拖框，覆盖自动色阶）----
let pickS=null, sdrag=null;
const SSEL={film_base_rect:"basesel",shadow_rect:"shadowsel",highlight_rect:"hlsel"};
const SBTN={film_base_rect:"pbase",shadow_rect:"pshadow",highlight_rect:"phl"};
const SNAME={film_base_rect:"片基",shadow_rect:"暗部",highlight_rect:"亮部"};
function setPickS(key){
  pickS=(pickS===key)?null:key;
  for(const k in SBTN) $(SBTN[k]).classList.toggle("on",pickS===k);
  if(pickS) setPickWB(false);
  $("imgwrap").style.cursor=pickS?"crosshair":"";
  if(!pickS&&sdrag){sdrag=null; drawSamples();}
}
function drawSbox(key,rect){
  const el=$(SSEL[key]), r=rect||P[key];
  if(!r){el.style.display="none";return;}
  el.style.display="block";
  el.style.left=(r.x0*100)+"%"; el.style.top=(r.y0*100)+"%";
  el.style.width=((r.x1-r.x0)*100)+"%"; el.style.height=((r.y1-r.y0)*100)+"%";
}
function drawSamples(){ for(const k in SSEL) drawSbox(k); }
function sInfo(){
  const set=Object.keys(SSEL).filter(k=>P[k]).map(k=>SNAME[k]);
  $("sinfo").textContent="取样: "+(set.length?set.join(" / "):"未设");
}
$("pbase").onclick=()=>setPickS("film_base_rect");
$("pshadow").onclick=()=>setPickS("shadow_rect");
$("phl").onclick=()=>setPickS("highlight_rect");
$("sclear").onclick=()=>{P.film_base_rect=P.shadow_rect=P.highlight_rect=null;
  drawSamples();sInfo();render();};

// ---- 裁切框拖拽 / 平移 / 取白点点击 ----
let drag=null;
function cropDown(e){
  const wr=$("imgwrap"), r=wr.getBoundingClientRect();
  if(pickWB){
    // 框选白点：拖出一个范围，后端取范围内平均色，避免噪点/颗粒导致单点不准
    const pt={x:clamp((e.clientX-r.left)/r.width,0,1),y:clamp((e.clientY-r.top)/r.height,0,1)};
    wbdrag={start:pt,cur:pt};
    drawWBRect(normalizedRect(pt,pt));
    wr.setPointerCapture(e.pointerId);
    e.preventDefault(); return;
  }
  if(pickS){
    const pt={x:clamp((e.clientX-r.left)/r.width,0,1),y:clamp((e.clientY-r.top)/r.height,0,1)};
    sdrag={start:pt,cur:pt};
    drawSbox(pickS,normalizedRect(pt,pt));
    wr.setPointerCapture(e.pointerId);
    e.preventDefault(); return;
  }
  const onCrop=!!(e.target.dataset&&e.target.dataset.h)||!!e.target.closest("#crop");
  if(Z>1&&!onCrop){
    // 放大状态下，在裁切框外按下 = 平移
    drag={mode:"pan",cx:e.clientX,cy:e.clientY,tx:TX,ty:TY,moved:false};
  }else{
    drag={mode:(e.target.dataset&&e.target.dataset.h)||"move",
      sx:(e.clientX-r.left)/r.width,sy:(e.clientY-r.top)/r.height,
      start:Object.assign({},cropN),moved:false};
  }
  wr.setPointerCapture(e.pointerId); e.preventDefault();
}
function cropMove(e){
  if(wbdrag){
    const wr=$("imgwrap"), r=wr.getBoundingClientRect();
    wbdrag.cur={x:clamp((e.clientX-r.left)/r.width,0,1),y:clamp((e.clientY-r.top)/r.height,0,1)};
    drawWBRect(normalizedRect(wbdrag.start,wbdrag.cur));
    e.preventDefault(); return;
  }
  if(sdrag){
    const wr=$("imgwrap"), r=wr.getBoundingClientRect();
    sdrag.cur={x:clamp((e.clientX-r.left)/r.width,0,1),y:clamp((e.clientY-r.top)/r.height,0,1)};
    drawSbox(pickS,normalizedRect(sdrag.start,sdrag.cur));
    e.preventDefault(); return;
  }
  if(!drag) return;
  if(drag.mode==="pan"){
    TX=drag.tx+(e.clientX-drag.cx); TY=drag.ty+(e.clientY-drag.cy);
    drag.moved=true; applyTransform(); return;
  }
  const wr=$("imgwrap"), r=wr.getBoundingClientRect();
  const dx=(e.clientX-r.left)/r.width-drag.sx, dy=(e.clientY-r.top)/r.height-drag.sy;
  if(Math.abs(dx)+Math.abs(dy)>1e-4) drag.moved=true;
  const s=drag.start; let n=Object.assign({},s);
  if(drag.mode==="move"){
    const w=s.x1-s.x0,h=s.y1-s.y0;
    n.x0=clamp(s.x0+dx,0,1-w); n.y0=clamp(s.y0+dy,0,1-h); n.x1=n.x0+w; n.y1=n.y0+h;
  }else{ const m=drag.mode;
    if(m.includes("w")) n.x0=clamp(s.x0+dx,0,s.x1-0.03);
    if(m.includes("e")) n.x1=clamp(s.x1+dx,s.x0+0.03,1);
    if(m.includes("n")) n.y0=clamp(s.y0+dy,0,s.y1-0.03);
    if(m.includes("s")) n.y1=clamp(s.y1+dy,s.y0+0.03,1);
    if(aspect) n=lockAspect(n,m);
  }
  cropN=n; drawCrop();
  render();  // 拖框实时渲染（合并请求，不排队）
}
function cropUp(){
  if(wbdrag){
    const r=normalizedRect(wbdrag.start,wbdrag.cur);
    wbdrag=null; setPickWB(false); drawWBRect();
    stat("采样中性灰…");
    // 框选中性灰 → 自动换算成 色温/色调 回填，不再单独存白点框
    fetch("/api/wbtemp",{method:"POST",headers:HJ,
      body:JSON.stringify(Object.assign({},P,{wb_rect:r,crop_rect:cropRect()}))})
      .then(x=>x.json()).then(d=>{
        if(d.ok){ P.temp=d.temp; P.tint=d.tint; P.wb_rect=null; P.wb_point=null;
          stat("白点→ 色温 "+d.temp+" / 色调 "+d.tint); }
        else stat("✗ "+d.err);
        drawWBRect(); refl(); render();
      });
    return;
  }
  if(sdrag){
    const key=pickS;
    P[key]=normalizedRect(sdrag.start,sdrag.cur);
    sdrag=null; setPickS(null);
    drawSbox(key); sInfo(); render();
    return;
  }
  if(drag){const need=drag.mode!=="pan"&&drag.moved; drag=null; if(need) render();}
}
function cropRect(){ return [cropN.x0,cropN.y0,cropN.x1,cropN.y1]; }

// ---- 曲线编辑器（单调 PCHIP，与后端算法一致）----
const CVCH=["rgb","r","g","b"], CVCOL={rgb:"#e6e7ea",r:"#ff5c54",g:"#60dc80",b:"#6090ff"};
let curCh="rgb", cvDrag=null;
const cvKey=ch=>ch==="rgb"?"curve":"curve_"+ch;
function getCv(ch){ const c=P[cvKey(ch)]; return c?c.map(p=>p.slice()):[[0,0],[1,1]]; }
function setCv(ch,pts){
  const isId=pts.length===2&&Math.abs(pts[0][0])<1e-6&&Math.abs(pts[0][1])<1e-6
    &&Math.abs(pts[1][0]-1)<1e-6&&Math.abs(pts[1][1]-1)<1e-6;
  P[cvKey(ch)]=isId?null:pts.map(p=>[+p[0].toFixed(4),+p[1].toFixed(4)]);
}
function pchipY(pts,x){
  const n=pts.length, xs=pts.map(p=>p[0]), ys=pts.map(p=>p[1]);
  if(x<=xs[0]) return ys[0]; if(x>=xs[n-1]) return ys[n-1];
  const h=[],d=[];
  for(let i=0;i<n-1;i++){h.push(Math.max(xs[i+1]-xs[i],1e-6));d.push((ys[i+1]-ys[i])/h[i]);}
  const m=new Array(n).fill(0);
  if(n===2){m[0]=m[1]=d[0];}
  else{
    m[0]=d[0]; m[n-1]=d[n-2];
    for(let i=1;i<n-1;i++){
      if(d[i-1]*d[i]<=0) m[i]=0;
      else{const w1=2*h[i]+h[i-1],w2=h[i]+2*h[i-1]; m[i]=(w1+w2)/(w1/d[i-1]+w2/d[i]);}
    }
    for(let i=0;i<n-1;i++){
      if(Math.abs(d[i])<1e-12){m[i]=0;m[i+1]=0;}
      else{const a=m[i]/d[i],b=m[i+1]/d[i],q=a*a+b*b;
        if(q>9){const t=3/Math.sqrt(q);m[i]=t*a*d[i];m[i+1]=t*b*d[i];}}
    }
  }
  let i=0; while(i<n-2&&x>xs[i+1]) i++;
  const t=(x-xs[i])/h[i];
  return clamp(ys[i]*(2*t*t*t-3*t*t+1)+m[i]*h[i]*(t*t*t-2*t*t+t)
    +ys[i+1]*(-2*t*t*t+3*t*t)+m[i+1]*h[i]*(t*t*t-t*t),0,1);
}
function cvXY(e){
  const cv=$("curve"), r=cv.getBoundingClientRect(), PAD=10;
  const x=(e.clientX-r.left)/r.width*cv.width, y=(e.clientY-r.top)/r.height*cv.height;
  return [clamp((x-PAD)/(cv.width-2*PAD),0,1), clamp(1-(y-PAD)/(cv.height-2*PAD),0,1)];
}
function drawCurve(){
  const cv=$("curve"), ctx=cv.getContext("2d"), PAD=10;
  const W=cv.width-2*PAD, H=cv.height-2*PAD;
  const X=x=>PAD+x*W, Y=y=>PAD+(1-y)*H;
  ctx.clearRect(0,0,cv.width,cv.height);
  ctx.lineWidth=1; ctx.strokeStyle="rgba(255,255,255,0.06)";
  for(let i=0;i<=4;i++){const g=i/4;
    ctx.beginPath();ctx.moveTo(X(g),Y(0));ctx.lineTo(X(g),Y(1));ctx.stroke();
    ctx.beginPath();ctx.moveTo(X(0),Y(g));ctx.lineTo(X(1),Y(g));ctx.stroke();}
  ctx.strokeStyle="rgba(255,255,255,0.15)";
  ctx.beginPath();ctx.moveTo(X(0),Y(0));ctx.lineTo(X(1),Y(1));ctx.stroke();
  for(const ch of CVCH){  // 其他有调整的通道淡显
    if(ch===curCh||!P[cvKey(ch)]) continue;
    const pts=getCv(ch);
    ctx.strokeStyle=CVCOL[ch]+"55"; ctx.beginPath();
    for(let i=0;i<=60;i++){const x=i/60,y=pchipY(pts,x); i?ctx.lineTo(X(x),Y(y)):ctx.moveTo(X(x),Y(y));}
    ctx.stroke();
  }
  const pts=getCv(curCh);
  ctx.strokeStyle=CVCOL[curCh]; ctx.lineWidth=1.8; ctx.beginPath();
  for(let i=0;i<=100;i++){const x=i/100,y=pchipY(pts,x); i?ctx.lineTo(X(x),Y(y)):ctx.moveTo(X(x),Y(y));}
  ctx.stroke();
  for(const p of pts){
    ctx.beginPath();
    ctx.arc(X(p[0]), Y(p[1]), 4.5, 0, Math.PI * 2);
    ctx.fillStyle = CVCOL[curCh];
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
  }
}
$("curve").addEventListener("pointerdown",e=>{
  const [x,y]=cvXY(e), pts=getCv(curCh);
  let idx=-1,best=0.06;
  pts.forEach((p,i)=>{const d=Math.hypot(p[0]-x,p[1]-y); if(d<best){best=d;idx=i;}});
  if(idx<0){ const np=[x,y]; pts.push(np); pts.sort((a,b)=>a[0]-b[0]); idx=pts.indexOf(np); }
  cvDrag={idx,pts}; setCv(curCh,pts); drawCurve();
  $("curve").setPointerCapture(e.pointerId); e.preventDefault();
});
$("curve").addEventListener("pointermove",e=>{
  if(!cvDrag) return;
  const [x,y]=cvXY(e), {idx,pts}=cvDrag;
  const last=pts.length-1;
  if(idx===0) pts[0][0]=0;                    // 端点只能上下动
  else if(idx===last) pts[last][0]=1;
  else pts[idx][0]=clamp(x,pts[idx-1][0]+0.02,pts[idx+1][0]-0.02);
  pts[idx][1]=y;
  setCv(curCh,pts); drawCurve();
  sched();  // 拖曲线点实时渲染
});
function cvUp(){ if(cvDrag){cvDrag=null; sched();} }
$("curve").addEventListener("pointerup",cvUp);
$("curve").addEventListener("pointercancel",cvUp);
$("curve").addEventListener("dblclick",e=>{
  const [x,y]=cvXY(e), pts=getCv(curCh);
  let idx=-1,best=0.06;
  pts.forEach((p,i)=>{const d=Math.hypot(p[0]-x,p[1]-y); if(d<best){best=d;idx=i;}});
  if(idx>0&&idx<pts.length-1){ pts.splice(idx,1); setCv(curCh,pts); drawCurve(); sched(); }
});
$("curvech").querySelectorAll("button[data-c]").forEach(b=>b.onclick=()=>{
  curCh=b.dataset.c;
  $("curvech").querySelectorAll("button[data-c]").forEach(x=>x.classList.toggle("on",x.dataset.c===curCh));
  drawCurve();
});
$("curvereset").onclick=()=>{ setCv(curCh,[[0,0],[1,1]]); drawCurve(); sched(); };

// ---- HSL 八色 ----
const HB=[["red","红","#e05252"],["orange","橙","#e0954a"],["yellow","黄","#d8cc4e"],
  ["green","绿","#6fbf5e"],["aqua","青","#4ec2c2"],["blue","蓝","#5a8ede"],
  ["purple","紫","#9a6ede"],["magenta","品","#d661b8"]];
let curBand="orange";
function buildChips(){
  const box=$("hslchips");
  HB.forEach(pair=>{
    const b=document.createElement("button");
    b.className="pill cband"; b.dataset.b=pair[0]; b.textContent=pair[1];
    b.style.borderBottom="3px solid "+pair[2];
    b.onclick=()=>{curBand=pair[0]; hslSync();};
    box.appendChild(b);
  });
}
function bandVals(k){ return (P.hsl&&P.hsl[k])||{}; }
function hslSync(){
  document.querySelectorAll("#hslchips .cband").forEach(b=>{
    b.classList.toggle("on",b.dataset.b===curBand);
    const v=bandVals(b.dataset.b);
    const adj=Math.abs(v.h||0)+Math.abs(v.s||0)+Math.abs(v.l||0)>0;
    b.style.fontWeight=adj?"700":"400"; b.style.opacity=adj?"1":".8";
  });
  const v=bandVals(curBand), map={hslh:"h",hsls:"s",hsll:"l"};
  for(const id in map){ $(id).value=v[map[id]]||0; $("v"+id).textContent=v[map[id]]||0; }
}
for(const pair of [["hslh","h"],["hsls","s"],["hsll","l"]]){
  $(pair[0]).addEventListener("input",e=>{
    if(!P.hsl) P.hsl={};
    const v=Object.assign({},P.hsl[curBand]); v[pair[1]]=parseFloat(e.target.value);
    if(!(v.h||0)&&!(v.s||0)&&!(v.l||0)) delete P.hsl[curBand]; else P.hsl[curBand]=v;
    $("v"+pair[0]).textContent=e.target.value; hslSync(); sched();
  });
}
$("hslreset").onclick=()=>{ P.hsl={}; hslSync(); sched(); };

// ---- 控件状态回显 ----
function refl(){
  for(const k of SL){ $(k).value=P[k]; $("v"+k).textContent=P[k]; }
  document.querySelectorAll("#modes button").forEach(b=>b.classList.toggle("on",b.dataset.m===P.mode));
  $("ndtoggle").classList.toggle("on",P.negadoctor);
  $("ndrow").style.display=P.negadoctor?"":"none";
  $("wbgray").classList.toggle("on",P.wb==="gray");
  $("wbnone").classList.toggle("on",P.wb==="none");
  $("fliph").classList.toggle("on",P.flip==="h");
  $("flipv").classList.toggle("on",P.flip==="v");
  $("usematch").classList.toggle("on",P.use_match);
  $("raw_denoise").checked=P.raw_denoise;
  $("ftif").classList.toggle("on",fmt==="tif");
  $("fjpg").classList.toggle("on",fmt==="jpg");
  $("qrow").style.display=fmt==="jpg"?"":"none";
  if(P.wb_rect){
    const wh=dispWH();
    $("wbinfo").textContent="白点框: "+Math.round((P.wb_rect.x1-P.wb_rect.x0)*wh[0])+"×"+Math.round((P.wb_rect.y1-P.wb_rect.y0)*wh[1]);
  }else{
    $("wbinfo").textContent=P.wb_point?("白点: "+P.wb_point.map(v=>v.toFixed(3)).join(", ")):"白点: 未设";
  }
  drawWBRect(); drawSamples(); sInfo(); updAngle();
  drawCurve(); hslSync();  // 曲线/HSL 编辑器随 P 同步（预设/记忆参数恢复时也会刷新）
}

// ---- 渲染 / 直方图 / 按住看负片 ----
// 实时渲染：不做防抖延迟。始终最多一个请求在飞，拖动期间的新调整只把
// rdirty 置位，上一帧一回来立刻用「最新参数」再渲——拖多快都不排队不卡死，
// 预览以服务器能跑的帧率实时跟手（后端还有分阶段缓存加速）。
let lastURL=null, negOn=false, inflight=false, rdirty=false;
function render(){
  if(!loaded) return;
  autosaveXml();                 // 参数一变就排一次自动保存（防抖+去重）
  if(inflight){ rdirty=true; return; }
  inflight=true; $("spin").style.display="inline";
  const body=Object.assign({},P,{crop_rect:cropRect()});
  fetch("/api/render",{method:"POST",headers:HJ,body:JSON.stringify(body)})
    .then(r=>{ if(!r.ok) throw new Error("render "+r.status); return r.blob(); })
    .then(b=>{
      const img=$("img");
      img.onload=()=>{ $("imgwrap").style.display="block"; $("empty").style.display="none"; fitWrap(); };
      const old=lastURL;
      lastURL=URL.createObjectURL(b);
      if(!negOn) img.src=lastURL;
      if(old) setTimeout(()=>URL.revokeObjectURL(old),2000);  // 释放旧帧，防内存涨
    })
    .catch(()=>{})
    .finally(()=>{
      inflight=false;
      if(rdirty){ rdirty=false; render(); }          // 拖动中：立刻渲下一帧
      else { $("spin").style.display="none"; fetchHist(); }  // 停下了才刷直方图
    });
}
function sched(){ render(); }
function fetchHist(){
  fetch("/api/hist").then(r=>r.json()).then(d=>{ if(d.ok) drawHist(d); }).catch(()=>{});
}
function drawHist(d){
  const cv=$("hist"), ctx=cv.getContext("2d");
  ctx.clearRect(0,0,cv.width,cv.height);
  ctx.fillStyle="#0b0c10"; ctx.fillRect(0,0,cv.width,cv.height);
  // Grid lines
  ctx.strokeStyle="rgba(255,255,255,0.05)"; ctx.lineWidth=1;
  for(let i=1;i<=3;i++){
    const x=i/4*cv.width; ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,cv.height); ctx.stroke();
  }
  const fillCols={r:"rgba(239,68,68,.18)",g:"rgba(16,185,129,.18)",b:"rgba(59,130,246,.18)"};
  const strokeCols={r:"rgba(239,68,68,.75)",g:"rgba(16,185,129,.75)",b:"rgba(59,130,246,.75)"};
  for(const k of ["r","g","b"]){
    const a=d[k]||[]; if(!a.length) continue;
    ctx.beginPath(); ctx.moveTo(0,cv.height);
    for(let i=0;i<a.length;i++){
      const x=(i+0.5)/a.length*cv.width;
      const y=cv.height-Math.log1p(a[i]*255)/Math.log(256)*(cv.height-4);
      ctx.lineTo(x,y);
    }
    ctx.lineTo(cv.width,cv.height); ctx.closePath();
    ctx.fillStyle=fillCols[k]; ctx.fill();
    // Stroke outline
    ctx.beginPath();
    for(let i=0;i<a.length;i++){
      const x=(i+0.5)/a.length*cv.width;
      const y=cv.height-Math.log1p(a[i]*255)/Math.log(256)*(cv.height-4);
      i?ctx.lineTo(x,y):ctx.moveTo(x,y);
    }
    ctx.strokeStyle=strokeCols[k]; ctx.lineWidth=1.2; ctx.stroke();
  }
}
function showNeg(on){
  if(!loaded||on===negOn) return; negOn=on;
  $("negbtn").classList.toggle("on",on);
  if(on){
    fetch("/api/render",{method:"POST",headers:HJ,
      body:JSON.stringify({rotate:P.rotate,flip:P.flip,negative_preview:true})})
      .then(r=>r.blob()).then(b=>{ if(negOn) $("img").src=URL.createObjectURL(b); });
  }else if(lastURL){ $("img").src=lastURL; }
}
for(const ev of ["pointerdown"]) $("negbtn").addEventListener(ev,()=>showNeg(true));
for(const ev of ["pointerup","pointercancel","pointerleave"]) $("negbtn").addEventListener(ev,()=>showNeg(false));

// ---- 参数控件事件 ----
for(const k of SL) $(k).addEventListener("input",e=>{
  P[k]=parseFloat(e.target.value); $("v"+k).textContent=P[k]; sched();});
document.querySelectorAll("#modes button").forEach(b=>b.onclick=()=>{
  P.mode=b.dataset.m;
  if(P.mode==="positive") P.wb="none";  // 正片默认不做白平衡（可再手动改回）
  refl(); render();});
$("wbgray").onclick=()=>{P.wb="gray";refl();render()};
$("wbnone").onclick=()=>{P.wb="none";refl();render()};
$("ndtoggle").onclick=()=>{P.negadoctor=!P.negadoctor;refl();render();};
// 镜像/旋转：裁切框 + 各取样框(白点/片基/暗部/亮部)一起变换；
// 镜像还翻转旋转角方向——让「对图片的所有修改」都跟着图一起走，不错位。
function rFlipH(r){ return r?{x0:1-r.x1,y0:r.y0,x1:1-r.x0,y1:r.y1}:r; }
function rFlipV(r){ return r?{x0:r.x0,y0:1-r.y1,x1:r.x1,y1:1-r.y0}:r; }
function rRotCW(r){ return r?{x0:1-r.y1,y0:r.x0,x1:1-r.y0,y1:r.x1}:r; }   // 90°顺
function rRotCCW(r){ return r?{x0:r.y0,y0:1-r.x1,x1:r.y1,y1:1-r.x0}:r; }  // 90°逆
function transformRegions(fn){
  cropN=fn(cropN)||cropN;
  for(const k of ["wb_rect","film_base_rect","shadow_rect","highlight_rect"]) if(P[k]) P[k]=fn(P[k]);
}
$("fliph").onclick=()=>{P.flip=P.flip==="h"?"none":"h"; transformRegions(rFlipH);
  P.level_angle=-(+P.level_angle||0); refl(); drawCrop(); render();};
$("flipv").onclick=()=>{P.flip=P.flip==="v"?"none":"v"; transformRegions(rFlipV);
  P.level_angle=-(+P.level_angle||0); refl(); drawCrop(); render();};
// 镜像会翻转"看到的旋转方向"，所以镜像时左右转要反向设 rotate，
// 让按钮永远按标注方向转所见的画面，裁切框也跟着对。
function mirrored(){ return P.flip==="h"||P.flip==="v"; }
$("rotL").onclick=()=>{ transformRegions(rRotCCW); P.rotate=(P.rotate+(mirrored()?90:270))%360;
  applyFormat(curFmt); refl(); render();};
$("rotR").onclick=()=>{ transformRegions(rRotCW); P.rotate=(P.rotate+(mirrored()?270:90))%360;
  applyFormat(curFmt); refl(); render();};
// 左下角旋转/拉直按钮
function updAngle(){ const el=$("angleval"); if(el) el.textContent=(+(P.level_angle||0)).toFixed(1); }
function nudgeAngle(d){ P.level_angle=clamp(Math.round(((+P.level_angle||0)+d)*10)/10,-45,45); updAngle(); render(); }
$("rotm1").onclick=()=>nudgeAngle(-1);
$("rotm01").onclick=()=>nudgeAngle(-0.1);
$("rotp01").onclick=()=>nudgeAngle(0.1);
$("rotp1").onclick=()=>nudgeAngle(1);
$("rot0").onclick=()=>{P.level_angle=0; updAngle(); render();};
// 功能说明弹窗
$("helpbtn").onclick=()=>{$("helpmodal").style.display="flex";};
$("helpclose").onclick=()=>{$("helpmodal").style.display="none";};
$("helpmodal").onclick=(e)=>{ if(e.target.id==="helpmodal") $("helpmodal").style.display="none"; };
$("raw_denoise").onchange=e=>{P.raw_denoise=e.target.checked;render()};
$("usematch").onclick=()=>{P.use_match=!P.use_match;refl();render()};
$("ftif").onclick=()=>{fmt="tif";refl()}; $("fjpg").onclick=()=>{fmt="jpg";refl()};
$("quality").addEventListener("input",e=>{$("vquality").textContent=e.target.value;});
$("reset").onclick=()=>{P=dclone(D);refl();render()};

// 裁切框：拖动 / 缩放 / 画幅比例 / 横竖 / 自动框 / 占满 / 重置
$("imgwrap").addEventListener("pointerdown",cropDown);
$("imgwrap").addEventListener("pointermove",cropMove);
$("imgwrap").addEventListener("pointerup",cropUp);
$("imgwrap").addEventListener("pointercancel",cropUp);
$("fmts").querySelectorAll("button").forEach(b=>b.onclick=()=>{
  $("fmts").querySelectorAll("button").forEach(x=>x.classList.remove("on"));
  b.classList.add("on"); applyFormat(b.dataset.f); render();});
$("oland").onclick=()=>{orient="land";$("oland").classList.add("on");$("oport").classList.remove("on");applyFormat(curFmt);render();};
$("oport").onclick=()=>{orient="port";$("oport").classList.add("on");$("oland").classList.remove("on");applyFormat(curFmt);render();};
$("cropfull").onclick=()=>{cropN={x0:0,y0:0,x1:1,y1:1}; aspect?applyFormat(curFmt):drawCrop(); render();};
$("cropreset").onclick=()=>{cropN={x0:.06,y0:.06,x1:.94,y1:.94}; aspect?applyFormat(curFmt):drawCrop(); render();};
$("autocrop").onclick=()=>{
  if(!loaded){stat("先载入图片");return;}
  stat("自动检测画面区域…");
  // 只框画面，不自动旋转（旋转用左下角按钮手动调，更可控）
  fetch("/api/autocrop",{method:"POST",headers:HJ,
    body:JSON.stringify({rotate:P.rotate,flip:P.flip,level:false})}).then(r=>r.json()).then(d=>{
      if(!d.ok){stat("✗ "+d.err);return;}
      const[x0,y0,x1,y1]=d.rect; cropN={x0,y0,x1,y1};
      curFmt="free"; syncFmtPills(); drawCrop(); render();
      stat("已自动框选画面");});
};
window.addEventListener("resize",()=>{ if(loaded) fitWrap(); });

// ---- 文件列表：列出 / 过滤 / 刷新 / 勾选 ----
function fillFiles(files){
  const box=$("files"); box.innerHTML="";
  const sel=$("fileselect"); sel.innerHTML="";
  files.forEach(f=>{
    const el=document.createElement("div"); el.className="fitem"; el.dataset.path=f;
    const cb=document.createElement("input"); cb.type="checkbox"; cb.className="fck";
    cb.onclick=e=>e.stopPropagation();
    const sp=document.createElement("span"); sp.textContent=f.split("/").pop(); sp.title=f;
    el.appendChild(cb); el.appendChild(sp);
    el.onclick=()=>loadFile(f);
    box.appendChild(el);
    const op=document.createElement("option"); op.value=f; op.textContent=f.split("/").pop(); sel.appendChild(op);
  });
  applyFilter(); updateNavButtons();
}
// 底栏选片：下拉 + 上一张/下一张（走整卷文件顺序）
function navFile(step){
  const opts=[...$("fileselect").options]; if(!opts.length) return;
  let idx=opts.findIndex(o=>o.value===curFile);
  idx = idx<0 ? (step>0?0:opts.length-1) : idx+step;
  if(idx<0||idx>=opts.length) return;
  loadFile(opts[idx].value);
}
function updateNavButtons(){
  const opts=[...$("fileselect").options]; const idx=opts.findIndex(o=>o.value===curFile);
  $("previmg").disabled = idx<=0;
  $("nextimg").disabled = idx<0 || idx>=opts.length-1;
}
$("fileselect").onchange=e=>{ if(e.target.value) loadFile(e.target.value); };
$("previmg").onclick=()=>navFile(-1);
$("nextimg").onclick=()=>navFile(1);
function applyFilter(){
  const q=$("filter").value.trim().toLowerCase();
  document.querySelectorAll("#files .fitem").forEach(el=>{
    el.style.display=(!q||el.dataset.path.toLowerCase().includes(q))?"":"none";});
}
function listFiles(dir){
  fetch("/api/list"+(dir?"?dir="+encodeURIComponent(dir):"")).then(r=>r.json()).then(d=>{
    fillFiles(d.files); stat(d.files.length+" 个文件");});
}
$("filter").addEventListener("input",applyFilter);
$("refresh").onclick=()=>listFiles($("dir").value.trim());

// ---- macOS 原生选择框（服务端 osascript 弹窗）----
function pick(mode,cb){
  stat("等待系统选择框…（可能弹在浏览器窗口后面）");
  fetch("/api/pick?mode="+mode).then(r=>r.json()).then(d=>{
    if(d.ok){ stat(""); cb(d.path); } else stat(d.err||"已取消");
  }).catch(()=>stat("选择失败"));
}
$("pickdir").onclick=()=>pick("dir",p=>{$("dir").value=p;listFiles(p);});
$("pickfile").onclick=()=>pick("file",p=>{$("dir").value=p;loadFile(p);});
$("pickref").onclick=()=>pick("file",p=>{$("ref").value=p;REFLOADED=false;});
$("pickout").onclick=()=>pick("save",p=>{$("out").value=p;});
$("pickbatch").onclick=()=>pick("dir",p=>{$("batchout").value=p;});
$("selall").onclick=()=>{document.querySelectorAll("#files .fitem").forEach(el=>{
  if(el.style.display!=="none") el.querySelector(".fck").checked=true;});};
$("selnone").onclick=()=>{document.querySelectorAll("#files .fck").forEach(c=>c.checked=false);};
$("dir").addEventListener("keydown",e=>{ if(e.key!=="Enter")return;
  const v=e.target.value.trim();
  if(v && /\.(arw|arq|cr2|cr3|nef|raf|dng|rw2|tif|tiff|png|jpg|jpeg)$/i.test(v)){ loadFile(v); return;}
  listFiles(v);
});

// ---- 载入 + 每张图参数记忆 ----
function loadFile(path){
  stat("解码中… "+path.split("/").pop());
  fetch("/api/load",{method:"POST",headers:HJ,
    body:JSON.stringify({path,raw_denoise:P.raw_denoise})}).then(r=>r.json()).then(d=>{
      if(!d.ok){stat("✗ "+d.err);return;}
      curFile=path; loaded=true; fullW=d.w; fullH=d.h; $("rotpad").style.display="flex";
      $("meta").textContent=d.name+" · "+d.w+"×"+d.h;
      $("fileselect").value=path;                       // 同步底栏下拉与列表高亮
      [...document.querySelectorAll("#files .fitem")].forEach(c=>c.classList.toggle("on",c.dataset.path===path));
      updateNavButtons();
      resetView();
      const applyRestore=(sd,label)=>{
        if(sd){
          if(sd.P) P=Object.assign(dclone(D),sd.P);
          if(sd.cropN) cropN=Object.assign({},sd.cropN);
          if(sd.curFmt!==undefined){curFmt=sd.curFmt||"free"; orient=sd.orient||"land";}
          stat("已载入（恢复自"+label+"）");
        }else{
          P=dclone(D);                    // 重置为默认（含 flip:h），不沿用上一张
          cropN={x0:.06,y0:.06,x1:.94,y1:.94}; curFmt="free"; orient="land";
          if(aspect) applyFormat(curFmt);
          stat("已载入（默认参数）");
        }
        syncFmtPills(); refl(); drawCrop();
        lastSavedSig=settingsSig();   // 先记基线，避免刚载入未改动就误写边车
        render();
      };
      if($("resetdefault").checked){    // 开关：每张一律用默认参数
        applyRestore(null); return;
      }
      // 否则优先读挨着照片的 XML 边车；没有再退回内部 JSON 记忆
      fetch("/api/sidecar?path="+encodeURIComponent(path)).then(r=>r.json()).then(sc=>{
        if(sc.ok&&sc.data){ applyRestore(sc.data,"XML 边车"); return; }
        fetch("/api/settings?path="+encodeURIComponent(path)).then(r=>r.json()).then(s=>{
          applyRestore(s.ok&&s.data?s.data:null,"记忆参数");
        });
      });
    });
}
function saveSettings(path,silent){
  if(!path) return;
  fetch("/api/settings",{method:"POST",headers:HJ,
    body:JSON.stringify({path:path,data:currentSettings()})})
    .then(r=>r.json()).then(d=>{ if(!silent) stat(d.ok?"✓ 参数已保存":"✗ "+d.err); });
}
function currentSettings(){
  return {P:P,cropN:cropN,curFmt:curFmt,orient:orient};
}
// ---- 调整参数后自动存 XML 边车（挨着照片，随照片一起搬移）----
let lastSavedSig=null, xmlTimer=null;
function settingsSig(){ return JSON.stringify(currentSettings()); }
function autosaveXml(){
  if(!curFile) return;
  const sig=settingsSig();
  if(sig===lastSavedSig) return;           // 和上次保存的一样，不重复写
  clearTimeout(xmlTimer);
  xmlTimer=setTimeout(()=>{
    const data=currentSettings(), sig2=JSON.stringify(data);
    if(sig2===lastSavedSig) return;    // 期间基线已更新（如刚载入），不写
    fetch("/api/sidecar",{method:"POST",headers:HJ,
      body:JSON.stringify({path:curFile,data})}).then(r=>r.json()).then(d=>{
        if(d.ok){ lastSavedSig=sig2; stat("✓ 调整已自动存 XML"); }});
    // 顺带同步内部 JSON 记忆，保证「应用到整卷」等也拿到最新
    fetch("/api/settings",{method:"POST",headers:HJ,
      body:JSON.stringify({path:curFile,data})});
  }, 900);
}
$("savepar").onclick=()=>{ if(!curFile){stat("先载入图片");return;} saveSettings(curFile,false); };
$("applyroll").onclick=async()=>{
  if(!curFile){stat("先载入图片并调好参数");return;}
  let items=[...document.querySelectorAll("#files .fitem")].filter(el=>el.querySelector(".fck").checked);
  if(!items.length) items=[...document.querySelectorAll("#files .fitem")].filter(el=>el.style.display!=="none");
  if(!items.length){stat("当前列表没有文件");return;}
  const scope=[...document.querySelectorAll("#files .fitem")].some(el=>el.querySelector(".fck").checked)?"勾选文件":"当前列表";
  if(!confirm("把当前完整参数套用到"+scope+"的 "+items.length+" 张？")) return;
  const data=currentSettings();
  let ok=0;
  for(const el of items){
    try{
      const r=await fetch("/api/settings",{method:"POST",headers:HJ,
        body:JSON.stringify({path:el.dataset.path,data:data})});
      const d=await r.json();
      if(d.ok) ok++;
    }catch(_){}
  }
  stat("整卷参数已保存："+ok+"/"+items.length);
};
// 只把当前白平衡（色温/色调/白平衡模式）套给整卷，各自裁切/影调等保留
$("wbroll").onclick=async()=>{
  if(!curFile){stat("先调好白平衡");return;}
  let items=[...document.querySelectorAll("#files .fitem")].filter(el=>el.querySelector(".fck").checked);
  if(!items.length) items=[...document.querySelectorAll("#files .fitem")].filter(el=>el.style.display!=="none");
  if(!items.length){stat("当前列表没有文件");return;}
  if(!confirm("把当前白平衡（色温 "+P.temp+" / 色调 "+P.tint+"）套给 "+items.length+" 张？各自裁切/其它参数保留")) return;
  const wb={temp:P.temp,tint:P.tint,wb:P.wb};
  let ok=0;
  for(const el of items){
    const f=el.dataset.path;
    try{
      let data=null;
      const sc=await(await fetch("/api/sidecar?path="+encodeURIComponent(f))).json();
      if(sc.ok&&sc.data) data=sc.data;
      else{ const s=await(await fetch("/api/settings?path="+encodeURIComponent(f))).json(); if(s.ok&&s.data) data=s.data; }
      if(!data) data={P:dclone(D),cropN:{x0:.06,y0:.06,x1:.94,y1:.94},curFmt:"free",orient:"land"};
      if(!data.P) data.P={};
      Object.assign(data.P,wb);
      await fetch("/api/sidecar",{method:"POST",headers:HJ,body:JSON.stringify({path:f,data})});
      await fetch("/api/settings",{method:"POST",headers:HJ,body:JSON.stringify({path:f,data})});
      ok++;
    }catch(_){}
  }
  stat("整卷白平衡已套用："+ok+"/"+items.length+"（重新载入生效）");
};

// ---- 参照匹配 ----
$("usematch").addEventListener("mousedown",()=>{ const v=$("ref").value.trim();
  if(v && !REFLOADED){ fetch("/api/loadref",{method:"POST",headers:HJ,
    body:JSON.stringify({path:v})}).then(r=>r.json()).then(d=>{REFLOADED=d.ok;
      stat(d.ok?"参照已载入":"✗ "+d.err);
      if(d.ok&&P.use_match) render();  // 参照载入完成后补一次渲染，避免首次点击时还没生效
    });}
});
let REFLOADED=false;
$("ref").addEventListener("change",()=>{REFLOADED=false;});
$("clearref").onclick=()=>{P.use_match=false;REFLOADED=false;$("ref").value="";
  fetch("/api/loadref",{method:"POST",headers:HJ,body:JSON.stringify({path:""})});
  refl();render();};

// ---- 预设 ----
function loadPresets(sel){
  fetch("/api/presets").then(r=>r.json()).then(d=>{
    const s=$("presel"); s.innerHTML='<option value="">— 选择预设即应用 —</option>';
    (d.names||[]).forEach(n=>{const o=document.createElement("option");o.value=n;o.textContent=n;s.appendChild(o);});
    if(sel) s.value=sel;});
}
$("presel").onchange=()=>{ const n=$("presel").value; if(!n) return;
  fetch("/api/presets?name="+encodeURIComponent(n)).then(r=>r.json()).then(d=>{
    if(!d.ok){stat("✗ "+d.err);return;}
    for(const k of PKEYS) if(d.data[k]!==undefined)
      P[k]=(d.data[k]&&typeof d.data[k]==="object")?dclone(d.data[k]):d.data[k];
    refl(); render(); stat("已应用预设："+n);});};
$("presave").onclick=()=>{
  const n=($("prename").value.trim()||$("presel").value);
  if(!n){stat("先输入预设名");return;}
  const data={}; for(const k of PKEYS) data[k]=P[k];
  fetch("/api/presets",{method:"POST",headers:HJ,body:JSON.stringify({name:n,data:data})})
    .then(r=>r.json()).then(d=>{stat(d.ok?"✓ 预设已保存："+n:"✗ "+d.err); loadPresets(n);});};
$("predel").onclick=()=>{ const n=$("presel").value;
  if(!n){stat("先在下拉里选一个预设");return;}
  fetch("/api/presets?name="+encodeURIComponent(n),{method:"DELETE"})
    .then(r=>r.json()).then(d=>{stat(d.ok?"✓ 已删除预设："+n:"✗ "+d.err); loadPresets();});};

// ---- 导出（单张 / 批量）----
function exportOpts(){
  return {format:fmt,bits:16,quality:parseInt($("quality").value,10)||92,
    resize:parseInt($("resize").value||"0",10)||0};
}
$("export").onclick=()=>{ if(!loaded){stat("先载入图片");return;}
  const body=Object.assign({},P,{crop_rect:cropRect(),out:$("out").value.trim()},exportOpts());
  stat("导出中（全分辨率）…");
  fetch("/api/export",{method:"POST",headers:HJ,
    body:JSON.stringify(body)}).then(r=>r.json()).then(d=>{
      if(d.ok){stat("✓ 已导出："+d.out); saveSettings(curFile,true);}  // 导出成功自动记忆参数
      else stat("✗ "+d.err);});
};
function blog(t){ const l=$("blog"); l.textContent+=t+"\n"; l.scrollTop=l.scrollHeight; }
let batchBusy=false, batchCancel=false;
$("batch").onclick=async()=>{
  if(batchBusy){ batchCancel=true; $("batch").textContent="取消中…"; return; }  // 运行中再点=取消
  const items=[...document.querySelectorAll("#files .fitem")].filter(el=>el.querySelector(".fck").checked);
  if(!items.length){stat("先在文件列表里勾选文件");return;}
  const outdir=$("batchout").value.trim();
  const useSaved=$("usesaved").checked;
  const bar=$("bprog"); bar.style.display="block"; bar.firstElementChild.style.width="0%";
  $("blog").textContent="";
  batchBusy=true; batchCancel=false;
  const bbtn=$("batch"); bbtn.textContent="取消导出"; bbtn.style.background="#c0392b"; bbtn.style.color="#fff";
  let done=0, okc=0;
  for(const el of items){
    if(batchCancel){ blog("⏹ 已取消，剩余未导出"); break; }
    const f=el.dataset.path;
    try{
      // 参数：优先各自已存记忆，否则用当前面板参数
      let params=Object.assign({},P), rect=cropRect();
      if(useSaved){
        const s=await(await fetch("/api/settings?path="+encodeURIComponent(f))).json();
        if(s.ok&&s.data){
          if(s.data.P) params=Object.assign(dclone(D),s.data.P);
          if(s.data.cropN){const c=s.data.cropN; rect=[c.x0,c.y0,c.x1,c.y1];}
        }
      }
      const ld=await(await fetch("/api/load",{method:"POST",headers:HJ,
        body:JSON.stringify({path:f})})).json();
      if(!ld.ok) throw new Error(ld.err||"载入失败");
      // 输出目录：留空 = 各源文件同目录/去色罩输出/（服务端自动建目录）
      const out=outdir? outdir.replace(/\/?$/,"/") : f.replace(/\/[^/]*$/,"/")+"去色罩输出/";
      const body=Object.assign({},params,{crop_rect:rect,out:out},exportOpts());
      const ex=await(await fetch("/api/export",{method:"POST",headers:HJ,
        body:JSON.stringify(body)})).json();
      if(!ex.ok) throw new Error(ex.err||"导出失败");
      okc++; blog("✓ "+f.split("/").pop()+" → "+ex.out);
    }catch(err){ blog("✗ "+f.split("/").pop()+"："+err.message); }
    done++; bar.firstElementChild.style.width=(done/items.length*100)+"%";
    stat("批量导出 "+done+"/"+items.length+"…");
  }
  batchBusy=false;
  const bbtn2=$("batch"); bbtn2.textContent="批量导出"; bbtn2.style.background=""; bbtn2.style.color="";
  stat((batchCancel?"已取消，":"批量完成：")+okc+"/"+done+" 导出，共 "+items.length+" 张");
  // 服务端缓存已换到最后一张，把当前显示的重新载回来
  if(curFile) fetch("/api/load",{method:"POST",headers:HJ,body:JSON.stringify({path:curFile})});
};

// ---- 快捷键（输入框聚焦时忽略）----
window.addEventListener("keydown",e=>{
  if($("helpmodal").style.display==="flex"){ if(e.key==="Escape") $("helpmodal").style.display="none"; return; }
  const t=e.target.tagName;
  if(t==="INPUT"||t==="TEXTAREA"||t==="SELECT") return;
  if(e.key===" "){ e.preventDefault(); if(!e.repeat) showNeg(true); return; }
  if(e.key==="r") $("rotR").click();
  else if(e.key==="R") $("rotL").click();
  else if(e.key==="f") $("fliph").click();
  else if(e.key==="e") $("export").click();
  else if(e.key==="ArrowLeft"){ e.preventDefault(); navFile(-1); }
  else if(e.key==="ArrowRight"){ e.preventDefault(); navFile(1); }
});
window.addEventListener("keyup",e=>{ if(e.key===" ") showNeg(false); });

function stat(t){$("status").textContent=t;}
// 启动：列默认目录 + 预设列表 + HSL 色区按钮
listFiles("");
loadPresets();
buildChips();
refl();
applyTransform();
</script></body></html>"""


def daemonize(logpath):
    """双 fork + setsid，彻底脱离控制终端与进程组，成为独立后台进程。"""
    if os.fork() > 0:
        os._exit(0)          # 父进程立即退出，命令即刻返回
    os.setsid()              # 新会话，脱离原进程组
    if os.fork() > 0:
        os._exit(0)          # 再 fork，确保不是会话首进程
    sys.stdout.flush(); sys.stderr.flush()
    with open(os.devnull, "r") as nul:
        os.dup2(nul.fileno(), 0)
    lf = open(logpath, "a", buffering=1)
    os.dup2(lf.fileno(), 1)
    os.dup2(lf.fileno(), 2)


def main():
    global START_DIRS
    ap = argparse.ArgumentParser(description="去色罩工具 · 可视化网页界面")
    ap.add_argument("dirs", nargs="*", help="起始目录（可多个），默认列常用目录")
    ap.add_argument("--port", type=int, default=8765,
                    help="监听端口，默认 8765")
    ap.add_argument("--daemon", action="store_true",
                    help="转入后台运行（日志写到 gui.log）")
    a = ap.parse_args()
    dirs = [os.path.abspath(d) for d in a.dirs if os.path.isdir(d)]
    if dirs:
        START_DIRS = dirs
    else:
        cand = ["/Users/apple/Pictures/胶片扫描", "/Users/apple/Downloads",
                os.path.expanduser("~/Pictures")]
        START_DIRS = [c for c in cand if os.path.isdir(c)]
    if a.daemon:
        daemonize(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.log"))
    print("起始目录:", START_DIRS)
    print(f"在浏览器打开: http://127.0.0.1:{a.port}")
    app.run(host="127.0.0.1", port=a.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

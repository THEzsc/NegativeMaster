"""High resolution contact sheets from already developed positive images.

Coordinates in the JSON configuration are logical pixels at a 2400 px width.
Photographs and film perforations are separate layers: the holes really reveal
the chosen background, including its alpha channel. Edge lettering is an
editable typographic approximation, never a claim to the maker's exact font.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from math import ceil, cos, isfinite, radians, sin
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

BASE_WIDTH = 2400
MAX_PIXELS = 80_000_000
FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
DEFAULT_CONFIG = {
    "width": 2400, "columns": 6, "ratio": "3:2", "spacing": 28, "margin": 90,
    "background": {"mode": "blur", "color": "#e8e5dc", "color2": "#1b2f34", "angle": 45,
                   "blur": 30, "brightness": .7, "sourceIndex": 0},
    "strip": {"color": "#080808", "opacity": 1, "sprockets": True, "edgeText": None,
              "secondaryText": None, "edgeColor": None, "fontStyle": "auto", "leader": True,
              "startNumber": 1, "reverseNumbers": False, "frameGap": 12, "padding": 8,
              "showNumbers": True, "showHalfNumbers": True, "fit": "contain",
              "edgeScale": 1, "edgeTracking": 0},
    "header": {"enabled": True, "title": "", "roll": "", "camera": "", "lens": "",
               "date": "", "process": "", "notes": "", "color": "#ffffff",
               "textColor": "#171717", "height": 180},
    "frameOverrides": [], "watermark": "",
}


def _number(value: Any, name: str, low: float, high: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}必须是数字") from None
    if not isfinite(out) or not low <= out <= high:
        raise ValueError(f"{name}须在 {low:g} 至 {high:g} 之间")
    return out


def _color(value: Any, fallback: str = "#080808") -> tuple[int, int, int, int]:
    try:
        return ImageColor.getcolor(str(value if value is not None else fallback), "RGBA")
    except (ValueError, TypeError):
        raise ValueError(f"颜色格式无效：{str(value)[:40]}") from None


def normalize_config(config: dict | None) -> dict:
    """Return a validated copy; do not copy a potentially large custom image."""
    source = config or {}
    if not isinstance(source, dict):
        raise ValueError("排版设置须为对象")
    c = deepcopy(DEFAULT_CONFIG)
    for key, value in source.items():
        if key == "_backgroundImage":
            c[key] = value
        elif key in ("background", "strip", "header"):
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"{key}设置须为对象")
            c[key].update(value or {})
        else:
            c[key] = deepcopy(value)
    c["width"] = round(_number(c["width"], "输出宽度", 1200, 10000))
    c["columns"] = round(_number(c["columns"], "每行张数", 2, 12))
    c["margin"] = _number(c["margin"], "画布边距", 0, 400)
    c["spacing"] = _number(c["spacing"], "行间距", 0, 300)
    if c["ratio"] not in ("3:2", "4:3", "1:1", "original"):
        raise ValueError("画幅比例须为 3:2、4:3、1:1 或 original")
    bg, strip, header = c["background"], c["strip"], c["header"]
    if bg["mode"] not in ("blur", "solid", "gradient", "transparent"):
        raise ValueError("背景模式无效")
    bg["blur"] = _number(bg["blur"], "背景模糊", 0, 200)
    bg["brightness"] = _number(bg["brightness"], "背景亮度", 0, 2)
    bg["angle"] = _number(bg["angle"], "渐变角度", -360, 360)
    strip["opacity"] = _number(strip["opacity"], "胶片不透明度", 0, 1)
    strip["frameGap"] = _number(strip["frameGap"], "画格间隔", 0, 100)
    strip["padding"] = _number(strip["padding"], "画格内边距", 0, 40)
    strip["edgeScale"] = _number(strip["edgeScale"], "边字大小", .6, 1.8)
    strip["edgeTracking"] = _number(strip["edgeTracking"], "边字字距", 0, 3)
    strip["startNumber"] = round(_number(strip["startNumber"], "起始格号", -999, 9999))
    header["height"] = _number(header["height"], "顶栏高度", 130, 400)
    if strip["fontStyle"] not in ("auto", "dot", "mono", "condensed"):
        raise ValueError("边字字体样式无效")
    if strip["fit"] not in ("contain", "cover"):
        raise ValueError("照片填充方式无效")
    if not isinstance(c["frameOverrides"], list):
        raise ValueError("逐张调整须为列表")
    for color in (bg["color"], bg["color2"], strip["color"], header["color"], header["textColor"]):
        _color(color)
    return c


@dataclass(frozen=True)
class SheetLayout:
    width: int
    height: int
    columns: int
    rows: int
    margin: int
    spacing: int
    header_height: int
    leader: bool
    cell_width: float
    aperture_width: int
    aperture_height: int
    band: int
    strip_height: int
    gap: int
    scale: float

    @property
    def top(self) -> int:
        return self.margin + (self.header_height + self.spacing if self.header_height else 0)

    def row_y(self, row: int) -> int:
        return self.top + row * (self.strip_height + self.spacing)


def sheet_layout(count: int, config: dict | None = None) -> SheetLayout:
    c = normalize_config(config)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("请先选择至少一张照片")
    if count > 1000:
        raise ValueError("一次最多排版 1000 张照片，请分成多张联系印样")
    width, columns = c["width"], c["columns"]
    scale = width / BASE_WIDTH
    margin, spacing = round(c["margin"] * scale), round(c["spacing"] * scale)
    available = width - 2 * margin
    cell = available / columns
    gap = round(c["strip"]["frameGap"] * scale)
    aperture_w = round(cell - gap)
    if aperture_w < 24:
        raise ValueError("画格太窄，请减少列数、边距或画格间隔")
    aspect = {"3:2": 1.5, "4:3": 4 / 3, "1:1": 1, "original": 1.5}[c["ratio"]]
    aperture_h = round(aperture_w / aspect)
    # 135: 38 mm frame pitch, 35 mm film width, 24 mm picture height.
    # Nonstandard picture ratios retain the same perforation pitch/bands.
    band = max(12, round(cell * 5.5 / 38))
    strip_h = aperture_h + 2 * band
    leader = bool(c["strip"]["leader"])
    rows = ceil(count / columns) + int(leader)
    header_h = round(c["header"]["height"] * scale) if c["header"]["enabled"] else 0
    footer = round(45 * scale) if c.get("watermark") else 0
    height = 2 * margin + header_h + (spacing if header_h else 0) + rows * strip_h + (rows - 1) * spacing + footer
    if width * height > MAX_PIXELS:
        mp = width * height / 1_000_000
        raise ValueError(f"当前画布约 {mp:.1f} 百万像素，超过 80 百万像素上限。请减小输出宽度、增加每行张数或减少照片。")
    return SheetLayout(width, height, columns, rows, margin, spacing, header_h, leader,
                       cell, aperture_w, aperture_h, band, strip_h, gap, scale)


def sheet_size(count: int, config: dict | None = None) -> tuple[int, int]:
    layout = sheet_layout(count, config)
    return layout.width, layout.height


@lru_cache(maxsize=160)
def _font(style: str, size: int, text: str = "") -> ImageFont.FreeTypeFont:
    size = max(1, int(size))
    # Use the OS's licensed CJK font for multilingual headers without bundling it.
    if any(ord(ch) > 255 for ch in text):
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/msyh.ttc",
        ]
    else:
        candidates = []
    filename = {"condensed": "BarlowCondensed-Medium.ttf", "mono": "IBMPlexMono-Regular.ttf",
                "header": "BarlowCondensed-SemiBold.ttf"}.get(style, "IBMPlexMono-Regular.ttf")
    candidates += [str(FONT_DIR / filename), "DejaVuSans.ttf"]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


# Drawn 5 × 7 dots reproduce the dot-matrix *style*. These are our own glyphs,
# not extracted from or attributed as a manufacturer's proprietary typeface.
_DOT = {
    "A": (14,17,17,31,17,17,17), "B": (30,17,17,30,17,17,30),
    "C": (14,17,16,16,16,17,14), "D": (30,17,17,17,17,17,30),
    "E": (31,16,16,30,16,16,31), "F": (31,16,16,30,16,16,16),
    "G": (14,17,16,23,17,17,15), "H": (17,17,17,31,17,17,17),
    "I": (31,4,4,4,4,4,31), "J": (7,2,2,2,18,18,12),
    "K": (17,18,20,24,20,18,17), "L": (16,16,16,16,16,16,31),
    "M": (17,27,21,21,17,17,17), "N": (17,25,21,19,17,17,17),
    "O": (14,17,17,17,17,17,14), "P": (30,17,17,30,16,16,16),
    "Q": (14,17,17,17,21,18,13), "R": (30,17,17,30,20,18,17),
    "S": (15,16,16,14,1,1,30), "T": (31,4,4,4,4,4,4),
    "U": (17,17,17,17,17,17,14), "V": (17,17,17,17,17,10,4),
    "W": (17,17,17,21,21,21,10), "X": (17,17,10,4,10,17,17),
    "Y": (17,17,10,4,4,4,4), "Z": (31,1,2,4,8,16,31),
    "0": (14,17,19,21,25,17,14), "1": (4,12,4,4,4,4,14),
    "2": (14,17,1,2,4,8,31), "3": (30,1,1,14,1,1,30),
    "4": (2,6,10,18,31,2,2), "5": (31,16,16,30,1,1,30),
    "6": (14,16,16,30,17,17,14), "7": (31,1,2,4,8,8,8),
    "8": (14,17,17,14,17,17,14), "9": (14,17,17,15,1,1,14),
    "-": (0,0,0,31,0,0,0), ".": (0,0,0,0,0,12,12),
    "/": (1,1,2,4,8,16,16), ":": (0,12,12,0,12,12,0),
    "+": (0,4,4,31,4,4,0), " ": (0,0,0,0,0,0,0),
}


def _text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: int,
          fill: tuple, style: str = "mono", max_width: float | None = None,
          tracking: float = 0) -> None:
    text = str(text or "")[:250]
    if not text:
        return
    if style == "dot" and all(ch.upper() in _DOT for ch in text):
        unit = max(.1, size / 7)
        if max_width:
            measured = unit * (len(text) * 6 - 1) + tracking * (len(text)-1)
            if measured > max_width:
                shrink = max_width / measured
                unit, tracking = unit * shrink, tracking * shrink
        # Subpixel dots are antialiased by the final high-resolution export.
        x, y = xy
        radius = max(.35, unit * .36)
        for ch in text.upper():
            for row, bits in enumerate(_DOT[ch]):
                for col in range(5):
                    if bits & (1 << (4 - col)):
                        cx, cy = x + col * unit + unit / 2, y + row * unit + unit / 2
                        if unit < 1.5:
                            draw.point((int(cx), int(cy)), fill=fill)
                        else:
                            draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=fill)
            x += unit * 6 + tracking
        return
    font = _font(style, size, text)
    if max_width is not None:
        measured = (sum(draw.textlength(ch,font=font) for ch in text) + tracking*(len(text)-1)
                    if tracking else draw.textlength(text,font=font))
        if measured > max_width:
            shrink = max_width / measured
            font = _font(style, max(1, round(size * shrink)), text)
            tracking *= shrink
            def measured_width():
                return (sum(draw.textlength(ch,font=font) for ch in text)+tracking*(len(text)-1)
                        if tracking else draw.textlength(text,font=font))
            while measured_width() > max_width and len(text) > 1:
                text = text[:-2] + "…"
    if tracking:
        x,y=xy
        # Stable baseline keeps punctuation and uppercase glyphs aligned when
        # letter spacing requires drawing individual characters.
        baseline=y-font.getbbox(text,anchor="ls")[1]
        for ch in text:
            draw.text((x,baseline),ch,font=font,fill=fill,anchor="ls")
            x+=draw.textlength(ch,font=font)+tracking
    else:
        draw.text(xy, text, font=font, fill=fill, anchor="lt")


def _cover(source: Image.Image, size: tuple[int, int], override: dict | None = None,
           fit: str = "cover", padding: int = 0) -> Image.Image:
    """Fit positive pixels, with normalized crop center and an optional zoom."""
    o = override if isinstance(override, dict) else {}
    rotation = _number(o.get("rotation", 0), "单张旋转", -360, 360)
    photo = ImageOps.exif_transpose(source)
    if rotation % 360:
        photo = photo.rotate(-rotation, Image.Resampling.BICUBIC, expand=True)
    crop = o.get("crop") or {}
    if not isinstance(crop, dict):
        raise ValueError("单张裁剪设置须为对象")
    cx = _number(crop.get("x", .5), "裁剪中心 X", 0, 1)
    cy = _number(crop.get("y", .5), "裁剪中心 Y", 0, 1)
    zoom = _number(crop.get("scale", 1), "裁剪放大", 1, 8)
    mode = o.get("fit", fit)
    if mode not in ("contain", "cover"):
        raise ValueError("单张照片填充方式无效")
    tw, th = max(1, size[0] - 2 * padding), max(1, size[1] - 2 * padding)
    sw, sh = photo.size
    if mode == "cover":
        ratio = tw / th
        crop_w, crop_h = (sh * ratio, sh) if sw / sh > ratio else (sw, sw / ratio)
    else:
        crop_w, crop_h = sw, sh
    crop_w, crop_h = crop_w / zoom, crop_h / zoom
    left, top = min(max(0, cx * sw - crop_w / 2), sw - crop_w), min(max(0, cy * sh - crop_h / 2), sh - crop_h)
    bounds = (left, top, left + crop_w, top + crop_h)
    if mode == "cover":
        out = photo.convert("RGBA").resize((tw, th), Image.Resampling.LANCZOS, box=bounds)
    else:
        cut = photo.crop(tuple(round(v) for v in bounds))
        out = ImageOps.contain(cut.convert("RGBA"), (tw, th), Image.Resampling.LANCZOS)
    window = Image.new("RGBA", size, (0, 0, 0, 0))
    window.alpha_composite(out, ((size[0] - out.width) // 2, (size[1] - out.height) // 2))
    return window


def _background(images: list[Image.Image], c: dict, size: tuple[int, int]) -> Image.Image:
    bg = c["background"]
    color1, color2 = _color(bg["color"]), _color(bg["color2"])
    if bg["mode"] == "transparent":
        return Image.new("RGBA", size, (0, 0, 0, 0))
    if bg["mode"] == "solid":
        return Image.new("RGBA", size, color1)
    if bg["mode"] == "gradient":
        # A bounded working buffer avoids allocating several 80 MP float arrays.
        import numpy as np
        sw, sh = 512, max(2, min(1024, round(512 * size[1] / size[0])))
        xx, yy = np.meshgrid(np.linspace(-.5, .5, sw), np.linspace(-.5, .5, sh))
        angle = radians(bg["angle"])
        dx, dy = cos(angle), sin(angle)
        span = max(.001, abs(dx) + abs(dy))
        t = np.clip((xx * dx + yy * dy) / span + .5, 0, 1)[..., None]
        pixels = np.asarray(color1) * (1-t) + np.asarray(color2) * t
        return Image.fromarray(np.rint(pixels).astype("uint8"), "RGBA").resize(size, Image.Resampling.BICUBIC)
    custom = c.get("_backgroundImage")
    if custom is not None and not isinstance(custom, Image.Image):
        raise ValueError("自定义背景必须为有效图片")
    if custom is not None:
        photo = custom
    else:
        try:
            index = int(bg["sourceIndex"])
        except (ValueError, TypeError):
            index = 0
        photo = images[max(0, min(len(images)-1, index))]
    working = (min(size[0], 1000), max(1, round(size[1] * min(size[0], 1000) / size[0])))
    # Very tall sheets only need low spatial detail in a blurred background.
    if working[1] > 2400:
        working = (max(1, round(working[0] * 2400 / working[1])), 2400)
    result = ImageOps.fit(ImageOps.exif_transpose(photo).convert("RGB"), working, Image.Resampling.LANCZOS)
    result = result.filter(ImageFilter.GaussianBlur(bg["blur"] * working[0] / BASE_WIDTH))
    result = ImageEnhance.Brightness(result).enhance(bg["brightness"])
    return result.resize(size, Image.Resampling.BICUBIC).convert("RGBA")


def _film_layer(layout: SheetLayout, c: dict, cells: int, leader: bool = False) -> Image.Image:
    strip = c["strip"]
    width = round(layout.cell_width * cells)
    color = _color(strip["color"])
    alpha = round(color[3] * strip["opacity"])
    row = Image.new("RGBA", (width, layout.strip_height), (*color[:3], alpha))
    draw = ImageDraw.Draw(row)
    if strip["sprockets"]:
        pitch = layout.cell_width / 8
        hw, hh = layout.cell_width * 1.98 / 38, layout.cell_width * 2.79 / 38
        # Text is outside the holes, toward the two outer edges.
        hole_y = layout.band * .45
        for i in range(cells * 8):
            x = (i + .5) * pitch
            for y in (hole_y, layout.strip_height - hole_y - hh):
                draw.rounded_rectangle((x-hw/2, y, x+hw/2, y+hh), radius=max(1, hw*.18), fill=(0,0,0,0))
    return row


def _clip_leader(row: Image.Image) -> None:
    """Apply the leader outline after its panels and lettering are drawn."""
    h, w = row.height, row.width
    mask = Image.new("L", row.size, 0)
    md = ImageDraw.Draw(mask)
    p0, p1, p2, p3 = (w*.79,0), (w*.845,0), (w*.84,h*.47), (w*.90,h*.47)
    curve = []
    for i in range(65):
        t=i/64; u=1-t
        curve.append((u**3*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*p3[0],
                      u**3*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*p3[1]))
    md.polygon([(0,0),p0,*curve,(w,h*.47),(w,h),(0,h)], fill=255)
    from PIL import ImageChops
    row.putalpha(ImageChops.multiply(row.getchannel("A"), mask))


def _edge_labels(row: Image.Image, layout: SheetLayout, c: dict, stock: dict,
                 indices: list[int], count: int, leader: bool = False) -> None:
    strip = c["strip"]
    style = strip["fontStyle"]
    if style == "auto":
        style = stock.get("font_style", "condensed")
    if style not in ("dot", "condensed", "mono"):
        style = "condensed"
    primary = strip["edgeText"] if strip["edgeText"] is not None else stock.get("edge_text", stock.get("name", ""))
    secondary = strip["secondaryText"] if strip["secondaryText"] is not None else stock.get("edge_secondary", "")
    edge_color = _color(strip["edgeColor"] or stock.get("edge_color", "#d6ac63"))
    edge_color = (*edge_color[:3], round(edge_color[3] * strip["opacity"]))
    draw = ImageDraw.Draw(row)
    fs = max(1, round(layout.cell_width * .026 * strip["edgeScale"]))
    # Extra inter-character advance is in logical px at the 2400 px master.
    tracking = strip["edgeTracking"] * layout.scale
    outer = max(1, round(layout.cell_width * .007))
    for cell, index in enumerate(indices):
        x = cell * layout.cell_width + layout.gap / 2
        edge = secondary if secondary and cell % 2 else primary
        if not leader or cell < max(1, layout.columns-1):
            _text(draw, (x, outer), edge, fs, edge_color, style, layout.cell_width*.84, tracking)
        if not strip["showNumbers"] or leader:
            continue
        number = strip["startNumber"] + (count-1-index if strip["reverseNumbers"] else index)
        override = c["frameOverrides"][index] if index < len(c["frameOverrides"]) else {}
        label = str(override.get("label", number) if isinstance(override, dict) else number)
        number_y = layout.strip_height - outer - fs
        _text(draw, (x + layout.cell_width*.10, number_y), label, fs, edge_color, style, layout.cell_width*.38, tracking)
        if strip["showHalfNumbers"]:
            _text(draw, (x + layout.cell_width*.60, number_y), label+"A", fs, edge_color, style, layout.cell_width*.35, tracking)


def _header(canvas: Image.Image, layout: SheetLayout, c: dict, stock: dict) -> None:
    if not layout.header_height:
        return
    header, s = c["header"], layout.scale
    x, y, w, h = layout.margin, layout.margin, layout.width-2*layout.margin, layout.header_height
    draw = ImageDraw.Draw(canvas)
    fill, ink = _color(header["color"]), _color(header["textColor"])
    draw.rectangle((x,y,x+w-1,y+h-1),fill=fill)
    pad, icon = round(28*s), round(54*s)
    # Archival camera mark, deliberately no decorative/fake QR code.
    ix, iy = x+pad, y+round((h-icon)/2)
    lw = max(1,round(3*s))
    draw.rectangle((ix,iy+icon*.15,ix+icon,iy+icon*.9),outline=ink,width=lw)
    draw.rectangle((ix+icon*.18,iy,ix+icon*.58,iy+icon*.18),fill=ink)
    draw.ellipse((ix+icon*.27,iy+icon*.31,ix+icon*.73,iy+icon*.77),outline=ink,width=lw)
    tx, content_w = ix+icon+round(30*s), w-icon-3*pad-round(30*s)
    title = str(header.get("title") or stock.get("name") or "")
    roll = str(header.get("roll") or "")
    title_w = content_w * (.70 if roll else 1)
    _text(draw,(tx,y+round(23*s)),title,round(31*s),ink,"header",title_w)
    if roll:
        _text(draw,(tx+content_w*.74,y+round(30*s)),"ROLL  "+roll,round(20*s),ink,"mono",content_w*.26)
    ry=y+round(min(74,header["height"]*.41)*s)
    rule=tuple(round(ink[i]*.25+fill[i]*.75) for i in range(3))+(fill[3],)
    draw.line((tx,ry,x+w-pad,ry),fill=rule,width=max(1,round(s)))
    fields=[]
    for key,label in (("camera","CAMERA"),("lens","LENS"),("date","DATE"),("process","PROCESS")):
        value=header.get(key) or (stock.get("process") if key=="process" else "")
        if value:
            fields.append((label,str(value)))
    if fields:
        column_w=content_w/len(fields)
        for i,(label,value) in enumerate(fields):
            fx=tx+i*column_w
            _text(draw,(fx,ry+round(15*s)),label,round(13*s),ink,"mono",column_w-round(15*s))
            _text(draw,(fx,ry+round(37*s)),value,round(21*s),ink,"header",column_w-round(15*s))
    notes=str(header.get("notes") or "")
    if notes:
        _text(draw,(tx,y+h-round(28*s)),notes,round(16*s),ink,"mono",content_w)


def render_sheet(images: list[Image.Image], config: dict | None = None,
                 stock: dict | None = None) -> Image.Image:
    """Render an RGBA poster; source images must already be positive photographs.

    `frameOverrides[i]` accepts label, clockwise rotation, fit and
    crop={x:0..1,y:0..1,scale:1..8}. `ratio=original` uses 3:2 film windows
    and contain by default. `_backgroundImage` is an optional in-memory PIL
    image and must not be serialized into a saved JSON preset.
    """
    if not isinstance(images, (list, tuple)) or not images:
        raise ValueError("请先选择至少一张照片")
    if any(not isinstance(im, Image.Image) or min(im.size)<1 for im in images):
        raise ValueError("照片列表中包含无效图片")
    c = normalize_config(config)
    stock = stock if isinstance(stock,dict) else {}
    layout = sheet_layout(len(images),c)
    canvas = _background(images,c,(layout.width,layout.height))
    _header(canvas,layout,c,stock)
    row_index = 0
    if layout.leader:
        leader = _film_layer(layout,c,layout.columns,True)
        # Empty exposed leader panels mimic the start of a roll; this row does
        # not consume photographs or advance their frame numbers.
        draw = ImageDraw.Draw(leader)
        for i in range(max(1,layout.columns-1)):
            px=round(i*layout.cell_width+layout.gap/2)
            leader_alpha=round(255*c["strip"]["opacity"])
            color=(13,12,10,leader_alpha) if i<layout.columns-2 else (228,226,218,leader_alpha)
            draw.rectangle((px,layout.band,px+layout.aperture_width-1,layout.band+layout.aperture_height-1),fill=color)
        _edge_labels(leader,layout,c,stock,list(range(layout.columns)),len(images),True)
        _clip_leader(leader)
        canvas.alpha_composite(leader,(layout.margin,layout.row_y(0)))
        row_index=1
    for first in range(0,len(images),layout.columns):
        indices=list(range(first,min(first+layout.columns,len(images))))
        row = _film_layer(layout,c,len(indices))
        for col,index in enumerate(indices):
            override=c["frameOverrides"][index] if index<len(c["frameOverrides"]) else {}
            fit="contain" if c["ratio"]=="original" else c["strip"]["fit"]
            photo=_cover(images[index],(layout.aperture_width,layout.aperture_height),override,fit,
                         round(c["strip"]["padding"]*layout.scale))
            px=round(col*layout.cell_width+layout.gap/2)
            row.alpha_composite(photo,(px,layout.band))
        _edge_labels(row,layout,c,stock,indices,len(images))
        canvas.alpha_composite(row,(layout.margin,layout.row_y(row_index)))
        row_index+=1
    watermark=c.get("watermark")
    if isinstance(watermark,dict):
        watermark=watermark.get("text","")
    if watermark:
        draw=ImageDraw.Draw(canvas)
        _text(draw,(layout.margin,layout.height-layout.margin-round(20*layout.scale)),str(watermark),
              round(18*layout.scale),_color(c["header"]["textColor"]),"mono",layout.width-2*layout.margin)
    return canvas

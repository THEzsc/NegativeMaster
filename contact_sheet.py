"""High resolution contact sheets from already developed positive images.

Coordinates in the JSON configuration are logical pixels at a 2400 px width.
Photographs and film perforations are separate layers: the holes really reveal
the chosen background, including its alpha channel. Edge lettering is an
editable typographic approximation, never a claim to the maker's exact font.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
from math import ceil, cos, isfinite, radians, sin
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from film_effects import EXPOSURE_STYLES, exposure_field

EDGE_STYLES = ("dot", "mono", "condensed", "citaro", "citaro-tall",
               "film-dot", "film-stamp", "film-rvp", "film-phoenix", "film-kodak", "film-cine")

BASE_WIDTH = 2400
MAX_PIXELS = 80_000_000
FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
DEFAULT_CONFIG = {
    "width": 2400, "columns": 6, "ratio": "3:2", "spacing": 28, "margin": 90,
    "background": {"mode": "blur", "color": "#e8e5dc", "color2": "#1b2f34", "angle": 45,
                   "blur": 30, "brightness": .7, "sourceIndex": 0, "opacity": 1},
    "strip": {"color": "#080808", "opacity": 1, "sprockets": True, "edgeText": None,
              "secondaryText": None, "edgeColor": None, "fontStyle": "auto", "leader": True,
              "startNumber": 1, "reverseNumbers": False, "frameGap": 12, "padding": 8,
              "showNumbers": True, "showHalfNumbers": True, "edgeArrow": "none", "fit": "contain",
              "edgeScale": 1, "edgeTracking": 0, "leaderMode": "auto", "leaderCount": 3,
              "leaderStyle": "dark", "leaderStrength": .75, "leaderShape": "cut",
              "separation": "none", "separationStrength": .65,
              "separationHoles": True, "shadowTone": "black", "sprocketStyle": "standard",
              "sprocketRim": "none", "edgeGlow": 0, "leakSoftness": .55,
              "leakSeed": 17, "leakPhotoCount": 0},
    "header": {"enabled": True, "title": "", "roll": "", "camera": "", "lens": "",
               "date": "", "process": "", "notes": "", "color": "#ffffff",
               "textColor": "#171717", "height": 180, "showStock": True, "infoScale": 1},
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
    bg["opacity"] = _number(bg["opacity"], "背景不透明度", 0, 1)
    strip["separationStrength"] = _number(strip["separationStrength"], "片条分离强度", 0, 1)
    bg["brightness"] = _number(bg["brightness"], "背景亮度", 0, 2)
    bg["angle"] = _number(bg["angle"], "渐变角度", -360, 360)
    strip["opacity"] = _number(strip["opacity"], "胶片不透明度", 0, 1)
    strip["frameGap"] = _number(strip["frameGap"], "画格间隔", 0, 100)
    strip["padding"] = _number(strip["padding"], "画格内边距", 0, 40)
    strip["edgeScale"] = _number(strip["edgeScale"], "边字大小", .6, 1.8)
    strip["edgeTracking"] = _number(strip["edgeTracking"], "边字字距", 0, 3)
    strip["startNumber"] = round(_number(strip["startNumber"], "起始格号", -999, 9999))
    header["height"] = _number(header["height"], "顶栏高度", 130, 400)
    strip["leaderCount"] = round(_number(strip["leaderCount"], "片头数量", 0, 24))
    strip["leaderStrength"] = _number(strip["leaderStrength"], "片头曝光强度", 0, 1)
    strip["leakSoftness"] = _number(strip["leakSoftness"], "漏光柔和度", 0, 1)
    strip["edgeGlow"] = _number(strip["edgeGlow"], "边字光晕", 0, 1)
    strip["leakSeed"] = round(_number(strip["leakSeed"], "漏光纹理编号", 0, 999999))
    strip["leakPhotoCount"] = round(_number(strip["leakPhotoCount"], "漏光延伸张数", 0, 12))
    header["infoScale"] = _number(header["infoScale"], "信息字号", .8, 1.4)
    for key, choices in (("leaderMode", ("auto", "manual")),
                         ("leaderStyle", ("dark", "clear", *EXPOSURE_STYLES)),
                         ("sprocketStyle", ("standard", "cinema", "square")),
                         ("sprocketRim", ("none", "amber", "silver")),
                         ("separation", ("none", "shadow", "outline", "lift", "paper")),
                         ("shadowTone", ("black", "white")),
                         ("edgeArrow", ("none", "left", "right")),
                         ("leaderShape", ("cut", "straight"))):
        if strip[key] not in choices:
            raise ValueError("片头设置无效")
    if not isinstance(strip["separationHoles"], bool):
        raise ValueError("齿孔层次设置须为布尔值")
    if strip["fontStyle"] not in ("auto", *EDGE_STYLES):
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
    leader_count: int
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
    strip = c["strip"]
    leader_count = ((-count % columns or columns) if strip["leaderMode"] == "auto"
                    else strip["leaderCount"]) if strip["leader"] else 0
    leader = leader_count > 0
    rows = ceil((count + leader_count) / columns)
    header_h = round(c["header"]["height"] * scale) if c["header"]["enabled"] else 0
    footer = round(45 * scale) if c.get("watermark") else 0
    height = 2 * margin + header_h + (spacing if header_h else 0) + rows * strip_h + (rows - 1) * spacing + footer
    if width * height > MAX_PIXELS:
        mp = width * height / 1_000_000
        raise ValueError(f"当前画布约 {mp:.1f} 百万像素，超过 80 百万像素上限。请减小输出宽度、增加每行张数或减少照片。")
    return SheetLayout(width, height, columns, rows, margin, spacing, header_h, leader, leader_count,
                       cell, aperture_w, aperture_h, band, strip_h, gap, scale)


def sheet_size(count: int, config: dict | None = None) -> tuple[int, int]:
    layout = sheet_layout(count, config)
    return layout.width, layout.height


@lru_cache(maxsize=160)
def _font(style: str, size: int, text: str = "") -> ImageFont.FreeTypeFont:
    size = max(1, int(size))
    # Use the OS's licensed CJK font for multilingual headers without bundling it.
    if any(ord(ch) > 255 for ch in text):
        windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates = [
            str(windows_fonts / "msyh.ttc"),
            str(windows_fonts / "msjh.ttc"),
            str(windows_fonts / "simsun.ttc"),
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]
    else:
        candidates = []
    filename = {"condensed": "BarlowCondensed-Medium.ttf", "mono": "IBMPlexMono-Regular.ttf",
                "header": "BarlowCondensed-SemiBold.ttf", "info": "IBMPlexMono-Medium.ttf",
                "film-kodak": "BarlowCondensed-SemiBold.ttf",
                "citaro": "CitaroVoor-Single.ttf", "citaro-tall": "CitaroVoor-Double.ttf"}.get(style, "IBMPlexMono-Regular.ttf")
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

# Original angular exposure lettering, drawn from the supplied RVP reference's
# visual traits. These paths are not a manufacturer's font or extracted glyphs.
# A small exposure grid gives diagonals their characteristic stepped shoulders.
_RVP_STROKES = {
    "A": (((0,10),(0,3),(3,0),(6,3),(6,10)),((0,6),(6,6))),
    "B": (((0,10),(0,0),(4,0),(6,2),(6,3),(4,5),(0,5)),((4,5),(6,7),(6,8),(4,10),(0,10))),
    "C": (((6,1),(5,0),(2,0),(0,2),(0,8),(2,10),(5,10),(6,9)),),
    "D": (((0,0),(3,0),(6,3),(6,7),(3,10),(0,10),(0,0)),),
    "E": (((6,0),(0,0),(0,10),(6,10)),((0,5),(5,5))),
    "F": (((6,0),(0,0),(0,10)),((0,5),(5,5))),
    "G": (((6,2),(4,0),(2,0),(0,2),(0,8),(2,10),(6,10),(6,5),(3,5)),),
    "H": (((0,0),(0,10)),((6,0),(6,10)),((0,5),(6,5))),
    "I": (((1,0),(5,0)),((3,0),(3,10)),((1,10),(5,10))),
    "J": (((1,0),(6,0),(6,8),(4,10),(2,10),(0,8)),),
    "K": (((0,0),(0,10)),((6,0),(0,6)),((2,4),(6,10))),
    "L": (((0,0),(0,10),(6,10)),),
    "M": (((0,10),(0,0),(3,4),(6,0),(6,10)),),
    "N": (((0,10),(0,0),(6,10),(6,0)),),
    "O": (((2,0),(4,0),(6,2),(6,8),(4,10),(2,10),(0,8),(0,2),(2,0)),),
    "P": (((0,10),(0,0),(4,0),(6,2),(6,4),(4,6),(0,6)),),
    "Q": (((2,0),(4,0),(6,2),(6,7),(3,10),(0,7),(0,2),(2,0)),((3,7),(6,10))),
    "R": (((0,10),(0,0),(4,0),(6,2),(6,4),(4,6),(0,6)),((3,6),(6,10))),
    "S": (((6,1),(5,0),(2,0),(0,2),(0,4),(6,6),(6,8),(4,10),(1,10),(0,9)),),
    "T": (((0,0),(6,0)),((3,0),(3,10))),
    "U": (((0,0),(0,8),(2,10),(4,10),(6,8),(6,0)),),
    "V": (((0,0),(0,5),(3,10),(6,5),(6,0)),),
    "W": (((0,0),(0,10),(3,6),(6,10),(6,0)),),
    "X": (((0,0),(6,10)),((6,0),(0,10))),
    "Y": (((0,0),(3,5),(6,0)),((3,5),(3,10))),
    "Z": (((0,0),(6,0),(0,10),(6,10)),),
    "0": (((2,0),(4,0),(6,2),(6,8),(4,10),(2,10),(0,8),(0,2),(2,0)),((1,8),(5,2))),
    "1": (((1,3),(4,0),(4,10)),),
    "2": (((0,2),(2,0),(4,0),(6,2),(6,4),(0,10),(6,10)),),
    "3": (((0,0),(5,0),(6,1),(6,3),(4,5),(2,5)),((4,5),(6,7),(6,9),(5,10),(0,10))),
    "4": (((4,10),(4,0),(0,6),(0,7),(6,7)),),
    "5": (((6,0),(0,0),(0,5),(4,5),(6,7),(6,9),(5,10),(0,10)),),
    "6": (((6,0),(2,0),(0,2),(0,8),(2,10),(4,10),(6,8),(6,6),(4,5),(0,5)),),
    "7": (((0,0),(6,0),(6,2),(1,10)),),
    "8": (((2,0),(4,0),(6,2),(6,3),(4,5),(2,5),(0,3),(0,2),(2,0)),((2,5),(0,7),(0,8),(2,10),(4,10),(6,8),(6,7),(4,5))),
    "9": (((6,5),(2,5),(0,4),(0,2),(2,0),(4,0),(6,2),(6,8),(4,10),(0,10)),),
    "-": (((1,5),(5,5)),), ".": (((3,9),(3,10)),),
    "/": (((0,10),(6,0)),), ":": (((3,3),(3,3.5)),((3,7),(3,7.5))),
    "+": (((0,5),(6,5)),((3,2),(3,8))), " ": (),
}


def _text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: int,
          fill: tuple, style: str = "mono", max_width: float | None = None,
          tracking: float = 0) -> None:
    text = str(text or "")[:250]
    if not text:
        return
    if style in EDGE_STYLES[3:] and (all(ord(ch) < 128 for ch in text) if style.startswith("citaro") else all(ch.upper() in _DOT for ch in text)):
        mask = _edge_type_mask(text, style, size, max_width, tracking)
        draw.bitmap(xy, mask, fill=fill)
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


@lru_cache(maxsize=256)
def _edge_type_mask(text: str, style: str, size: int, max_width: float | None, tracking: float) -> Image.Image:
    scale = 4
    if style in ("film-rvp", "film-cine"):
        cine = style == "film-cine"
        advance=(18 if cine else 19)+tracking*24/max(1,size)
        source=Image.new("L",(max(1,ceil(advance*(len(text)-1)+16)),24))
        d=ImageDraw.Draw(source)
        for i,ch in enumerate(text.upper()):
            for path in (_RVP_STROKES.get("O",()) if cine and ch == "0" else _RVP_STROKES.get(ch,())):
                d.line([(round(i*advance+2+x*2),round(2+y*2)) for x,y in path],
                       fill=245,width=2 if cine else 4,joint="curve")
        source=source.filter(ImageFilter.GaussianBlur(.16 if cine else .38))
        height=max(1,size*scale);width=max(1,round(source.width*height/24))
        if max_width and width>max_width*scale:
            height=max(1,round(height*max_width*scale/width));width=max(1,round(max_width*scale))
        mask=source.resize((width,height),Image.Resampling.LANCZOS)
    elif style.startswith("citaro") or style == "film-kodak":
        font = _font(style, 96)
        bbox = font.getbbox(text, anchor="lt")
        source = Image.new("L", (max(1,round(font.getlength(text)))+4, max(1,bbox[3])+4))
        d = ImageDraw.Draw(source)
        d.text((0,0),text,font=font,fill=255,anchor="lt",stroke_width=1 if style=="film-kodak" else 0)
        source = source.crop(source.getbbox() or (0,0,1,1))
        height = max(1, size*scale)
        width = max(1, round(source.width*height/source.height))
        # Letter spacing stays in final output pixels, normalized with cap height.
        if tracking:
            pieces = []
            for ch in text:
                b = font.getbbox(ch,anchor="ls")
                pieces.append((ch, font.getlength(ch)))
            cap = max(1,bbox[3]); advance = tracking*cap/max(1,size)
            source = Image.new("L", (max(1,round(sum(p[1] for p in pieces)+advance*(len(text)-1)))+4, cap+4))
            d = ImageDraw.Draw(source); x = 0; baseline = -font.getbbox(text,anchor="ls")[1]
            for ch,step in pieces:
                d.text((x,baseline),ch,font=font,fill=255,anchor="ls",stroke_width=1 if style=="film-kodak" else 0)
                x+=step+advance
            width = max(1,round(source.width*height/source.height))
        if style == "film-kodak": width=round(width*1.28)
        if max_width and width > max_width*scale:
            height=max(1,round(height*max_width*scale/width)); width=max(1,round(max_width*scale))
        mask = source.resize((width,height),Image.Resampling.LANCZOS)
    else:
        unit = max(1,size*scale/7); pitch = unit*(1 if style=="film-phoenix" else .76)
        width = max(1,ceil((len(text)*6-1)*pitch+tracking*scale*(len(text)-1)))
        if max_width and width > max_width*scale:
            shrink=max_width*scale/width
            unit*=shrink; pitch*=shrink; tracking*=shrink; size*=shrink
            width=max(1,round(max_width*scale))
        mask = Image.new("L",(width,max(1,ceil(size*scale))))
        d=ImageDraw.Draw(mask); x=0
        for ch in text.upper():
            glyph=_DOT.get("O" if style=="film-phoenix" and ch=="0" else ch,_DOT[" "])
            for row,bits in enumerate(glyph):
                for col in range(5):
                    if bits & (1 << (4-col)):
                        cx=x+(col+.5)*pitch; cy=(row+.5)*unit
                        if style=="film-phoenix":
                            d.rectangle((x+col*pitch,row*unit,x+(col+1)*pitch,(row+1)*unit),fill=245)
                        elif style=="film-dot":
                            rx,ry=pitch*.43,unit*.40
                            d.ellipse((cx-rx,cy-ry,cx+rx,cy+ry),fill=245)
                        else:
                            rx,ry=pitch*.52,unit*.54
                            d.rounded_rectangle((cx-rx,cy-ry,cx+rx,cy+ry),radius=unit*.18,fill=245)
            x+=pitch*6+tracking*scale
        mask=mask.filter(ImageFilter.GaussianBlur(.22 if style=="film-phoenix" else .4 if style=="film-dot" else .65))
    width=max(1,round(mask.width/scale)); height=max(1,round(mask.height/scale))
    if max_width and width>max_width:
        ratio=max_width/width; width=max(1,round(max_width)); height=max(1,round(height*ratio))
    return mask.resize((width,height),Image.Resampling.LANCZOS)


@lru_cache(maxsize=128)
def _edge_arrow_mask(direction: str, size: int) -> Image.Image:
    """A broad stepped wedge matching the supplied film-edge reference."""
    source=Image.new("L",(19,11));draw=ImageDraw.Draw(source)
    for y in range(11): draw.line((abs(y-5)*3,y,18,y),fill=245)
    if direction == "right": source=ImageOps.mirror(source)
    return source.filter(ImageFilter.GaussianBlur(.2)).resize(
        (max(1,round(size*1.75)),max(1,size)),Image.Resampling.LANCZOS)


def _composite_print(base: Image.Image, letters: Image.Image, size: int, strength: float) -> None:
    """Red halation and a warm core, clipped to the existing film silhouette."""
    alpha = base.getchannel("A")
    mask = letters.getchannel("A")
    for radius, color, opacity in ((size*.40,(255,30,7),.72),
                                    (size*.11,(255,118,18),.55)):
        halo = Image.new("RGBA",base.size,(*color,0))
        halo.putalpha(mask.filter(ImageFilter.GaussianBlur(max(.3,radius))).point(
            lambda v: min(255,round(v*strength*opacity*3))))
        base.alpha_composite(halo)
    base.alpha_composite(letters)
    core = Image.new("RGBA",base.size,(255,240,153,0))
    core.putalpha(mask.point(lambda v:round(v*strength*.55)))
    base.alpha_composite(core)
    base.putalpha(alpha)


def lettering_sample(style: str, text: str, color: str = "#dda850", arrow: str = "none",
                     glow: float = 0) -> Image.Image:
    if style not in EDGE_STYLES:
        raise ValueError("边字字体样式无效")
    if arrow not in ("none","left","right"): raise ValueError("边字箭头方向无效")
    glow = _number(glow,"边字光晕",0,1)
    out=Image.new("RGBA",(800,156),(14,14,13,255))
    letters=Image.new("RGBA",out.size) if glow else out
    draw=ImageDraw.Draw(letters)
    _text(draw,(28,25),text or "FILM 135 / ISO 200",38,_color(color),style,744)
    for i,number in enumerate((12,13,14)):
        x=28+i*248
        _text(draw,(x,91),str(number),25,_color(color),style,56)
        if arrow != "none": draw.bitmap((x+66,92),_edge_arrow_mask(arrow,23),fill=_color(color))
        _text(draw,(x+122,91),f"{number}A",25,_color(color),style,110)
    if glow: _composite_print(out,letters,38,glow)
    return out.convert("RGB")


def _cover(source: Image.Image, size: tuple[int, int], override: dict | None = None,
           fit: str = "cover", padding: int = 0) -> Image.Image:
    """Fit positive pixels, with normalized crop center and an optional zoom."""
    o = override if isinstance(override, dict) else {}
    photo = ImageOps.exif_transpose(source)
    # Film windows are horizontal. Only an absent rotation uses the portrait
    # default; an explicit zero is a deliberate request to keep it upright.
    rotation = o.get("rotation")
    if rotation is None:
        rotation = 90 if photo.height > photo.width else 0
    rotation = _number(rotation, "单张旋转", -360, 360)
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


@lru_cache(maxsize=128)
def _hole_mask(width: int, height: int, style: str) -> Image.Image:
    """Antialiased perforation silhouettes, shared by holes and depth effects."""
    aa=4; w,h=width*aa,height*aa
    mask=Image.new("L",(w,h)); d=ImageDraw.Draw(mask)
    if style == "cinema":
        # Flat sides and bowed ends, inspired by BH camera-negative holes.
        d.rounded_rectangle((0,h*.12,w-1,h*.88),radius=w*.10,fill=255)
        d.ellipse((0,0,w-1,h*.38),fill=255)
        d.ellipse((0,h*.62,w-1,h-1),fill=255)
    else:
        radius=w*(.07 if style == "square" else .18)
        d.rounded_rectangle((0,0,w-1,h-1),radius=radius,fill=255)
    return mask.resize((width,height),Image.Resampling.LANCZOS)


def _film_layer(layout: SheetLayout, c: dict, cells: int, cut_leader: bool = False) -> Image.Image:
    strip = c["strip"]
    width = round(layout.cell_width * cells)
    color = _color(strip["color"])
    alpha = round(color[3] * strip["opacity"])
    row = Image.new("RGBA", (width, layout.strip_height), (*color[:3], alpha))
    if strip["sprockets"]:
        pitch = layout.cell_width / 8
        hw, hh = layout.cell_width * 1.98 / 38, layout.cell_width * 2.79 / 38
        # Text is outside the holes, toward the two outer edges.
        hole_y = layout.band * .45
        for i in range(cells * 8):
            x = (i + .5) * pitch
            for y in (hole_y, layout.strip_height - hole_y - hh):
                # Leave the cut shoulder unpunched instead of opening a half
                # sprocket into its silhouette. Full-width film retains its pitch.
                shoulder_end = min(layout.cell_width * .96, layout.strip_height * 1.08)
                if cut_leader and y == hole_y and x-hw/2 < shoulder_end:
                    continue
                hole=_hole_mask(max(2,round(hw)),max(2,round(hh)),strip["sprocketStyle"])
                hx,hy=round(x-hw/2),round(y)
                if strip["sprocketRim"] != "none":
                    pad=max(1,round(layout.scale))
                    padded=Image.new("L",(hole.width+2*pad,hole.height+2*pad))
                    padded.paste(hole,(pad,pad))
                    rim=ImageChops.subtract(padded.filter(ImageFilter.MaxFilter(2*pad+1)),padded)
                    tone=(176,102,44,alpha) if strip["sprocketRim"] == "amber" else (209,205,190,alpha)
                    row.paste(tone,(hx-pad,hy-pad,hx+hole.width+pad,hy+hole.height+pad),rim)
                row.paste((0,0,0,0),(hx,hy,hx+hole.width,hy+hole.height),hole)
    return row


def _clip_leader(row: Image.Image, cell_width: float) -> None:
    """Flat leader tongue with a compact, tangent-continuous S shoulder.

    Keep the cut within the first blank. Supersample only that small end,
    with a bounded mask allocation even for large exports.
    """
    h = row.height
    end = min(cell_width * .96, h * 1.08)
    tongue = end * .55
    level = h * .48
    radius = min(h * .035, tongue * .15)
    width = min(row.width, ceil(end) + 2)
    aa = max(1, min(4, int((4_000_000 / max(1, width * h)) ** .5)))
    mask = Image.new("L", (width * aa, h * aa), 0)
    shoulder = end - tongue
    p0, p1 = (tongue, level), (tongue + shoulder * .48, level)
    p2, p3 = (end - shoulder * .48, 0), (end, 0)
    points = [(radius, level), p0]
    for i in range(1, 97):
        t = i / 96; u = 1 - t
        points.append((u**3*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*p3[0],
                       u**3*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*p3[1]))
    points += [(width, 0), (width, h), (radius, h)]
    for i in range(1, 25):
        angle = radians(90 + i * 90 / 24)
        points.append((radius + radius*cos(angle), h-radius + radius*sin(angle)))
    points.append((0, level+radius))
    for i in range(1, 25):
        angle = radians(180 + i * 90 / 24)
        points.append((radius + radius*cos(angle), level+radius + radius*sin(angle)))
    ImageDraw.Draw(mask).polygon([(x*aa,y*aa) for x,y in points], fill=255)
    if aa > 1:
        mask = mask.resize((width,h), Image.Resampling.LANCZOS)
    alpha = row.getchannel("A")
    alpha.paste(ImageChops.multiply(alpha.crop((0,0,width,h)), mask), (0,0))
    row.putalpha(alpha)


def _leader_field(size: tuple[int, int], start: float, end: float,
                  aspect: float, strip: dict) -> Image.Image:
    """One continuous exposure field along the entire leader, including its bands.

    start/end are positions along the roll, independent of rows and frame gaps.
    All exposure styles decay to the chosen film color at the photo boundary.
    """
    base = _color(strip["color"])[:3]
    style = strip["leaderStyle"]
    if style in ("dark", "clear"):
        return Image.new("RGB", size, base if style == "dark" else (224,216,194))
    light = exposure_field(size,start,end,aspect,style,strip["leaderStrength"],
                           strip["leakSoftness"],strip["leakSeed"])
    return ImageChops.screen(Image.new("RGB",size,base),light)


def _place_strip(canvas: Image.Image, row: Image.Image, xy: tuple[int,int],
                 layout: SheetLayout, strip: dict, cut_leader: bool) -> None:
    effect, strength=strip["separation"],strip["separationStrength"]
    if effect == "none" or strength == 0:
        canvas.alpha_composite(row,xy)
        return
    # Use the punched film geometry, independent of photo/film opacity.
    # Work at <= 1600 px for predictable preview and large-export costs.
    ratio=min(1,1600/row.width)
    work=(max(1,round(row.width*ratio)),max(1,round(row.height*ratio)))
    silhouette=Image.new("RGBA",work,(255,255,255,255))
    if cut_leader: _clip_leader(silhouette,layout.cell_width*ratio)
    scale=layout.scale*ratio
    pad=max(4,ceil(20*scale))
    mask=Image.new("L",(work[0]+2*pad,work[1]+2*pad),0)
    mask.paste(silhouette.getchannel("A"),(pad,pad))
    outer=mask.copy()
    if strip["separationHoles"] and strip["sprockets"]:
        scaled=replace(layout,cell_width=layout.cell_width*ratio,
                       band=layout.band*ratio,strip_height=work[1])
        geometry=_film_layer(scaled,{"strip":dict(strip,color="#ffffff",opacity=1)},
                             round(row.width/layout.cell_width),cut_leader)
        if cut_leader: _clip_leader(geometry,scaled.cell_width)
        mask.paste(geometry.getchannel("A").resize(work,Image.Resampling.LANCZOS),(pad,pad))
    decor=Image.new("RGBA",mask.size,(0,0,0,0))
    if effect in ("shadow","lift","paper"):
        shifted=Image.new("L",mask.size,0)
        shifted.paste(mask,(0,max(1,round(4*scale))))
        shadow=shifted.filter(ImageFilter.GaussianBlur(max(.7,5*scale)))
        shadow=ImageChops.subtract(shadow,mask).point(lambda v:round(v*.72*strength))
        tone=255 if strip["shadowTone"] == "white" else 0
        cast=Image.new("RGBA",mask.size,(tone,tone,tone,0));cast.putalpha(shadow)
        decor.alpha_composite(cast)
    if effect in ("outline","lift","paper"):
        radius=max(1,round((6 if effect == "paper" else 1.5)*scale))
        border=ImageChops.subtract(outer.filter(ImageFilter.MaxFilter(2*radius+1)),outer)
        # Keep broad paper borders from closing narrow sprocket openings.
        rim=min(radius,max(1,int(layout.cell_width*ratio*1.98/38*.22)))
        inside=ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(2*rim+1)),mask)
        border=ImageChops.lighter(border,ImageChops.multiply(inside,outer))
        border=border.point(lambda v:round(v*strength))
        light=Image.new("RGBA",mask.size,(247,241,226,0));light.putalpha(border)
        decor.alpha_composite(light)
    full_pad=max(1,round(pad/ratio))
    if ratio < 1: decor=decor.resize((row.width+2*full_pad,row.height+2*full_pad),Image.Resampling.BICUBIC)
    canvas.alpha_composite(decor,(xy[0]-full_pad,xy[1]-full_pad))
    canvas.alpha_composite(row,xy)


def _edge_labels(row: Image.Image, layout: SheetLayout, c: dict, stock: dict,
                 indices: list[int], count: int) -> None:
    strip = c["strip"]
    if strip["edgeGlow"]:
        # Only the two narrow film bands need glow buffers, even at 10K export.
        letters=Image.new("RGBA",(row.width,2*layout.band))
        compact=replace(layout,strip_height=2*layout.band)
        _edge_labels(letters,compact,dict(c,strip=dict(strip,edgeGlow=0)),stock,indices,count)
        for source_y,target_y in ((0,0),(layout.band,row.height-layout.band)):
            region=row.crop((0,target_y,row.width,target_y+layout.band))
            ink=letters.crop((0,source_y,row.width,source_y+layout.band))
            _composite_print(region,ink,max(1,round(layout.cell_width*.026*strip["edgeScale"])),strip["edgeGlow"])
            row.paste(region,(0,target_y))
        return
    style = strip["fontStyle"]
    if style == "auto":
        style = stock.get("font_style", "condensed")
    if style not in EDGE_STYLES:
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
        _text(draw, (x, outer), edge, fs, edge_color, style, layout.cell_width*.84, tracking)
        if index < 0:
            continue
        number_y = layout.strip_height - outer - fs
        if strip["edgeArrow"] != "none":
            draw.bitmap((x+layout.cell_width*.49,number_y),
                        _edge_arrow_mask(strip["edgeArrow"],fs),fill=edge_color)
        if not strip["showNumbers"]: continue
        number = strip["startNumber"] + (count-1-index if strip["reverseNumbers"] else index)
        override = c["frameOverrides"][index] if index < len(c["frameOverrides"]) else {}
        label = str(override.get("label", number) if isinstance(override, dict) else number)
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
    pad, icon = round(28*s), round(62*s)
    ix, iy = x+pad, y+round((h-icon)/2)
    lw = max(1,round(4*s))
    draw.rectangle((ix,iy+icon*.15,ix+icon,iy+icon*.9),outline=ink,width=lw)
    draw.rectangle((ix+icon*.18,iy,ix+icon*.58,iy+icon*.18),fill=ink)
    draw.ellipse((ix+icon*.27,iy+icon*.31,ix+icon*.73,iy+icon*.77),outline=ink,width=lw)
    tx = ix+icon+round(30*s)
    content_w = x+w-pad-tx
    title = str(header.get("title") or stock.get("name") or "")
    roll = str(header.get("roll") or "")
    title_w = content_w * (.75 if roll else 1)
    factor=min(1.15,(header["height"]/180)**.35)
    _text(draw,(tx,y+h*.13),title,round(40*s*factor),ink,"header",title_w)
    if roll:
        _text(draw,(tx+content_w*.78,y+h*.17),"ROLL  "+roll,round(23*s*factor),ink,"info",content_w*.22)
    ry=y+h*.43
    rule=tuple(round(ink[i]*.25+fill[i]*.75) for i in range(3))+(fill[3],)
    draw.line((tx,ry,x+w-pad,ry),fill=rule,width=max(1,round(s)))
    fields=[]
    if header["showStock"]:
        if stock.get("name"): fields.append(("FILM",str(stock["name"])))
        if stock.get("iso"): fields.append(("ISO",str(stock["iso"])))
    for key,label in (("camera","CAMERA"),("lens","LENS"),("date","DATE"),("process","PROCESS")):
        value=header.get(key) or (stock.get("process") if key=="process" else "")
        if value: fields.append((label,str(value)))
    notes=str(header.get("notes") or "")
    if fields:
        # Weight cells by useful text, keeping ISO and process compact.
        weights=[min(2.5,max(.7,len(value)*.11)) for _,value in fields]
        available=min(content_w, sum(weights)*460*s)
        fx=tx
        label_y=ry+h*.075
        value_y=ry+h*.205
        value_room=h*(.18 if notes else .27)
        for (label,value),weight in zip(fields,weights):
            column_w=available*weight/sum(weights)
            _text(draw,(fx,label_y),label,round(14*s*factor),ink,"info",column_w-18*s)
            fs=min(round(30*s*factor*header["infoScale"]),round(value_room))
            _text(draw,(fx,value_y),value,fs,ink,"info",column_w-18*s)
            fx+=column_w
    if notes:
        _text(draw,(tx,y+h*.84),notes,round(16*s*factor),ink,"mono",content_w)


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
    if c["background"]["opacity"] < 1:
        opacity=c["background"]["opacity"]
        canvas.putalpha(canvas.getchannel("A").point(lambda v:round(v*opacity)))
    _header(canvas,layout,c,stock)
    total = layout.leader_count + len(images)
    for row_index, first in enumerate(range(0, total, layout.columns)):
        slots = list(range(first, min(first + layout.columns, total)))
        indices = [slot - layout.leader_count for slot in slots]
        cut_leader = row_index == 0 and layout.leader and c["strip"]["leaderShape"] == "cut"
        row = _film_layer(layout,c,len(slots),cut_leader)
        leader_cells=max(0,min(len(slots),layout.leader_count-first))
        if leader_cells and c["strip"]["leaderStyle"] in ("dark", "clear"):
            leader_width=round(leader_cells*layout.cell_width)
            field=_leader_field((leader_width,layout.strip_height),first/layout.leader_count,
                                (first+leader_cells)/layout.leader_count,
                                layout.leader_count*layout.cell_width/layout.strip_height,c["strip"]).convert("RGBA")
            field.putalpha(row.getchannel("A").crop((0,0,leader_width,layout.strip_height)))
            row.paste(field,(0,0))
        for col,index in enumerate(indices):
            if index < 0: continue
            override=c["frameOverrides"][index] if index<len(c["frameOverrides"]) else {}
            fit="contain" if c["ratio"]=="original" else c["strip"]["fit"]
            photo=_cover(images[index],(layout.aperture_width,layout.aperture_height),override,fit,
                         round(c["strip"]["padding"]*layout.scale))
            px=round(col*layout.cell_width+layout.gap/2)
            row.alpha_composite(photo,(px,layout.band))
        affected = layout.leader_count + min(len(images),c["strip"]["leakPhotoCount"])
        if c["strip"]["leaderStyle"] in EXPOSURE_STYLES and first < affected:
            cells = min(len(slots),affected-first)
            width = round(cells*layout.cell_width)
            light = exposure_field((width,layout.strip_height),first/affected,
                                   (first+cells)/affected,affected*layout.cell_width/layout.strip_height,
                                   c["strip"]["leaderStyle"],c["strip"]["leaderStrength"],
                                   c["strip"]["leakSoftness"],c["strip"]["leakSeed"])
            region = row.crop((0,0,width,layout.strip_height))
            exposed = ImageChops.screen(region.convert("RGB"),light).convert("RGBA")
            exposed.putalpha(region.getchannel("A"))
            row.paste(exposed,(0,0))
        _edge_labels(row,layout,c,stock,indices,len(images))
        if cut_leader:
            _clip_leader(row, layout.cell_width)
        _place_strip(canvas,row,(layout.margin,layout.row_y(row_index)),layout,c["strip"],cut_leader)
    watermark=c.get("watermark")
    if isinstance(watermark,dict):
        watermark=watermark.get("text","")
    if watermark:
        draw=ImageDraw.Draw(canvas)
        _text(draw,(layout.margin,layout.height-layout.margin-round(20*layout.scale)),str(watermark),
              round(18*layout.scale),_color(c["header"]["textColor"]),"mono",layout.width-2*layout.margin)
    return canvas

"""Isolated, asynchronous image preparation for the roll contact-sheet editor.

The editor reads exported positives first and saved adjustments second. It never
loads a frame into the adjustment UI's current-image cache or writes a sidecar.
"""
from __future__ import annotations

import copy
import io
import json
import math
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
import zipfile

import numpy as np
from flask import Blueprint, jsonify, render_template, request, send_file
from PIL import Image, ImageCms, ImageOps

import decast
from contact_sheet import render_sheet, sheet_size


MAX_FRAMES = 240
MAX_JOBS = 4
MAX_IMAGE_PIXELS = 180_000_000
MAX_EXPORT_PIXELS = 80_000_000
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
MAX_UPLOAD_TOTAL = 512 * 1024 * 1024
MAX_PROJECT_BYTES = 500 * 1024 * 1024
MAX_PREVIEW_CACHE_BYTES = 64 * 1024 * 1024
JOB_TTL = 2 * 60 * 60
BASE_DIR = Path(__file__).resolve().parent
IMAGE_EXTS = decast.IMG_EXTS
SUPPORTED_EXTS = IMAGE_EXTS | decast.RAW_EXTS


class SheetInputError(ValueError):
    pass


class _PreviewImageCache:
    """Bound decoded preview derivatives independently from the on-disk jobs.

    Cached pixels are immutable: callers receive a copy, so a renderer cannot
    affect a later request. Slow decodes never hold the job registry lock.
    """
    def __init__(self, limit):
        self.limit = limit
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = threading.Lock()

    def get(self, key, loader):
        with self.lock:
            cached = self.entries.get(key)
            if cached is not None:
                self.entries.move_to_end(key)
                return cached[0].copy()
        image = loader()
        # Pillow uses four bytes per RGB pixel internally, as it does for RGBA.
        size = image.width * image.height * 4
        if size <= self.limit:
            with self.lock:
                previous = self.entries.pop(key, None)
                if previous is not None:
                    self.bytes -= previous[1]
                while self.entries and self.bytes + size > self.limit:
                    _, (_, removed) = self.entries.popitem(last=False)
                    self.bytes -= removed
                self.entries[key] = (image.copy(), size)
                self.bytes += size
        return image

    def discard_job(self, identifier):
        with self.lock:
            for key in [key for key in self.entries if key[0] == identifier]:
                _, size = self.entries.pop(key)
                self.bytes -= size


def _error(message, status=400):
    return jsonify(ok=False, error=str(message), err=str(message)), status


def _path(value, *, directory=False):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise SheetInputError("请选择有效的本地文件夹或图片。")
    p = Path(value.strip()).expanduser().resolve()
    if directory:
        if not p.is_dir():
            raise SheetInputError("找不到这个文件夹：" + str(p))
    elif not p.is_file() or p.suffix.lower() not in SUPPORTED_EXTS:
        raise SheetInputError("找不到图片或格式不受支持：" + str(p))
    return p


def _frame_key(path):
    stem = path.stem
    return re.sub(r"_pos$", "", stem, flags=re.I).casefold()


def _natural_key(value):
    return tuple((1, int(s)) if s.isdigit() else (0, s.casefold())
                 for s in re.split(r"(\d+)", str(value)))


def _is_export(path):
    return path.suffix.lower() in IMAGE_EXTS and path.stem.lower().endswith("_pos")


def _collect_directory(directory):
    """Find original/export pairs, including common export subdirectories."""
    found = []
    for root, folders, names in os.walk(directory):
        depth = len(Path(root).relative_to(directory).parts)
        folders[:] = sorted(d for d in folders if not d.startswith(".")
                            and d not in {"整卷展示", "settings", "presets", "__pycache__"})
        if depth >= 3:
            folders[:] = []
        for name in sorted(names, key=_natural_key):
            p = Path(root, name)
            if not name.startswith(".") and p.suffix.lower() in SUPPORTED_EXTS:
                found.append(p.resolve())
        if len(found) > 20000:
            raise SheetInputError("文件夹里的图片太多，请选择具体的一卷。")
    return found


def _discover_related(paths):
    """A selection in the adjustment UI still means a *frame*, not a JPEG import.

    Include same-stem RAW/JPEG counterparts and known positive exports next to
    the selected source or in conventional immediate export subdirectories.
    """
    result = set(paths)
    parents = {}
    for path in paths:
        parents.setdefault(path.parent, set()).add(_frame_key(path))
    export_folders = {"positive", "positives", "export", "exports", "output", "outputs",
                      "成片", "导出", "输出", "正片", "positives_output"}
    for parent, keys in parents.items():
        folders = [parent]
        for entry in parent.iterdir():
            if (entry.is_dir() and not entry.name.startswith(".")
                    and entry.name.casefold() in export_folders):
                folders.append(entry)
        for folder in folders:
            for candidate in folder.iterdir():
                if (candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTS
                        and _frame_key(candidate) in keys):
                    result.add(candidate.resolve())
    return sorted(result, key=lambda p: _natural_key(str(p)))


def _positive_image(path, max_side=2560):
    """Decode, honor orientation, convert embedded profiles, retain PNG alpha."""
    with Image.open(path) as opened:
        if opened.width * opened.height > MAX_IMAGE_PIXELS:
            raise SheetInputError("单张图片超过 1.8 亿像素，请先缩小。")
        icc = opened.info.get("icc_profile")
        # The cache stores a derivative, so ask libjpeg for a smaller decode
        # before EXIF transposition loads the pixels. Other formats stay intact.
        if opened.format == "JPEG" and opened.mode in {"RGB", "L"}:
            opened.draft(opened.mode, (max_side, max_side))
        image = ImageOps.exif_transpose(opened)
        if image.mode == "P":
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        # ICC transforms are pointwise; doing this at the actual cache size
        # avoids transforming a 42 MP scan that will immediately be discarded.
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        image = image.convert("RGB")
        if icc:
            try:
                image = ImageCms.profileToProfile(
                    image, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                    ImageCms.createProfile("sRGB"), outputMode="RGB")
            except (OSError, ValueError, ImageCms.PyCMSError):
                pass
        if alpha is not None:
            image.putalpha(alpha)
        return image.copy()


def _rgb(image):
    if image.mode == "RGBA":
        backdrop = Image.new("RGB", image.size, "white")
        backdrop.paste(image, mask=image.getchannel("A"))
        return backdrop
    return image.convert("RGB")


def _json_object():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise SheetInputError("请求内容必须是 JSON 对象。")
    return body


def _check_numbers(value, depth=0):
    """Reject NaN, infinities and pathological nested JSON before rendering."""
    if depth > 12:
        raise SheetInputError("排版参数层级过多。")
    if isinstance(value, float) and not math.isfinite(value):
        raise SheetInputError("排版参数需要使用有效数字。")
    if isinstance(value, (float, int)) and not isinstance(value, bool) and abs(value) > 1e7:
        raise SheetInputError("排版参数数值过大。")
    if isinstance(value, dict):
        if len(value) > 150:
            raise SheetInputError("排版参数过多。")
        for key, entry in value.items():
            if str(key).startswith("_"):
                raise SheetInputError("排版参数包含保留字段。")
            _check_numbers(entry, depth + 1)
    elif isinstance(value, list):
        if len(value) > 1000:
            raise SheetInputError("排版参数列表过长。")
        for entry in value:
            _check_numbers(entry, depth + 1)
    elif isinstance(value, str) and len(value) > 5000:
        raise SheetInputError("排版文字过长。")


def _archive_name(value):
    if (not isinstance(value, str) or not value or len(value) > 240
            or "\\" in value or "\x00" in value or ":" in value):
        raise SheetInputError("项目压缩包包含无效的文件名。")
    path = PurePosixPath(value)
    if (path.is_absolute() or ".." in path.parts or "." in path.parts
            or str(path) != value.rstrip("/")):
        raise SheetInputError("项目压缩包包含越界路径，无法导入。")
    return value


def _project_image_name(value):
    value = _archive_name(value)
    if value.endswith("/") or PurePosixPath(value).suffix.lower() not in IMAGE_EXTS:
        raise SheetInputError("项目中的照片和背景必须是普通图片。")
    return value


def create_sheet_blueprint(make_opts, read_xml, settings_file, get_start_dirs):
    blueprint = Blueprint("sheet", __name__, template_folder="templates")
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="film-sheet")
    lock = threading.RLock()
    jobs = {}
    exports = {}
    preview_images = _PreviewImageCache(MAX_PREVIEW_CACHE_BYTES)

    def remove_job_locked(identifier):
        job = jobs.pop(identifier)
        preview_images.discard_job(identifier)
        shutil.rmtree(job["cache"], ignore_errors=True)

    def cleanup_locked():
        now = time.monotonic()
        busy = {e["job"] for e in exports.values() if e["state"] == "running"}
        busy.update(j["id"] for j in jobs.values() if j.get("users", 0))
        expired = [key for key, job in jobs.items()
                   if job["state"] != "running" and key not in busy
                   and now - job["touched"] > JOB_TTL]
        for key in expired:
            remove_job_locked(key)
        if len(jobs) >= MAX_JOBS:
            idle = sorted((j for j in jobs.values()
                           if j["state"] != "running" and j["id"] not in busy),
                          key=lambda j: j["touched"])
            if idle:
                oldest = idle[0]
                remove_job_locked(oldest["id"])
        if len(jobs) >= MAX_JOBS:
            raise SheetInputError("同时处理的胶卷已达 4 卷，请等当前任务完成。")

    def new_job(directory, label):
        with lock:
            cleanup_locked()
            identifier = uuid.uuid4().hex
            cache = Path(tempfile.mkdtemp(prefix="decast-sheet-"))
            job = dict(id=identifier, cache=cache, directory=str(directory),
                       label=label, state="running", done=0, total=0,
                       message="正在查找成片和已保存的调整", items=[], warnings=[],
                       touched=time.monotonic(), background=None, users=0,
                       preview_lock=threading.Lock())
            jobs[identifier] = job
        return job

    def get_job(identifier, ready=False):
        if not isinstance(identifier, str):
            raise SheetInputError("缺少整卷任务编号。")
        with lock:
            job = jobs.get(identifier)
            if job is None:
                raise SheetInputError("整卷任务已过期，请重新载入照片。")
            job["touched"] = time.monotonic()
            if ready and job["state"] != "ready":
                raise SheetInputError("照片尚未准备完成，请稍候。")
            return job

    def read_adjustments(path, warnings):
        xml = Path(str(path) + ".decast.xml")
        settings = Path(settings_file(str(path)))
        for candidate, is_xml in ((xml, True), (settings, False)):
            if not candidate.is_file():
                continue
            try:
                if candidate.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("参数文件过大")
                text = candidate.read_text(encoding="utf-8")
                data = read_xml(text) if is_xml else json.loads(text)
                if isinstance(data, dict) and isinstance(data.get("P"), dict) and data["P"]:
                    return data
            except Exception as exc:
                warnings.append(f"{path.name} 的调整参数无法读取：{exc}")
        return None

    def select_sources(paths, positive_only, warnings):
        grouped = {}
        for path in paths:
            grouped.setdefault(_frame_key(path), set()).add(path)
        selected = []
        for key in sorted(grouped, key=_natural_key):
            group = sorted(grouped[key], key=lambda p: (len(p.parts), str(p)))
            if positive_only:
                images = [p for p in group if p.suffix.lower() in IMAGE_EXTS]
                if images:
                    selected.append((images[0], "import", None))
                    continue
            positive = [p for p in group if _is_export(p)]
            if positive:
                priority = {".tif": 0, ".tiff": 0, ".png": 1, ".jpg": 2, ".jpeg": 2}
                chosen = min(positive, key=lambda p: (priority.get(p.suffix.lower(), 3), len(p.parts), str(p)))
                selected.append((chosen, "export", None))
                continue
            raw = [p for p in group if p.suffix.lower() in decast.RAW_EXTS]
            images = [p for p in group if p.suffix.lower() in IMAGE_EXTS]
            found = None
            for path in raw + images:
                adjustments = read_adjustments(path, warnings)
                if adjustments:
                    found = (path, "saved", adjustments)
                    break
            if found:
                selected.append(found)
            elif images and not raw:
                selected.append((images[0], "import", None))
            else:
                warnings.append(f"{group[0].stem} 没有导出的成片或已保存的调片参数，已跳过。")
        if len(selected) > MAX_FRAMES:
            warnings.append(f"最多排版 {MAX_FRAMES} 张，已载入前 {MAX_FRAMES} 张。")
            selected = selected[:MAX_FRAMES]
        return selected

    def saved_positive(path, data, warnings):
        params = copy.deepcopy(data["P"])
        params.pop("negative_preview", None)
        if params.get("use_match"):
            warnings.append(f"{path.name} 使用过参照匹配；请优先导出成片以保留该效果。")
        params["use_match"] = False
        crop = data.get("cropN")
        if crop:
            rect = [float(crop[k]) for k in ("x0", "y0", "x1", "y1")]
            if (not all(math.isfinite(x) and 0 <= x <= 1 for x in rect)
                    or rect[0] >= rect[2] or rect[1] >= rect[3]):
                raise SheetInputError("已保存的裁剪范围无效。")
            params["crop_rect"] = rect
        opts = make_opts(params)
        # make_opts reads the current matching reference. A sheet must not inherit it.
        opts._ref_centers = None
        opts._ref_cdfs = None
        opts.stats_rect = None
        lin, _ = decast.load_image(str(path), opts)
        if lin.shape[0] * lin.shape[1] > MAX_IMAGE_PIXELS:
            raise SheetInputError("单张图片超过 1.8 亿像素，请先缩小。")
        original_side = max(lin.shape[:2])
        lin = decast._resize_long_edge(lin, 2560)
        scale = max(lin.shape[:2]) / original_side
        if getattr(opts, "denoise", 0):
            opts.denoise = max(0, round(opts.denoise * scale))
        if getattr(opts, "sharpen_radius", 0):
            opts.sharpen_radius = max(1, opts.sharpen_radius * scale)
        positive = decast.convert_negative(lin, opts)
        return Image.fromarray((np.clip(positive, 0, 1) * 255 + .5).astype(np.uint8))

    def prepare_worker(job, paths=None, positive_only=False, discover=False):
        warnings = []
        try:
            if paths is None:
                paths = _collect_directory(Path(job["directory"]))
            elif discover and not positive_only:
                paths = _discover_related(paths)
            sources = select_sources(paths, positive_only, warnings)
            with lock:
                job["total"] = len(sources)
                job["warnings"] = list(warnings)
            for done, (path, source, data) in enumerate(sources, 1):
                with lock:
                    job["message"] = "正在准备 " + path.name
                try:
                    image = (saved_positive(path, data, warnings) if source == "saved"
                             else _positive_image(path))
                    index = len(job["items"])
                    cached = job["cache"] / f"positive-{index}.jpg"
                    _rgb(image).save(cached, "JPEG", quality=95, subsampling=0,
                                     icc_profile=decast._srgb_icc_bytes())
                    alpha_cache = None
                    if image.mode == "RGBA":
                        alpha_cache = job["cache"] / f"positive-{index}.png"
                        image.save(alpha_cache, "PNG", icc_profile=decast._srgb_icc_bytes())
                    thumb = _rgb(image)
                    thumb.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                    thumb.save(job["cache"] / f"thumb-{index}.jpg", "JPEG", quality=87)
                    item = dict(id=index, path=str(path), name=path.name, source=source,
                                number=index + 1, width=image.width, height=image.height,
                                thumb=f"/api/sheet/thumb/{job['id']}/{index}",
                                cache=str(alpha_cache or cached))
                    item["name"] = job.get("uploadNames", {}).get(str(path), path.name)
                    with lock:
                        job["items"].append(item)
                except Exception as exc:
                    warnings.append(f"{path.name} 未载入：{exc}")
                with lock:
                    job["done"] = done
                    job["warnings"] = list(warnings)
            with lock:
                job["state"] = "ready" if job["items"] else "failed"
                job["message"] = (f"已准备 {len(job['items'])} 张照片" if job["items"]
                                  else "没有可用的成片。请先导出照片，或保存调片参数。")
                job["touched"] = time.monotonic()
        except Exception as exc:
            with lock:
                job.update(state="failed", message="载入失败：" + str(exc),
                           warnings=list(warnings), touched=time.monotonic())

    def catalog_data():
        catalog = BASE_DIR / "data" / "film_stocks.json"
        if not catalog.is_file():
            raise SheetInputError("胶卷资料库尚未准备好，请稍后重试。")
        with catalog.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data.get("stocks"), list):
            raise SheetInputError("胶卷资料库格式不正确。")
        return data

    def render_request(body, preview):
        job = get_job(body.get("job"), ready=True)
        with lock:
            available = {item["id"]: dict(item) for item in job["items"]}
            background = job["background"]
        order = body.get("order", list(available))
        if (not isinstance(order, list) or not order or len(order) > MAX_FRAMES
                or any(type(index) is not int or index not in available for index in order)
                or len(set(order)) != len(order)):
            raise SheetInputError("照片顺序无效，至少需要一张照片，且不能重复。")
        config = copy.deepcopy(body.get("config", {}))
        if not isinstance(config, dict):
            raise SheetInputError("排版参数必须是对象。")
        _check_numbers(config)
        if preview:
            config["width"] = 1200
        else:
            raw_width = config.get("width", 3600)
            if isinstance(raw_width, bool) or not isinstance(raw_width, (int, float)):
                raise SheetInputError("输出宽度必须是数字。")
            width = int(raw_width)
            if not 1200 <= width <= 10000:
                raise SheetInputError("输出宽度需要在 1200 到 10000 像素之间。")
            config["width"] = width
        size = sheet_size(len(order), config)
        if size[0] * size[1] > MAX_EXPORT_PIXELS:
            raise SheetInputError("排版超过 8000 万像素，请降低输出宽度或增加每行张数。")
        stocks = catalog_data()["stocks"]
        stock_id = body.get("stockId")
        stock = next((s for s in stocks if s.get("id") == stock_id), None)
        if stock_id and stock is None:
            raise SheetInputError("所选胶卷型号不存在，请重新选择。")
        stock = copy.deepcopy(stock or (stocks[0] if stocks else {}))
        chosen = [available[index] for index in order]
        if (config.get("background") or {}).get("sourceIndex") == "custom":
            if not background:
                raise SheetInputError("请先上传自定义背景图片。")
            if preview:
                config["_backgroundImage"] = preview_images.get(
                    (job["id"], background, 4000), lambda: _positive_image(background, 4000))
            else:
                config["_backgroundImage"] = _positive_image(background, 4000)
        return job, chosen, config, stock

    def load_render_images(chosen, config, preview_job=None):
        result = []
        columns = float(config.get("columns", 6))
        cell_side = max(64, math.ceil(config["width"] / columns * 1.6))
        background = config.get("background") or {}
        background_index = background.get("sourceIndex", 0)
        overrides = config.get("frameOverrides") or []
        for index, item in enumerate(chosen):
            override = overrides[index] if index < len(overrides) else {}
            zoom = ((override.get("crop") or {}).get("scale", 1)
                    if isinstance(override, dict) else 1)
            try:
                max_side = min(2560, max(cell_side, math.ceil(cell_side * float(zoom))))
            except (TypeError, ValueError, OverflowError):
                raise SheetInputError("单张裁剪缩放无效。") from None
            if background.get("mode", "blur") == "blur" and index == background_index:
                max_side = max(1200, max_side)
            def decode():
                with Image.open(item["cache"]) as source:
                    image = source.copy()
                image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                return image
            image = (preview_images.get((preview_job, item["cache"], max_side), decode)
                     if preview_job is not None else decode())
            result.append(image)
        return result

    def fallback_directory():
        return next((Path(p).resolve() for p in get_start_dirs() if Path(p).is_dir()), BASE_DIR)

    def reserve_output(job, value, extension):
        suffix = "." + extension
        if value:
            if not isinstance(value, str) or "\x00" in value:
                raise SheetInputError("输出位置无效。")
            requested = Path(value).expanduser().resolve()
            if requested.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                folder = requested.parent
                filename = requested.stem + suffix
            else:
                folder = requested
                filename = ""
        else:
            folder = Path(job["directory"]) / "整卷展示"
            filename = ""
        folder.mkdir(parents=True, exist_ok=True)
        if not filename:
            label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", job["label"]).strip(". ") or "胶卷"
            filename = f"{label[:100]}-{time.strftime('%Y%m%d-%H%M%S')}{suffix}"
        for attempt in range(1000):
            path = folder / filename
            if attempt:
                path = path.with_name(f"{path.stem}-{attempt}{path.suffix}")
            try:
                with path.open("xb"):
                    pass
                return path
            except FileExistsError:
                continue
        raise SheetInputError("输出文件名已被占用，请换一个位置。")

    def export_worker(record, chosen, config, stock, extension):
        try:
            with lock:
                record["message"] = "正在生成整卷展示"
            image = render_sheet(load_render_images(chosen, config), config, stock)
            image = _rgb(image) if extension == "jpg" else image
            options = dict(icc_profile=decast._srgb_icc_bytes(), dpi=(300, 300))
            if extension == "jpg":
                options.update(quality=96, subsampling=0)
            image.save(record["out"], "JPEG" if extension == "jpg" else "PNG", **options)
            with lock:
                record.update(state="ready", done=1, message="导出完成")
        except Exception as exc:
            Path(record["out"]).unlink(missing_ok=True)
            with lock:
                record.update(state="failed", error="导出失败：" + str(exc), message="导出失败")

    @blueprint.get("/sheet")
    def editor():
        return render_template("sheet.html")

    @blueprint.get("/api/sheet/catalog")
    def catalog():
        try:
            return jsonify(ok=True, **catalog_data())
        except Exception as exc:
            return _error(exc)

    @blueprint.post("/api/sheet/prepare")
    def prepare():
        try:
            body = _json_object()
            if body.get("directory") and body.get("paths"):
                raise SheetInputError("请选择文件夹或图片列表中的一种来源。")
            if body.get("directory"):
                directory = _path(body["directory"], directory=True)
                job = new_job(directory, directory.name)
                executor.submit(prepare_worker, job)
            else:
                values = body.get("paths")
                if not isinstance(values, list) or not values or len(values) > 1000:
                    raise SheetInputError("请选择图片，单次最多传入 1000 个路径。")
                paths = list(dict.fromkeys(_path(value) for value in values))
                directory = Path(os.path.commonpath([str(p.parent) for p in paths]))
                job = new_job(directory, directory.name)
                executor.submit(prepare_worker, job, paths, body.get("positiveOnly") is True, True)
            return jsonify(ok=True, job=job["id"])
        except Exception as exc:
            return _error(exc)

    @blueprint.get("/api/sheet/job/<identifier>")
    def job_state(identifier):
        try:
            job = get_job(identifier)
            with lock:
                data = {key: job[key] for key in ("state", "done", "total", "message", "directory", "label")}
                data["items"] = [{k: v for k, v in item.items() if k != "cache"}
                                 for item in job["items"]]
                data["warnings"] = list(job["warnings"])
                data["hasBackground"] = bool(job["background"])
            return jsonify(ok=True, job=identifier, **data)
        except Exception as exc:
            return _error(exc, 404)

    @blueprint.get("/api/sheet/thumb/<identifier>/<int:index>")
    def thumbnail(identifier, index):
        try:
            job = get_job(identifier)
            with lock:
                if index >= len(job["items"]):
                    raise SheetInputError("找不到这张照片。")
            return send_file(job["cache"] / f"thumb-{index}.jpg", mimetype="image/jpeg", max_age=3600)
        except Exception as exc:
            return _error(exc, 404)

    @blueprint.post("/api/sheet/preview")
    def preview():
        job = None
        try:
            body = _json_object()
            with lock:
                job = get_job(body.get("job"), ready=True)
                job["users"] += 1
            # A lease protects cached files during the whole render. Only this
            # roll is serialized; state polling and other rolls stay responsive.
            with job["preview_lock"]:
                _, chosen, config, stock = render_request(body, True)
                images = load_render_images(chosen, config, job["id"])
                output_config = copy.deepcopy(body.get("config", {}))
                output_config.setdefault("width", 3600)
                try:
                    output_size = sheet_size(len(chosen), output_config)
                except (ValueError, TypeError):
                    # Keep a valid small preview available for oversized export settings.
                    output_size = None
                result = render_sheet(images, config, stock)
                buffer = io.BytesIO()
                result.save(buffer, "PNG", icc_profile=decast._srgb_icc_bytes())
            buffer.seek(0)
            response = send_file(buffer, mimetype="image/png", max_age=0)
            if output_size is not None:
                response.headers["X-Sheet-Width"] = str(output_size[0])
                response.headers["X-Sheet-Height"] = str(output_size[1])
            return response
        except Exception as exc:
            return _error(exc)
        finally:
            if job is not None:
                with lock:
                    job["users"] -= 1

    @blueprint.post("/api/sheet/export")
    def start_export():
        try:
            body = _json_object()
            extension = str(body.get("format", "png")).lower()
            if extension not in {"png", "jpg", "jpeg"}:
                raise SheetInputError("整卷展示支持 PNG 和 JPG 导出。")
            extension = "jpg" if extension == "jpeg" else extension
            with lock:
                job, chosen, config, stock = render_request(body, False)
                if sum(e["state"] == "running" for e in exports.values()) >= 4:
                    raise SheetInputError("导出队列已满，请等当前任务完成。")
                identifier = uuid.uuid4().hex
                output = reserve_output(job, body.get("out"), extension)
                record = dict(id=identifier, job=job["id"], state="running", done=0,
                              total=1, out=str(output), error=None, message="等待导出")
                exports[identifier] = record
            executor.submit(export_worker, record, chosen, config, stock, extension)
            return jsonify(ok=True, export=identifier)
        except Exception as exc:
            return _error(exc)

    @blueprint.get("/api/sheet/export/<identifier>")
    def export_state(identifier):
        with lock:
            record = exports.get(identifier)
            if record is None:
                return _error("找不到这个导出任务。", 404)
            return jsonify(ok=True, **{k: v for k, v in record.items() if k not in {"job", "id"}})

    @blueprint.get("/api/sheet/download/<identifier>")
    def download(identifier):
        with lock:
            record = exports.get(identifier)
            if record is None or record["state"] != "ready":
                return _error("导出尚未完成或已经过期。", 404)
            path = record["out"]
        return send_file(path, as_attachment=True, download_name=Path(path).name)

    @blueprint.post("/api/sheet/project/export")
    def project_export():
        job = None
        bundle = None
        leased = False
        try:
            with lock:
                job, chosen, config, stock = render_request(_json_object(), False)
                job["users"] += 1
                leased = True
                background = job["background"]
            serialized_config = {key: value for key, value in config.items()
                                 if key != "_backgroundImage"}
            overrides = serialized_config.get("frameOverrides") or []
            assets = []
            files = []
            for index, item in enumerate(chosen):
                cached = Path(item["cache"])
                filename = f"assets/{index:03d}{cached.suffix.lower()}"
                override = overrides[index] if index < len(overrides) else {}
                if not isinstance(override, dict):
                    raise SheetInputError("单张照片的排版参数无效。")
                assets.append(dict(file=filename, name=item["name"], sourcePath=item["path"],
                                   override=override))
                files.append((cached, filename))
            manifest = dict(type="NegativeMasterSheet", version=2, stockId=stock.get("id"),
                            config=serialized_config, assets=assets)
            # Save an uploaded background even when temporarily viewing solid/gradient.
            if background:
                bg_path = Path(background)
                filename = "assets/background" + bg_path.suffix.lower()
                manifest["backgroundFile"] = filename
                files.append((bg_path, filename))
            encoded_manifest = json.dumps(manifest, ensure_ascii=False, allow_nan=False,
                                           separators=(",", ":")).encode("utf-8")
            if len(encoded_manifest) > 2 * 1024 * 1024:
                raise SheetInputError("项目参数超过 2 MB，请减少排版文字。")
            if sum(path.stat().st_size for path, _ in files) + len(encoded_manifest) > MAX_PROJECT_BYTES:
                raise SheetInputError("项目素材超过 500 MB，请减少照片数量。")
            bundle = job["cache"] / ("project-" + uuid.uuid4().hex + ".zip")
            with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", encoded_manifest,
                                 compress_type=zipfile.ZIP_DEFLATED)
                for path, name in files:
                    archive.write(path, name)
            if bundle.stat().st_size > MAX_PROJECT_BYTES:
                raise SheetInputError("项目压缩包超过 500 MB，请减少照片数量。")
            label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", job["label"]).strip(". ") or "胶卷"
            response = send_file(bundle, mimetype="application/zip", as_attachment=True,
                                 download_name=label[:100] + "-整卷项目.zip", max_age=0)

            def release_bundle():
                bundle.unlink(missing_ok=True)
                with lock:
                    job["users"] -= 1

            response.direct_passthrough = False
            response.call_on_close(release_bundle)
            leased = False  # The response now owns the lease until its stream closes.
            return response
        except Exception as exc:
            if bundle is not None:
                bundle.unlink(missing_ok=True)
            return _error(exc)
        finally:
            if leased:
                with lock:
                    job["users"] -= 1

    @blueprint.post("/api/sheet/project/import")
    def project_import():
        job = None
        try:
            upload = request.files.get("file")
            if upload is None or not (upload.filename or "").lower().endswith(".zip"):
                raise SheetInputError("请选择保存过的整卷项目 ZIP 文件。")
            with tempfile.TemporaryDirectory(prefix="decast-sheet-project-") as staging:
                package = Path(staging) / "project.zip"
                received = 0
                with package.open("xb") as handle:
                    while True:
                        chunk = upload.stream.read(1024 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > MAX_PROJECT_BYTES:
                            raise SheetInputError("整卷项目不能超过 500 MB。")
                        handle.write(chunk)
                with zipfile.ZipFile(package, "r") as archive:
                    entries = archive.infolist()
                    if not entries or len(entries) > 245:
                        raise SheetInputError("项目压缩包文件数量不正确，最多允许 245 项。")
                    names = set()
                    declared_size = 0
                    for entry in entries:
                        _archive_name(entry.filename)
                        if "\x00" in getattr(entry, "orig_filename", ""):
                            raise SheetInputError("项目压缩包包含无效文件名。")
                        if entry.filename in names:
                            raise SheetInputError("项目压缩包包含重复文件名。")
                        names.add(entry.filename)
                        mode = stat.S_IFMT(entry.external_attr >> 16)
                        if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                            raise SheetInputError("项目压缩包不能包含符号链接或特殊文件。")
                        if entry.flag_bits & 1:
                            raise SheetInputError("不支持加密的项目压缩包。")
                        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                            raise SheetInputError("项目压缩包使用了不支持的压缩方式。")
                        declared_size += entry.file_size
                        if declared_size > MAX_PROJECT_BYTES:
                            raise SheetInputError("项目解压后的素材超过 500 MB。")
                    if "manifest.json" not in names:
                        raise SheetInputError("项目缺少 manifest.json，无法读取。")
                    if archive.getinfo("manifest.json").file_size > 2 * 1024 * 1024:
                        raise SheetInputError("项目参数文件超过 2 MB。")
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    if (not isinstance(manifest, dict) or manifest.get("type") != "NegativeMasterSheet"
                            or manifest.get("version") != 2):
                        raise SheetInputError("项目类型或版本不受支持。")
                    assets = manifest.get("assets")
                    if not isinstance(assets, list) or not 1 <= len(assets) <= MAX_FRAMES:
                        raise SheetInputError("整卷项目需要包含 1 到 240 张照片。")
                    photo_names = []
                    for asset in assets:
                        if not isinstance(asset, dict):
                            raise SheetInputError("项目照片信息格式不正确。")
                        name = _project_image_name(asset.get("file"))
                        if name not in names or name in photo_names:
                            raise SheetInputError("项目包含丢失或重复的照片素材。")
                        if not isinstance(asset.get("override", {}), dict):
                            raise SheetInputError("项目单张照片的排版参数无效。")
                        _check_numbers(asset.get("override", {}))
                        photo_names.append(name)
                    background_name = manifest.get("backgroundFile")
                    if background_name is not None:
                        background_name = _project_image_name(background_name)
                        if background_name not in names:
                            raise SheetInputError("项目缺少自定义背景图片。")
                    allowed = set(photo_names) | {"manifest.json"}
                    if background_name:
                        allowed.add(background_name)
                    for name in names:
                        if name.endswith("/"):
                            if not any(asset.startswith(name) for asset in allowed):
                                raise SheetInputError("项目包含未声明的文件夹。")
                        elif name not in allowed:
                            raise SheetInputError("项目包含未声明的文件，只能导入照片和背景素材。")
                    config = manifest.get("config", {})
                    if not isinstance(config, dict):
                        raise SheetInputError("项目排版设置格式不正确。")
                    _check_numbers(config)
                    sheet_size(len(assets), config)
                    if ((config.get("background") or {}).get("sourceIndex") == "custom"
                            and not background_name):
                        raise SheetInputError("项目使用了自定义背景，但缺少背景素材。")
                    stock_id = manifest.get("stockId")
                    if not any(stock.get("id") == stock_id for stock in catalog_data()["stocks"]):
                        raise SheetInputError("项目使用的胶卷型号不在当前资料库中。")
                    job = new_job(fallback_directory(), Path(upload.filename).stem[:100])
                    extracted = job["cache"] / "project-assets"
                    extracted.mkdir()
                    actual_size = 0

                    def extract_image(member, destination):
                        nonlocal actual_size
                        if archive.getinfo(member).file_size > MAX_UPLOAD_BYTES:
                            raise SheetInputError("项目单张素材不能超过 80 MB。")
                        individual_size = 0
                        with archive.open(member) as source, destination.open("xb") as target:
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                individual_size += len(chunk)
                                actual_size += len(chunk)
                                if individual_size > MAX_UPLOAD_BYTES or actual_size > MAX_PROJECT_BYTES:
                                    raise SheetInputError("项目素材超过大小限制。")
                                target.write(chunk)
                        with Image.open(destination) as image:
                            if image.width * image.height > MAX_IMAGE_PIXELS:
                                raise SheetInputError("项目单张素材超过 1.8 亿像素。")
                            image.verify()

                    paths = []
                    frame_options = {}
                    display_names = {}
                    for index, asset in enumerate(assets):
                        destination = extracted / f"{index:03d}-photo{PurePosixPath(asset['file']).suffix.lower()}"
                        extract_image(asset["file"], destination)
                        paths.append(destination)
                        frame_options[str(destination)] = copy.deepcopy(asset.get("override", {}))
                        display_names[str(destination)] = str(asset.get("name") or destination.name)[:250]
                    if background_name:
                        destination = extracted / ("background" + PurePosixPath(background_name).suffix.lower())
                        extract_image(background_name, destination)
                        job["background"] = str(destination)
                    job["uploadNames"] = display_names
                    # sourcePath is deliberately never inspected: portable assets are authoritative.
                    project = dict(type="NegativeMasterSheet", version=1, stockId=stock_id,
                                   config=copy.deepcopy(config), sources=[str(path) for path in paths],
                                   frameOptions=frame_options)
                    executor.submit(prepare_worker, job, paths, True)
            return jsonify(ok=True, job=job["id"], project=project)
        except zipfile.BadZipFile:
            message = "这个文件不是有效的整卷项目 ZIP，或文件已损坏。"
        except Exception as exc:
            message = str(exc)
        if job is not None:
            with lock:
                jobs.pop(job["id"], None)
            shutil.rmtree(job["cache"], ignore_errors=True)
        return _error(message)

    def write_upload(file, folder, index):
        name = Path(file.filename or "").name
        ext = Path(name).suffix.lower()
        if ext in decast.RAW_EXTS:
            raise SheetInputError("上传 RAW 无法携带已保存的调片参数，请选择胶卷文件夹或上传导出的成片。")
        if ext not in IMAGE_EXTS:
            raise SheetInputError("请上传 JPG、PNG、TIFF 或 WebP 图片。")
        destination = folder / f"{index:03d}-{uuid.uuid4().hex[:8]}{ext}"
        count = 0
        with destination.open("xb") as handle:
            while True:
                chunk = file.stream.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_UPLOAD_BYTES:
                    raise SheetInputError("单张上传图片不能超过 80 MB。")
                handle.write(chunk)
        # Check dimensions and decoder before the file reaches a worker.
        with Image.open(destination) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise SheetInputError("单张图片超过 1.8 亿像素，请先缩小。")
            image.verify()
        return destination, count, name

    @blueprint.post("/api/sheet/upload")
    def upload():
        job = None
        try:
            files = request.files.getlist("files") or request.files.getlist("file")
            if not files or len(files) > MAX_FRAMES:
                raise SheetInputError("请上传 1 到 240 张成片。")
            directory = fallback_directory()
            job = new_job(directory, "上传照片")
            upload_dir = job["cache"] / "uploads"
            upload_dir.mkdir()
            paths = []
            total_bytes = 0
            upload_names = {}
            for index, file in enumerate(files):
                path, count, name = write_upload(file, upload_dir, index)
                total_bytes += count
                if total_bytes > MAX_UPLOAD_TOTAL:
                    raise SheetInputError("单次上传不能超过 512 MB，请分批选择。")
                paths.append(path)
                upload_names[str(path)] = name
            job["uploadNames"] = upload_names
            executor.submit(prepare_worker, job, paths, True)
            return jsonify(ok=True, job=job["id"])
        except Exception as exc:
            if job is not None:
                with lock:
                    jobs.pop(job["id"], None)
                shutil.rmtree(job["cache"], ignore_errors=True)
            return _error(exc)

    @blueprint.post("/api/sheet/background")
    def background():
        destination = None
        job = None
        try:
            with lock:
                job = get_job(request.form.get("job"), ready=True)
                job["users"] += 1
            file = request.files.get("file")
            if file is None:
                raise SheetInputError("请选择一张背景图片。")
            folder = job["cache"] / "backgrounds"
            folder.mkdir(exist_ok=True)
            destination, _, _ = write_upload(file, folder, 0)
            with lock:
                job["background"] = str(destination)
            return jsonify(ok=True)
        except Exception as exc:
            if destination is not None:
                destination.unlink(missing_ok=True)
            return _error(exc)
        finally:
            if job is not None:
                with lock:
                    job["users"] -= 1

    # Kept private to this blueprint; useful for orderly shutdown and isolated tests.
    blueprint.sheet_jobs = jobs
    blueprint.sheet_executor = executor
    blueprint.sheet_lock = lock
    blueprint.sheet_preview_images = preview_images
    return blueprint

"""Local film archive. Source images are references; only derivatives are stored.

Each request owns a SQLite connection. Backups contain a versioned manifest and
managed JPEG derivatives, never source photographs or arbitrary disk contents.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import urlparse
import uuid
import zipfile

from flask import Blueprint, jsonify, render_template, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError

BASE_DIR = Path(__file__).resolve().parent
STATUSES = {"planned": "待拍摄", "shooting": "拍摄中", "developing": "冲洗中", "scanning": "待扫描", "archived": "已归档"}
TEXT_LIMITS = {"title": 160, "roll_number": 60, "stock_id": 100, "stock_name": 160,
               "format": 40, "camera": 160, "lens": 160, "place": 240, "lab": 160,
               "process": 100, "development": 500, "storage": 200, "notes": 12000,
               "cover_source": 500, "cover_credit": 240}
DATE_FIELDS = ("date_start", "date_end", "developed_on")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2", ".orf", ".pef", ".srw"}
MAX_FRAMES = 240
MAX_PIXELS = 100_000_000
MAX_BACKUP = 256 * 1024 * 1024
MAX_MANIFEST = 16 * 1024 * 1024
ASSET_RE = re.compile(r"^[a-f0-9]{64}\.jpg$")


class ArchiveError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def text_value(value, maximum, label):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ArchiveError(f"{label} 必须为不超过 {maximum} 字的文字。")
    return value.strip()


def clean_roll(body):
    if not isinstance(body, dict):
        raise ArchiveError("胶卷资料必须为对象。")
    result = {key: text_value(body.get(key, ""), limit, key) for key, limit in TEXT_LIMITS.items()}
    if not result["title"]:
        raise ArchiveError("请填写胶卷名称。")
    for key in DATE_FIELDS:
        value = text_value(body.get(key, ""), 10, key)
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise ArchiveError("日期请使用 YYYY-MM-DD 格式。") from None
        result[key] = value
    if result["date_start"] and result["date_end"] and result["date_start"] > result["date_end"]:
        raise ArchiveError("拍摄结束日期不能早于开始日期。")
    result["status"] = body.get("status", "planned")
    if not isinstance(result["status"], str) or result["status"] not in STATUSES:
        raise ArchiveError("胶卷状态无效。")
    for key in ("iso", "exposure_index"):
        value = body.get(key)
        if value in ("", None):
            result[key] = None
        elif type(value) is int and 1 <= value <= 102400:
            result[key] = value
        else:
            raise ArchiveError("ISO / 实拍 EI 必须为 1–102400 的整数。")
    tags = body.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 30:
        raise ArchiveError("标签最多 30 个。")
    result["tags"] = list(dict.fromkeys(text_value(t, 50, "标签") for t in tags if t))
    source = result["cover_source"]
    if source and (urlparse(source).scheme not in {"https", "http"} or not urlparse(source).netloc):
        raise ArchiveError("封面来源请使用 http / https 网页地址，拍摄者请填在署名栏。")
    return result


class ArchiveStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.assets = self.root / "assets"
        self.lock = threading.RLock()
        self._initialized = False

    def initialize(self):
        with self.lock:
            if self._initialized:
                return
            self.assets.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.root / "archive.sqlite3")) as db, db:
                db.execute("PRAGMA journal_mode=WAL")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ArchiveError("档案数据库版本较新，请使用新版 NegativeMaster。")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS rolls (
                        id TEXT PRIMARY KEY, data TEXT NOT NULL, cover TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS frames (
                        id TEXT PRIMARY KEY, roll_id TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
                        path TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL,
                        thumb TEXT NOT NULL DEFAULT '', rating INTEGER NOT NULL DEFAULT 0,
                        notes TEXT NOT NULL DEFAULT '', UNIQUE(roll_id, path));
                    CREATE INDEX IF NOT EXISTS frames_roll ON frames(roll_id, position);
                    PRAGMA user_version=1;
                """)
            self._initialized = True

    @contextmanager
    def connection(self):
        self.initialize()
        db = sqlite3.connect(self.root / "archive.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def roll(self, db, identifier, frames=False):
        row = db.execute("SELECT * FROM rolls WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise LookupError("没有找到这卷胶片，可能已被删除。")
        result = json.loads(row["data"])
        result.update(id=row["id"], created_at=row["created_at"], updated_at=row["updated_at"], cover=row["cover"])
        result["frame_count"] = db.execute("SELECT COUNT(*) FROM frames WHERE roll_id=?", (identifier,)).fetchone()[0]
        if frames:
            result["frames"] = [dict(row) for row in db.execute("SELECT * FROM frames WHERE roll_id=? ORDER BY position,id", (identifier,))]
            for frame in result["frames"]:
                frame["missing"] = not Path(frame["path"]).is_file()
        return result

    def asset(self, name):
        if not isinstance(name, str) or not ASSET_RE.fullmatch(name):
            raise ArchiveError("无效的档案图片编号。")
        return self.assets / name

    def save_image(self, source):
        with Image.open(source) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ArchiveError("图片超过 1 亿像素，请先缩小。")
            original.draft("RGB", (1200, 1200))
            image = ImageOps.exif_transpose(original)
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                image = rgb
            stream = io.BytesIO()
            image.convert("RGB").save(stream, "JPEG", quality=86)
        data = stream.getvalue()
        name = hashlib.sha256(data).hexdigest() + ".jpg"
        self.initialize()
        with self.lock:
            target = self.asset(name)
            if not target.exists():
                temp = self.assets / (uuid.uuid4().hex + ".tmp")
                try:
                    temp.write_bytes(data)
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
        return name


def create_archive_blueprint(data_dir=None):
    store = ArchiveStore(data_dir or os.environ.get("NEGATIVEMASTER_ARCHIVE_DIR") or BASE_DIR / "archive_data")
    bp = Blueprint("archive", __name__, template_folder="templates")
    bp.archive_store = store

    @bp.before_request
    def guard():
        # Multipart uploads need CSRF protection as much as JSON writes. A
        # cross-origin page must not be able to mutate a loopback archive.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-NegativeMaster-Archive") != "1":
                return jsonify(ok=False, error="请从胶片档案页面执行操作。"), 403
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                return jsonify(ok=False, error="不接受其他网站发来的档案修改。"), 403
            request.max_content_length = MAX_BACKUP + 1024 * 1024

    @bp.errorhandler(ArchiveError)
    def bad_input(exc):
        return jsonify(ok=False, error=str(exc)), 400

    @bp.errorhandler(LookupError)
    def missing(exc):
        return jsonify(ok=False, error=str(exc)), 404

    @bp.errorhandler(sqlite3.Error)
    def db_error(exc):
        return jsonify(ok=False, error="档案数据库暂不可用，请检查目录权限或稍后重试。"), 503

    @bp.errorhandler(OSError)
    def disk_error(exc):
        return jsonify(ok=False, error="无法读取或保存文件，请检查文件路径、磁盘空间与访问权限。"), 400

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ArchiveError("请求内容必须为 JSON 对象。")
        return value

    @bp.get("/archive")
    def archive_page():
        return render_template("archive.html")

    @bp.get("/api/archive/catalog")
    def catalog():
        stocks = json.loads((BASE_DIR / "data/film_stocks.json").read_text(encoding="utf-8"))["stocks"]
        return jsonify(ok=True, stocks=stocks, statuses=STATUSES, storage=str(store.root))

    @bp.get("/api/archive/rolls")
    def list_rolls():
        with store.connection() as db:
            rolls = [store.roll(db, row[0]) for row in db.execute("SELECT id FROM rolls ORDER BY updated_at DESC")]
        stats = {"rolls": len(rolls), "frames": sum(r["frame_count"] for r in rolls),
                 "archived": sum(r["status"] == "archived" for r in rolls)}
        years = sorted({r["date_start"][:4] for r in rolls if r["date_start"]}, reverse=True)
        q = request.args.get("q", "").strip().casefold()
        status = request.args.get("status", "")
        year = request.args.get("year", "")
        if q:
            rolls = [r for r in rolls if q in " ".join(str(r[k]) for k in TEXT_LIMITS if k not in {"cover_source", "cover_credit"}).casefold() + " " + " ".join(r["tags"]).casefold()]
        if status:
            rolls = [r for r in rolls if r["status"] == status]
        if year:
            rolls = [r for r in rolls if r["date_start"].startswith(year)]
        order = request.args.get("sort", "date")
        if order == "date":
            rolls.sort(key=lambda r: (r["date_start"], r["created_at"]), reverse=True)
        elif order == "title":
            rolls.sort(key=lambda r: r["title"].casefold())
        return jsonify(ok=True, rolls=rolls, stats=stats, years=years)

    @bp.post("/api/archive/rolls")
    def create_roll():
        data = clean_roll(body())
        identifier, timestamp = uuid.uuid4().hex, now()
        with store.connection() as db:
            db.execute("INSERT INTO rolls VALUES (?,?,?,?,?)", (identifier, json.dumps(data, ensure_ascii=False), "", timestamp, timestamp))
            result = store.roll(db, identifier, frames=True)
        return jsonify(ok=True, roll=result), 201

    @bp.route("/api/archive/rolls/<identifier>", methods=["GET", "PUT", "DELETE"])
    def roll_detail(identifier):
        with store.connection() as db:
            current = store.roll(db, identifier, frames=True)
            if request.method == "DELETE":
                db.execute("DELETE FROM rolls WHERE id=?", (identifier,))
                return jsonify(ok=True)
            if request.method == "PUT":
                submitted = body()
                if submitted.get("updated_at") != current["updated_at"]:
                    return jsonify(ok=False, error="这卷资料已在其他窗口更新。请重新打开后再编辑。"), 409
                clean = clean_roll(submitted)
                cursor = db.execute("UPDATE rolls SET data=?,updated_at=? WHERE id=? AND updated_at=?",
                                    (json.dumps(clean, ensure_ascii=False), now(), identifier, submitted["updated_at"]))
                if not cursor.rowcount:
                    return jsonify(ok=False, error="资料刚刚被更新，请重新打开后再编辑。"), 409
                current = store.roll(db, identifier, frames=True)
        return jsonify(ok=True, roll=current)

    @bp.post("/api/archive/rolls/<identifier>/frames")
    def add_frames(identifier):
        data = body()
        folder = Path(text_value(data.get("directory", ""), 4096, "文件夹路径")).expanduser()
        if not data.get("directory") or not folder.is_dir():
            raise ArchiveError("请填写现有的本地照片文件夹路径。")
        mode = data.get("mode", "positive")
        if mode not in {"positive", "all"}:
            raise ArchiveError("照片类型无效。")
        # Deliberately one directory only: this is a roll, not a disk crawler.
        paths = [p.resolve() for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS | RAW_EXTS]
        if mode == "positive":
            paths = [p for p in paths if p.stem.lower().endswith("_pos")]
        paths.sort(key=lambda p: [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", p.name)])
        if not paths:
            raise ArchiveError("没有找到照片。默认只关联 *_pos 成片，可切换为全部图片。")
        if len(paths) > MAX_FRAMES:
            raise ArchiveError("一卷最多关联 240 张，请选择具体胶卷的文件夹。")
        with store.connection() as db:
            current = store.roll(db, identifier, frames=True)
        seen = {os.path.normcase(f["path"]) for f in current["frames"]}
        paths = [p for p in paths if os.path.normcase(str(p)) not in seen]
        if len(paths) + len(seen) > MAX_FRAMES:
            raise ArchiveError("关联后超过每卷 240 张的上限。")
        prepared, warnings = [], []
        for path in paths:
            thumb = ""
            if path.suffix.lower() in IMAGE_EXTS:
                try:
                    thumb = store.save_image(path)
                except (OSError, ValueError, Image.DecompressionBombError) as exc:
                    warnings.append(f"{path.name}：未生成预览，请检查图片是否有效或过大。")
            else:
                warnings.append(f"{path.name}：RAW 保留文件关联，请在调片区导出成片后关联预览。")
            prepared.append((uuid.uuid4().hex, str(path), path.name, thumb))
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            store.roll(db, identifier)
            count = db.execute("SELECT COUNT(*) FROM frames WHERE roll_id=?", (identifier,)).fetchone()[0]
            if count + len(prepared) > MAX_FRAMES:
                raise ArchiveError("关联后超过每卷 240 张的上限。")
            position = db.execute("SELECT COALESCE(MAX(position),0) FROM frames WHERE roll_id=?", (identifier,)).fetchone()[0]
            added = 0
            for fid, path, name, thumb in prepared:
                cursor = db.execute("INSERT OR IGNORE INTO frames(id,roll_id,path,name,position,thumb) VALUES (?,?,?,?,?,?)",
                                    (fid, identifier, path, name, position + added + 1, thumb))
                added += cursor.rowcount
            db.execute("UPDATE rolls SET updated_at=? WHERE id=?", (now(), identifier))
            result = store.roll(db, identifier, frames=True)
        return jsonify(ok=True, roll=result, added=added, warnings=warnings)

    @bp.route("/api/archive/rolls/<identifier>/frames/<fid>", methods=["PUT", "DELETE"])
    def edit_frame(identifier, fid):
        with store.connection() as db:
            store.roll(db, identifier)
            frame = db.execute("SELECT * FROM frames WHERE roll_id=? AND id=?", (identifier, fid)).fetchone()
            if not frame:
                raise LookupError("找不到这张照片。")
            if request.method == "DELETE":
                db.execute("DELETE FROM frames WHERE id=?", (fid,))
            else:
                data = body()
                rating = data.get("rating", frame["rating"])
                if type(rating) is not int or not 0 <= rating <= 5:
                    raise ArchiveError("评分应为 0–5 的整数。")
                notes = text_value(data.get("notes", frame["notes"]), 2000, "照片备注")
                db.execute("UPDATE frames SET rating=?,notes=? WHERE id=?", (rating, notes, fid))
            db.execute("UPDATE rolls SET updated_at=? WHERE id=?", (now(), identifier))
            result = store.roll(db, identifier, frames=True)
        return jsonify(ok=True, roll=result)

    @bp.post("/api/archive/rolls/<identifier>/relink")
    def relink(identifier):
        data = body()
        directory = text_value(data.get("directory", ""), 4096, "文件夹路径")
        folder = Path(directory).expanduser().resolve()
        if not directory or not folder.is_dir():
            raise ArchiveError("请选择迁移后的本地照片文件夹。")
        linked = 0
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = store.roll(db, identifier, frames=True)
            # A duplicate basename is ambiguous: never guess which source it is.
            names = [f["name"] for f in current["frames"]]
            used = {os.path.normcase(f["path"]) for f in current["frames"]}
            for frame in current["frames"]:
                if names.count(frame["name"]) != 1 or Path(frame["name"]).name != frame["name"]:
                    continue
                target = (folder / frame["name"]).resolve()
                if target.suffix.lower() not in IMAGE_EXTS | RAW_EXTS or not target.is_file() or os.path.normcase(str(target)) in used:
                    continue
                db.execute("UPDATE frames SET path=? WHERE id=?", (str(target), frame["id"]))
                used.add(os.path.normcase(str(target)))
                linked += 1
            if linked:
                db.execute("UPDATE rolls SET updated_at=? WHERE id=?", (now(), identifier))
            result = store.roll(db, identifier, frames=True)
        return jsonify(ok=True, roll=result, linked=linked)

    @bp.post("/api/archive/rolls/<identifier>/cover")
    def cover(identifier):
        with store.connection() as db:
            store.roll(db, identifier)
        if request.is_json:
            data = body()
            fid = data.get("frame_id")
            with store.connection() as db:
                row = db.execute("SELECT thumb FROM frames WHERE roll_id=? AND id=?", (identifier, fid)).fetchone() if fid else None
                if fid and (not row or not row[0]):
                    raise ArchiveError("这张照片没有可用的封面预览。")
                asset = row[0] if row else ""
            source, credit = "", "本卷照片" if fid else ""
        else:
            uploaded = request.files.get("file")
            if uploaded is None:
                raise ArchiveError("请上传 JPEG、PNG、TIFF 或 WebP 封面。")
            data = uploaded.read(20 * 1024 * 1024 + 1)
            if len(data) > 20 * 1024 * 1024:
                raise ArchiveError("封面文件不能超过 20 MB。")
            source = request.form.get("source", "")
            credit = request.form.get("credit", "本人拍摄 / 上传")
            clean_roll({"title": "cover", "cover_source": source, "cover_credit": credit})
            try:
                asset = store.save_image(io.BytesIO(data))
            except (OSError, ValueError, Image.DecompressionBombError):
                raise ArchiveError("无法读取封面，请使用有效的图片（最大 1 亿像素）。") from None
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            data = store.roll(db, identifier)
            data.update(cover_source=source, cover_credit=credit)
            db.execute("UPDATE rolls SET cover=?,data=?,updated_at=? WHERE id=?", (asset, json.dumps(clean_roll(data), ensure_ascii=False), now(), identifier))
            result = store.roll(db, identifier, frames=True)
        return jsonify(ok=True, roll=result)

    @bp.get("/api/archive/assets/<name>")
    def asset(name):
        path = store.asset(name)
        with store.connection() as db:
            used = db.execute("SELECT 1 FROM rolls WHERE cover=? UNION ALL SELECT 1 FROM frames WHERE thumb=? LIMIT 1", (name, name)).fetchone()
        if not used or not path.is_file():
            raise LookupError("档案预览不存在。")
        return send_file(path, mimetype="image/jpeg", max_age=86400, conditional=True)

    @bp.get("/api/archive/backup")
    def backup():
        with store.connection() as db:
            db.execute("BEGIN")
            if db.execute("SELECT COUNT(*) FROM rolls").fetchone()[0] > 10000:
                raise ArchiveError("档案超过在线备份数量上限，请关闭应用后复制完整档案目录。")
            rolls = [store.roll(db, row[0], frames=True) for row in db.execute("SELECT id FROM rolls ORDER BY created_at")]
        assets = {r["cover"] for r in rolls if r["cover"]} | {f["thumb"] for r in rolls for f in r["frames"] if f["thumb"]}
        total = sum(store.asset(a).stat().st_size for a in assets)
        if total > MAX_BACKUP - MAX_MANIFEST:
            raise ArchiveError("预览库超过在线备份上限，请关闭应用后复制完整档案目录。")
        manifest = json.dumps({"format": "NegativeMasterArchive", "version": 1, "exported_at": now(), "originals_included": False, "rolls": rolls}, ensure_ascii=False).encode("utf-8")
        if len(manifest) > MAX_MANIFEST:
            raise ArchiveError("档案资料超过在线备份上限，请关闭应用后复制完整档案目录。")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", manifest)
            for name in sorted(assets):
                archive.write(store.asset(name), "assets/" + name)
        if stream.tell() > MAX_BACKUP:
            raise ArchiveError("备份 ZIP 超过 256 MB，请关闭应用后复制完整档案目录。")
        stream.seek(0)
        return send_file(stream, mimetype="application/zip", as_attachment=True, download_name=f"NegativeMaster-archive-{date.today().isoformat()}.zip")

    @bp.post("/api/archive/restore")
    def restore():
        uploaded = request.files.get("file")
        if not uploaded:
            raise ArchiveError("请选择 NegativeMaster 档案 ZIP 备份。")
        raw = uploaded.read(MAX_BACKUP + 1)
        if len(raw) > MAX_BACKUP:
            raise ArchiveError("备份文件不能超过 256 MB。")
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                names = {item.filename for item in infos}
                if len(names) != len(infos) or len(infos) > 50000 or sum(item.file_size for item in infos) > MAX_BACKUP:
                    raise ArchiveError("备份包含重复条目或超出容量限制。")
                if any(name != "manifest.json" and not (name.startswith("assets/") and ASSET_RE.fullmatch(name[7:])) for name in names):
                    raise ArchiveError("备份包含不受支持的路径。")
                if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > MAX_MANIFEST:
                    raise ArchiveError("备份缺少有效的档案清单。")
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict) or manifest.get("format") != "NegativeMasterArchive" or manifest.get("version") != 1:
                    raise ArchiveError("不支持此档案格式或版本。")
                rolls = manifest.get("rolls")
                if not isinstance(rolls, list) or len(rolls) > 10000:
                    raise ArchiveError("备份胶卷列表无效或过大。")
                prepared, wanted = [], set()
                for r in rolls:
                    clean = clean_roll(r)
                    cover_name = r.get("cover", "")
                    if cover_name:
                        store.asset(cover_name)
                        wanted.add(cover_name)
                    frames = r.get("frames", [])
                    if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
                        raise ArchiveError("备份中的照片数量无效。")
                    ready, seen = [], set()
                    for index, f in enumerate(frames):
                        if not isinstance(f, dict):
                            raise ArchiveError("备份中的照片资料无效。")
                        path = text_value(f.get("path", ""), 4096, "照片路径")
                        name = text_value(f.get("name", ""), 255, "照片名称")
                        if not path or path in seen or not name:
                            raise ArchiveError("备份中的照片路径为空或重复。")
                        seen.add(path)
                        thumb = f.get("thumb", "")
                        if thumb:
                            store.asset(thumb)
                            wanted.add(thumb)
                        rating = f.get("rating", 0)
                        if type(rating) is not int or not 0 <= rating <= 5:
                            raise ArchiveError("备份中的评分无效。")
                        notes = text_value(f.get("notes", ""), 2000, "照片备注")
                        ready.append((uuid.uuid4().hex, path, name, index + 1, thumb, rating, notes))
                    prepared.append((clean, cover_name, ready))
                decoded = {}
                for name in wanted:
                    entry = "assets/" + name
                    if entry not in names or archive.getinfo(entry).file_size > 8 * 1024 * 1024:
                        raise ArchiveError("备份缺少图片或图片超出限制。")
                    payload = archive.read(entry)
                    if hashlib.sha256(payload).hexdigest() + ".jpg" != name:
                        raise ArchiveError("备份图片校验失败。")
                    with Image.open(io.BytesIO(payload)) as img:
                        if img.format != "JPEG" or img.width > 1200 or img.height > 1200:
                            raise ArchiveError("备份图片不是有效的档案预览。")
                        img.verify()
                    decoded[name] = payload
        except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, TypeError, UnidentifiedImageError):
            raise ArchiveError("无法读取备份，文件可能损坏。") from None
        # Validate the complete archive before making any visible DB changes.
        # Source paths in the manifest are never opened or written during restore.
        store.initialize()
        with store.lock, store.connection() as db:
            for name, payload in decoded.items():
                target = store.asset(name)
                if not target.exists():
                    temp = store.assets / (uuid.uuid4().hex + ".tmp")
                    try:
                        temp.write_bytes(payload)
                        os.replace(temp, target)
                    finally:
                        temp.unlink(missing_ok=True)
            identifiers = []
            for data, cover_name, frames in prepared:
                identifier, timestamp = uuid.uuid4().hex, now()
                identifiers.append(identifier)
                db.execute("INSERT INTO rolls VALUES (?,?,?,?,?)", (identifier, json.dumps(data, ensure_ascii=False), cover_name, timestamp, timestamp))
                for fid, path, name, position, thumb, rating, notes in frames:
                    db.execute("INSERT INTO frames VALUES (?,?,?,?,?,?,?,?)", (fid, identifier, path, name, position, thumb, rating, notes))
        return jsonify(ok=True, imported=len(prepared), ids=identifiers)

    return bp

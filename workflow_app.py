"""Read-only conversion analysis and selective, durable roll tone updates."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
from flask import Blueprint, jsonify, request

import decast
import conversion_advisor


def representative_paths(paths, limit=12):
    """Evenly cover the ordered roll; preserve endpoints and remove duplicates."""
    if not isinstance(paths, list) or not paths or len(paths) > 600:
        raise ValueError("请选择 1–600 张同卷照片")
    if any(not isinstance(p, str) or not p.strip() for p in paths):
        raise ValueError("照片路径无效")
    unique = list(dict.fromkeys(os.path.abspath(p) for p in paths))
    if len(unique) <= limit:
        return unique
    return [unique[round(i * (len(unique) - 1) / (limit - 1))] for i in range(limit)]


def atomic_text(path, content):
    """Replace one metadata file without leaving a truncated file on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def create_workflow_blueprint(make_opts, defaults, settings_file, sidecar_path,
                              read_xml, write_xml, cache):
    bp = Blueprint("workflow", __name__)

    def saved(path):
        # A damaged sidecar must never be silently replaced by defaults.
        xml = Path(sidecar_path(path))
        if xml.is_file():
            result = read_xml(xml.read_text(encoding="utf-8"))
        elif Path(settings_file(path)).is_file():
            result = json.loads(Path(settings_file(path)).read_text(encoding="utf-8"))
        else:
            result = {"P": {**defaults, "flip": "h"}, "cropN": dict(x0=.06, y0=.06, x1=.94, y1=.94),
                      "curFmt": "free", "orient": "land", "geometrySource": "manual"}
        if not isinstance(result, dict) or not isinstance(result.get("P", {}), dict):
            raise ValueError("已存参数损坏，请先检查此照片的边车文件")
        return result

    def params_for(data):
        p = dict(data.get("P", {}))
        if data.get("cropN"):
            p["crop_rect"] = [data["cropN"][k] for k in ("x0", "y0", "x1", "y1")]
        return p

    @bp.post("/api/workflow/analyze")
    def analyze():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(ok=False, err="需要 JSON 对象"), 400
        try:
            paths = representative_paths(body.get("paths"))
            current = body.get("current") or {}
            if not isinstance(current, dict):
                raise ValueError("当前参数无效")
            current_path = os.path.abspath(body.get("current_path") or "")
            reports, errors = [], []
            for path in paths:
                try:
                    if not os.path.isfile(path):
                        raise ValueError("文件不存在")
                    data = current if path == current_path and current else saved(path)
                    params = params_for(data)
                    # Decode in isolation: analysis must not change the interactive image cache.
                    lin, _ = decast.load_image(path, make_opts(params))
                    step = max(1, math.ceil(max(lin.shape[:2]) / 1000))
                    preview = lin[::step, ::step].copy()
                    del lin
                    report = conversion_advisor.analyze_frame(preview, params)
                    report["path"] = path
                    report["name"] = os.path.basename(path)
                    reports.append(report)
                except Exception as exc:
                    errors.append({"path": path, "error": str(exc)})
            if not reports:
                return jsonify(ok=False, err="没有可分析的照片", errors=errors), 400
            result = conversion_advisor.analyze_roll(reports)
            return jsonify(ok=True, report=result, frames=reports, errors=errors,
                           sampled=len(paths), total=len(set(body["paths"])))
        except (ValueError, TypeError, KeyError) as exc:
            return jsonify(ok=False, err=str(exc)), 400

    @bp.post("/api/workflow/roll-gamma")
    def roll_gamma():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(ok=False, err="需要 JSON 对象"), 400
        try:
            paths = representative_paths(body.get("paths"), limit=600)
            key = body.get("parameter_key", "gamma")
            if key not in ("gamma", "nd_gamma"):
                raise ValueError("不支持此影调参数")
            gamma = body.get("gamma")
            if isinstance(gamma, bool) or not isinstance(gamma, (int, float)):
                raise ValueError("gamma 必须是数字")
            low, high = (1, 8) if key == "nd_gamma" else (.6, 3)
            if not math.isfinite(gamma) or not low <= gamma <= high:
                raise ValueError(f"gamma 必须在 {low}–{high} 之间")
            current = body.get("current")
            if current is not None and (not isinstance(current, dict) or
                                         not isinstance(current.get("P"), dict)):
                raise ValueError("当前参数无效")
            current_path = os.path.abspath(body.get("current_path") or "")
            updated, errors = [], []
            for path in paths:
                try:
                    if not os.path.isfile(path):
                        raise ValueError("文件不存在")
                    data = copy.deepcopy(current) if path == current_path and current else saved(path)
                    p = data.setdefault("P", {})
                    uses_nd = bool(p.get("negadoctor")) and p.get("mode", "color") == "color"
                    if p.get("mode") == "positive" or uses_nd != (key == "nd_gamma"):
                        raise ValueError("此照片的反转引擎与建议不一致，已保留原参数")
                    p[key] = float(gamma)
                    # XML is authoritative. The local JSON is a secondary cache.
                    atomic_text(sidecar_path(path), write_xml(data, path))
                    updated.append(path)
                    try:
                        atomic_text(settings_file(path), json.dumps(data, ensure_ascii=False, indent=2))
                    except OSError as exc:
                        errors.append({"path": path, "error": "XML 已保存，内部记忆未同步：" + str(exc)})
                except Exception as exc:
                    errors.append({"path": path, "error": str(exc)})
            return jsonify(ok=True, updated=updated, errors=errors, gamma=gamma)
        except (ValueError, TypeError) as exc:
            return jsonify(ok=False, err=str(exc)), 400

    return bp

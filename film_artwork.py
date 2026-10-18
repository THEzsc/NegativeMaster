"""Curated, offline cartridge artwork and attributed packaging references.

Runtime never fetches user-supplied URLs. Covers are copied only from reviewed
bundled assets, and their source and license travel with the archive backup.
"""
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT / "data/film_artwork.json").read_text(encoding="utf-8"))


def artwork(identifier):
    if not isinstance(identifier, str):
        raise ValueError("请选择有效的暗盒图案。")
    item = next((a for a in catalog()["artworks"] if a["id"] == identifier), None)
    if item is None:
        raise ValueError("这张图案不在本地图案库中，请重新选择。")
    path = ROOT / "static/film_artwork" / item["file"]
    if Path(item["file"]).name != item["file"] or not path.is_file():
        raise ValueError("图案文件缺失，请重新安装完整资源包。")
    return item, path

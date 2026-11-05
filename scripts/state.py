# -*- coding: utf-8 -*-
"""落盘：正文、族元数据、健康状态。

一条铁律：这里只做读写，不做判断。什么算「变了」由 pipeline 决定。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEXTS = DATA / "texts"
STANDARDS = DATA / "standards"
HEALTH = DATA / "health.json"

SAFE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


def safe(name: str) -> str:
    """版本号/族 id 可能出现 @ . 空格，转成安全文件名。"""
    return SAFE.sub("_", name).strip("_")[:120] or "unnamed"


def text_path(standard_id: str, edition: str) -> Path:
    return TEXTS / safe(standard_id) / f"{safe(edition)}.txt"


def save_text(standard_id: str, edition: str, text: str) -> Path:
    p = text_path(standard_id, edition)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def load_text(standard_id: str, edition: str) -> str | None:
    p = text_path(standard_id, edition)
    return p.read_text(encoding="utf-8") if p.exists() else None


def list_editions(standard_id: str) -> list[str]:
    d = TEXTS / safe(standard_id)
    return sorted(p.stem for p in d.glob("*.txt")) if d.exists() else []


def family_path(standard_id: str) -> Path:
    return STANDARDS / f"{safe(standard_id)}.json"


def load_family(standard_id: str) -> dict:
    p = family_path(standard_id)
    if not p.exists():
        base = _base_family(standard_id)
        if base is None:
            raise KeyError(f"data/standards.json 里没有族 {standard_id}")
        return base
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _base_family(standard_id: str) -> dict | None:
    reg = json.loads((DATA / "standards.json").read_text(encoding="utf-8-sig"))
    for f in reg["families"]:
        if f["id"] == standard_id:
            return dict(f)
    return None


def save_family(family: dict) -> None:
    STANDARDS.mkdir(parents=True, exist_ok=True)
    family_path(family["id"]).write_text(
        json.dumps(family, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def record_edition(standard_id: str, edition: str, meta: dict) -> dict:
    """记下「见过这一版」，并把它设为当前版本。"""
    fam = load_family(standard_id)
    eds = list(fam.get("editions") or [])
    if edition not in eds:
        eds.append(edition)
    fam["editions"] = eds
    fam["current_edition"] = edition
    fam.setdefault("edition_meta", {})[edition] = meta or {}
    save_family(fam)
    return fam


def previous_edition(standard_id: str, before: str) -> str | None:
    """按记录顺序取 before 的前一版；没有就返回 None。"""
    fam = load_family(standard_id)
    eds = list(fam.get("editions") or [])
    if before in eds:
        i = eds.index(before)
        return eds[i - 1] if i > 0 else None
    return eds[-1] if eds and eds[-1] != before else None


def save_health(payload: dict) -> None:
    HEALTH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_health() -> dict:
    if not HEALTH.exists():
        return {}
    return json.loads(HEALTH.read_text(encoding="utf-8-sig"))

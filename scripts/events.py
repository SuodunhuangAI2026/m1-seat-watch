# -*- coding: utf-8 -*-
"""变更事件：构造、落盘、去重、读取。

一天一个文件；同一族同一个目标版本只留一条，重跑不会重复。
"""
import json
import re
from pathlib import Path

from scripts.state import DATA

CHANGES = DATA / "changes"


def classify(old_ed: str, new_ed: str) -> tuple[str, float]:
    """从版本号变化推变更类型。认不准就返回 AMENDMENT + 低置信。"""
    if old_ed == new_ed:
        return "UNKNOWN", 0.1

    def parts(ed: str):
        m = re.match(r"R(\d+)\.(\d+)(?:a(\d+))?(?:c(\d+))?$", ed)
        if m:
            return ("unece", int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), int(m.group(4) or 0))
        return None

    a, b = parts(old_ed), parts(new_ed)
    if a and b:
        if b[2] > a[2]:
            return "NEW_EDITION", 0.95
        if b[4] > a[4]:
            return "CORRIGENDUM", 0.8
        if b[3] > a[3]:
            return "AMENDMENT", 0.9
        return "UNKNOWN", 0.3

    # eCFR 这类以日期为版本的：内容更新即视为修订
    if "@" in old_ed and "@" in new_ed:
        return "AMENDMENT", 0.6

    return "AMENDMENT", 0.5


def event_id(date: str, standard_id: str) -> str:
    return f"{date}-{standard_id}"


def make_event(*, date: str, family: dict, old_ed: str, new_ed: str,
               changes: list[dict], impact: dict, doc: dict | None = None,
               source_url: str | None = None) -> dict:
    kind, conf = classify(old_ed, new_ed)
    doc = doc or {}
    return {
        "id": event_id(date, family["id"]),
        "standard_id": family["id"],
        "date": date,
        "no": family.get("no"),
        "title": family.get("title_cn"),
        "site": family.get("site"),
        "category": family.get("category"),
        "type": kind,
        "type_confidence": conf,
        "from_edition": old_ed,
        "to_edition": new_ed,
        "timeline": {
            "published": doc.get("published"),
            "comment_until": None,
            "approved": None,
            "in_force": None,
            "transition_until": None,
            "mandatory_from": None,
            "repealed": None,
            "recall_window": None,
        },
        "diffs": changes[:200],
        "diff_total": len(changes),
        "impact": impact,
        "to_version": doc.get("version"),
        "doc_label": doc.get("label"),
        "doc_form": doc.get("form") or "official",
        "links": [source_url] if source_url else [],
        "analyzed": impact.get("analyzed", True),
        "progress_of": None,
    }


def _path(date: str) -> Path:
    return CHANGES / f"{date}.json"


def load_day(date: str) -> list[dict]:
    p = _path(date)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8-sig")).get("events", [])


def upsert(event: dict) -> bool:
    """写入当天文件。同一族同一目标版本已存在则返回 False（不重复写）。"""
    CHANGES.mkdir(parents=True, exist_ok=True)
    events = load_day(event["date"])
    key = (event["standard_id"], event["to_edition"])
    for e in events:
        if (e["standard_id"], e["to_edition"]) == key:
            return False
    events.append(event)
    _path(event["date"]).write_text(
        json.dumps({"date": event["date"], "events": events}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def load_all() -> list[dict]:
    if not CHANGES.exists():
        return []
    out: list[dict] = []
    for p in sorted(CHANGES.glob("*.json"), reverse=True):
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        out.extend(data.get("events", []))
    return out


def link_progress(events: list[dict]) -> list[dict]:
    """同一族后续事件挂到前一条上（amend → 其 corrigendum）。"""
    by_std: dict[str, list[dict]] = {}
    for e in sorted(events, key=lambda x: (x["date"], x["to_edition"])):
        by_std.setdefault(e["standard_id"], []).append(e)
    for items in by_std.values():
        for prev, cur in zip(items, items[1:]):
            cur["progress_of"] = prev["id"]
    return events

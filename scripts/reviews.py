# -*- coding: utf-8 -*-
"""人工覆盖层：处理意见与改判。

铁律：这里**只读不写**。任何自动化流程（publish / build_site）都不许写这个目录。
人工结论优先级最高，与模型判断冲突时以人工为准。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / "data" / "reviews"

SAFE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


def _base(event_id: str) -> Path:
    return REVIEWS / SAFE.sub("_", event_id).strip("_")[:120]


def load(event_id: str) -> dict | None:
    """读 .json（结构化）与 .md（正文），两者可并存，md 正文优先展示。"""
    base = _base(event_id)
    data: dict = {}
    jp, mp = base.with_suffix(".json"), base.with_suffix(".md")
    if jp.exists():
        try:
            data = json.loads(jp.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            data = {"error": f"review json 解析失败：{e}"}
    if mp.exists():
        data["opinion_md"] = mp.read_text(encoding="utf-8")
    return data or None


def apply(event: dict, review: dict | None) -> dict:
    """把人工结论合进事件的展示视图。不改动事件本身。"""
    view = dict(event)
    view["review"] = review
    if not review:
        return view

    if review.get("override_type"):
        view["type_original"] = view["type"]
        view["type"] = review["override_type"]
        view["type_overridden"] = True

    if review.get("override_relevant") is not None:
        view["impact"] = dict(view["impact"])
        view["impact"]["relevant_original"] = view["impact"].get("relevant")
        view["impact"]["relevant"] = bool(review["override_relevant"])
        view["impact"]["relevant_overridden"] = True

    view["verdict"] = review.get("verdict")
    view["opinion"] = review.get("opinion_md") or review.get("opinion") or ""
    return view


def wants_attention(event: dict) -> bool:
    """需要人看：未归因、疑似相关、低置信、或人类判 rejected/deferred。"""
    impact = event.get("impact") or {}
    if event.get("review") and event.get("review", {}).get("verdict") in ("rejected", "deferred"):
        return True
    return bool(
        impact.get("analyzed") is False
        or impact.get("needs_review")
        or (impact.get("relevant") is False and not impact.get("second_pass", {}).get("agrees"))
        or (impact.get("confidence") or 0) < 0.5 and impact.get("relevant") is not False
    )

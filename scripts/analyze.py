# -*- coding: utf-8 -*-
"""归因层：把差异变成「对座椅意味着什么」。

设计要点（对应规格 §8）：
  · 提示词外置在 prompts/，这里只负责拼装与校验
  · criteria 每项必须带条款号，给不出就丢弃
  · 判「无关」时做一次独立复核，两次不一致标为疑似相关
  · 任何失败都降级为未归因，绝不吞掉事件
"""
import json
from pathlib import Path

from scripts import llm

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"

MAX_DIFF_CHARS = 9000
SUBSTANCE_KEYWORDS = ("限用物质", "禁用物质", "SVHC", "ELV", "REACH", "回收")
REQUIRED = ("relevant", "part", "criteria", "design", "test", "summary", "action", "confidence")


class InvalidOutput(RuntimeError):
    """模型输出不合规。调用方必须降级，不得把它当成「无影响」。"""


def load_prompt(name: str) -> str:
    p = PROMPTS / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"缺少提示词：{p}")
    return p.read_text(encoding="utf-8")


def is_substance(family: dict) -> bool:
    blob = f"{family.get('no', '')} {family.get('title_cn', '')} {family.get('org', '')}"
    return any(k.lower() in blob.lower() for k in SUBSTANCE_KEYWORDS)


def format_changes(changes: list[dict], limit: int = 60) -> str:
    lines, used = [], 0
    for c in changes[:limit]:
        mark = {"added": "新增", "removed": "删除", "modified": "修改"}[c["kind"]]
        body = f"- [{c['clause']}] {mark}：{(c['new'] or c['old'] or '')[:600]}"
        if used + len(body) > MAX_DIFF_CHARS:
            lines.append(f"- …（另有 {len(changes) - len(lines)} 处未列入）")
            break
        lines.append(body)
        used += len(body)
    return "\n".join(lines)


def build_user(family: dict, old_ed: str, new_ed: str, changes: list[dict]) -> str:
    return (
        f"标准：{family.get('no')} {family.get('title_cn')}\n"
        f"发布机构：{family.get('org')}\n"
        f"版本：{old_ed} → {new_ed}\n"
        f"条款变动共 {len(changes)} 处：\n\n"
        f"{format_changes(changes)}\n\n"
        f"请判断这些改动对 M1 座椅的影响。"
    )


def _as_bool(value) -> bool:
    return bool(value) if isinstance(value, bool) else False


def validate(raw: dict) -> dict:
    """清洗并校验。不合规直接抛，绝不返回半成品。"""
    if not isinstance(raw, dict):
        raise InvalidOutput("输出不是 JSON 对象")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise InvalidOutput(f"缺少字段：{', '.join(missing)}")

    criteria, dropped = [], 0
    for item in raw.get("criteria") or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        clause = str(item.get("clause") or "").strip()
        name = str(item.get("item") or "").strip()
        if not clause or not name:
            dropped += 1          # 没有条款号 = 无法回溯，丢弃
            continue
        criteria.append({"item": name, "clause": clause})

    summary = str(raw.get("summary") or "").strip()
    action = str(raw.get("action") or "").strip()
    if not summary:
        raise InvalidOutput("summary 为空")

    try:
        conf = float(raw.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0
    if conf > 1.0:
        conf = 1.0
    if conf < 0:
        conf = 0.0
    # criteria 全被丢弃，说明模型给不出可回溯的依据，置信度必须压低
    if dropped and not criteria:
        conf = min(conf, 0.4)

    return {
        "relevant": _as_bool(raw.get("relevant")),
        "part": str(raw.get("part") or "其他").strip()[:40],
        "criteria": criteria,
        "design": _as_bool(raw.get("design")),
        "test": _as_bool(raw.get("test")),
        "summary": summary[:800],
        "action": action[:800],
        "confidence": round(conf, 2),
        "dropped_criteria": dropped,
        "second_pass": {"done": False, "agrees": None},
    }


def analyze(family: dict, old_ed: str, new_ed: str, changes: list[dict],
            *, client=llm.chat_json) -> dict:
    """返回 impact 字典。失败时抛 llm.BudgetExceeded / llm.LLMUnavailable / InvalidOutput。"""
    prompt = "impact-substance" if is_substance(family) else "impact-seat"
    system = load_prompt(prompt) + "\n\n" + load_prompt("confidence-rubric")
    user = build_user(family, old_ed, new_ed, changes)

    raw, _ = client(system, user)
    impact = validate(raw)

    if impact["relevant"] is False:
        impact = _second_pass(impact, family, user, client)

    return impact


def _second_pass(impact: dict, family: dict, user: str, client) -> dict:
    """判「无关」时独立复核一次。这里不信任第一次的结论，所以用单独的提示词。"""
    system = load_prompt("second-pass")
    try:
        raw, _ = client(system, user, temperature=0.7)
        again = validate(raw)
    except Exception:  # noqa: BLE001
        impact["second_pass"] = {"done": False, "agrees": None, "note": "复核失败，按未确认处理"}
        impact["confidence"] = min(impact["confidence"], 0.5)
        return impact

    agrees = (again["relevant"] is False)
    impact["second_pass"] = {"done": True, "agrees": agrees}
    if not agrees:
        # 两次不一致：宁可当成相关，让你看一眼
        impact["relevant"] = True
        impact["needs_review"] = True
        impact["summary"] = f"疑似与原判断不符：{again['summary'][:200]}"
        impact["confidence"] = min(impact["confidence"], 0.45)
    return impact


def degraded(reason: str) -> dict:
    """降级形态：事件照发，但明确说「没归因」。"""
    return {
        "relevant": None,
        "part": "未判定",
        "criteria": [],
        "design": None,
        "test": None,
        "summary": "未归因，请人工判读。",
        "action": "",
        "confidence": 0.0,
        "analyzed": False,
        "error": reason[:300],
        "second_pass": {"done": False, "agrees": None},
    }


def impact_to_json(impact: dict) -> str:
    return json.dumps(impact, ensure_ascii=False, indent=2)

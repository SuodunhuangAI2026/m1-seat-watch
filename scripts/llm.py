# -*- coding: utf-8 -*-
"""DeepSeek 客户端 + 月度预算熔断。

只做两件事：把一段对话发出去、把 JSON 拿回来；以及记账。
判断逻辑一律不放在这里。
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from scripts.state import DATA

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
BUDGET = DATA / "budget.json"

DEFAULT_BUDGET = {"max_tokens_per_month": 2_000_000, "used": {}}


class LLMUnavailable(RuntimeError):
    """没有 Key，或者调用失败。调用方应当降级为「未归因」。"""


class BudgetExceeded(RuntimeError):
    """本月额度用尽。同样降级为「未归因」，但要单独标出来。"""


def _month() -> str:
    return datetime.now().strftime("%Y-%m")


def load_budget() -> dict:
    if not BUDGET.exists():
        return json.loads(json.dumps(DEFAULT_BUDGET))
    try:
        data = json.loads(BUDGET.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return json.loads(json.dumps(DEFAULT_BUDGET))
    merged = {**DEFAULT_BUDGET, **data}
    merged["used"] = dict(merged.get("used") or {})
    return merged


def used_this_month() -> int:
    return int(load_budget()["used"].get(_month(), 0))


def charge(tokens: int) -> None:
    budget = load_budget()
    budget["used"][_month()] = used_this_month() + max(0, tokens)
    BUDGET.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def budget_left() -> int:
    b = load_budget()
    return int(b["max_tokens_per_month"]) - used_this_month()


def ensure_budget() -> None:
    if budget_left() <= 0:
        raise BudgetExceeded(
            f"本月额度已用尽（上限 {load_budget()['max_tokens_per_month']} tokens）"
        )


def chat_json(system: str, user: str, *, temperature: float = 0.2, timeout: int = 90) -> tuple[dict, int]:
    """返回 (解析后的 JSON, 消耗 token)。任何失败都抛异常，不返回 None。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise LLMUnavailable("没有 DEEPSEEK_API_KEY")

    ensure_budget()

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": 1200,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise LLMUnavailable(f"DeepSeek HTTP {e.code}: {e.read()[:200]!r}") from e
    except Exception as e:  # noqa: BLE001
        raise LLMUnavailable(f"DeepSeek 调用失败: {e}") from e

    try:
        body = json.loads(raw.decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        tokens = int(body.get("usage", {}).get("total_tokens", 0))
    except Exception as e:  # noqa: BLE001
        raise LLMUnavailable(f"DeepSeek 响应结构异常: {e}") from e

    charge(tokens)

    try:
        return json.loads(content), tokens
    except json.JSONDecodeError as e:
        raise LLMUnavailable(f"模型没有返回合法 JSON: {content[:200]!r}") from e

# -*- coding: utf-8 -*-
"""把一次「版本变化」变成一条事件：归因 → 组装 → 落盘 → 更新族元数据。

降级是默认行为，不是意外：模型不可用、超预算、输出不合规，事件照样写，
只是标 `analyzed: false`，并且报告里明说「未归因，请人工判读」。
"""
from datetime import datetime

from scripts import analyze, events, llm, state


def process(*, family: dict, old_ed: str, new_ed: str, changes: list[dict],
            doc: dict | None = None, source_url: str | None = None,
            date: str | None = None, client=llm.chat_json) -> dict:
    date = date or datetime.now().strftime("%Y-%m-%d")

    try:
        impact = analyze.analyze(family, old_ed, new_ed, changes, client=client)
        impact["analyzed"] = True
    except llm.BudgetExceeded as e:
        impact = analyze.degraded(f"额度用尽：{e}")
    except llm.LLMUnavailable as e:
        impact = analyze.degraded(f"模型不可用：{e}")
    except analyze.InvalidOutput as e:
        impact = analyze.degraded(f"输出不合规：{e}")
    except Exception as e:  # noqa: BLE001
        impact = analyze.degraded(f"归因异常：{type(e).__name__}: {e}")

    event = events.make_event(
        date=date, family=family, old_ed=old_ed, new_ed=new_ed,
        changes=changes, impact=impact, doc=doc, source_url=source_url,
    )
    created = events.upsert(event)
    state.record_edition(family["id"], new_ed, doc or {})
    return {**event, "created": created}


def pending_review(event: dict) -> bool:
    impact = event.get("impact") or {}
    return bool(
        impact.get("analyzed") is False
        or impact.get("needs_review")
        or (impact.get("confidence") or 0) < 0.5
    )

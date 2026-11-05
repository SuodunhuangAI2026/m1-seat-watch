# -*- coding: utf-8 -*-
"""条款级差异。先按条款号对齐，再比条款内文本。

不是字符级 diff——字符级在 PDF 抽文本的场景下会产生海量噪声
（换行、连字符、页码），看的人会直接放弃。
"""
import re
from collections import OrderedDict

CLAUSE_HEAD = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3}){0,4})\.?\s+(?=\S)")
WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return WS.sub(" ", text).strip()


def to_clauses(text: str) -> "OrderedDict[str, str]":
    """把正文切成 条款号 → 条款文本。没有条款号的前导内容归到 '(前言)'。"""
    clauses: "OrderedDict[str, list[str]]" = OrderedDict()
    current = "(前言)"
    for line in text.split("\n"):
        m = CLAUSE_HEAD.match(line)
        if m:
            current = m.group(1)
        clauses.setdefault(current, []).append(line)
    return OrderedDict((k, norm(" ".join(v))) for k, v in clauses.items())


def diff(old_text: str, new_text: str) -> list[dict]:
    old, new = to_clauses(old_text), to_clauses(new_text)
    out: list[dict] = []

    for clause, body in new.items():
        if clause not in old:
            out.append({"clause": clause, "kind": "added", "old": None, "new": body})
        elif norm(old[clause]) != body:
            out.append({"clause": clause, "kind": "modified", "old": old[clause], "new": body})

    for clause, body in old.items():
        if clause not in new:
            out.append({"clause": clause, "kind": "removed", "old": body, "new": None})

    out.sort(key=_sort_key)
    return out


def _sort_key(item: dict) -> tuple:
    parts = re.findall(r"\d+", item["clause"])
    return tuple(int(p) for p in parts) + ({"added": 0, "removed": 1, "modified": 2}[item["kind"]],)


def summarize(changes: list[dict]) -> dict:
    counts = {"added": 0, "removed": 0, "modified": 0}
    for c in changes:
        counts[c["kind"]] += 1
    return {"total": len(changes), "counts": counts}

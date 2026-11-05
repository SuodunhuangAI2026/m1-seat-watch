#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成静态站。全部页面都在这里产出，不依赖任何前端框架。"""
import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import events as ev
from scripts import render, reviews

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs"

TYPE_CN = {
    "NEW_EDITION": "升版", "CORRIGENDUM": "勘误", "AMENDMENT": "修订",
    "SUPPLEMENT": "增补", "CONSOLIDATED": "并入新版", "SUPERSEDED": "被替代",
    "REPEALED": "被废止", "TRANSLATION_ONLY": "仅译版更新",
    "STATUS_CHANGE": "状态变化", "UNKNOWN": "待确认",
}


def esc(v) -> str:
    return escape(str(v if v is not None else ""), quote=True)


def load() -> tuple[list[dict], list[dict]]:
    sites = json.loads((DATA / "sites.json").read_text(encoding="utf-8-sig"))["sites"]
    fams = json.loads((DATA / "standards.json").read_text(encoding="utf-8-sig"))["families"]
    return sites, fams


def view_of(event: dict) -> dict:
    return reviews.apply(event, reviews.load(event["id"]))


# ---------------- 片段 ----------------

def timeline_table(event: dict) -> str:
    t = event.get("timeline") or {}
    rows = [
        ("发布日", t.get("published")),
        ("征求意见期", t.get("comment_until")),
        ("批准日", t.get("approved")),
        ("生效日", t.get("in_force")),
        ("过渡期", t.get("transition_until")),
        ("强制实施日", t.get("mandatory_from")),
        ("废止日", t.get("repealed")),
        ("召回 / 整改窗口", t.get("recall_window")),
    ]
    body = "".join(
        f"<tr><th style='width:150px'>{k}</th><td>{esc(v) if v else '—'}</td></tr>" for k, v in rows
    )
    return f"<table>{body}</table>"


def diff_table(event: dict) -> str:
    diffs = (event.get("diffs") or [])[:60]
    if not diffs:
        return '<p class="empty">没有可展示的条款差异（可能只有元数据变化）</p>'
    rows = []
    for d in diffs:
        cls = {"added": "add", "removed": "del", "modified": "mod"}.get(d["kind"], "")
        old = esc((d.get("old") or "")[:900]) or "—"
        new = esc((d.get("new") or "")[:900]) or "—"
        mark = {"added": "新增", "removed": "删除", "modified": "修改"}.get(d["kind"], d["kind"])
        rows.append(
            f"<tr><td class='no'>{esc(d['clause'])}</td><td><span class='{cls}'>{mark}</span></td>"
            f"<td>{old}</td><td>{new}</td></tr>"
        )
    total = event.get("diff_total") or len(event.get("diffs") or [])
    more = ""
    if total > len(diffs):
        more = f'<p class="meta">另有 {total - len(diffs)} 处未列出。</p>'
    return ("<table><tr><th style='width:90px'>条款</th><th style='width:70px'>变化</th>"
            "<th>旧要求</th><th>新要求</th></tr>" + "".join(rows) + "</table>" + more)


def links_block(event: dict) -> str:
    links = [u for u in (event.get("links") or []) if u]
    if not links:
        return '<p class="meta">原文链接缺失</p>'
    items = "".join(f'<li><a href="{esc(u)}">{esc(u)}</a></li>' for u in links)
    return f"<ul>{items}</ul>"


def relevance_badge(impact: dict) -> str:
    if impact.get("analyzed") is False:
        return '<span class="tag bad">未归因</span>'
    if impact.get("needs_review"):
        return '<span class="tag warn">疑似相关·待确认</span>'
    rel = impact.get("relevant")
    if rel is True:
        return '<span class="tag ok">相关</span>'
    if rel is False:
        return '<span class="tag rel">无关</span>'
    return '<span class="tag warn">未判定</span>'


def report_page(view: dict) -> str:
    impact = view.get("impact") or {}
    criteria = impact.get("criteria") or []
    crit_html = ("<ul>" + "".join(
        f"<li>{esc(c['item'])} <span class='meta'>（条款 {esc(c['clause'])}）</span></li>"
        for c in criteria) + "</ul>") if criteria else '<span class="meta">无</span>'

    opinion = view.get("opinion") or ""
    if opinion:
        op_html = f'<div class="op">{esc(opinion)}</div>'
        if view.get("verdict"):
            op_html += f'<p class="meta">人工结论：{esc(view["verdict"])}</p>'
    else:
        op_html = ('<p class="empty" style="text-align:left">待填写 —— 在 '
                   f'<code>data/reviews/{esc(view["id"])}.json</code> 里写入 '
                   '<code>opinion</code> 字段，重建后自动出现在这里。</p>')

    notes = ""
    if view.get("type_overridden"):
        notes += f' <span class="tag warn">人工改判（原为 {esc(view.get("type_original"))}）</span>'
    if impact.get("relevant_overridden"):
        notes += ' <span class="tag warn">相关性已人工改判</span>'

    rel_text = {True: "相关（属于 M1 座椅范围）", False: "无关", None: "未判定"}.get(
        impact.get("relevant"), "未判定")
    if impact.get("analyzed") is False:
        rel_text = f"未归因（{esc(impact.get('error', ''))}）"
    elif impact.get("needs_review"):
        rel_text = "疑似相关（两次判定不一致，请人工确认）"

    body = render.fill(
        render.template("report.html"),
        no=esc(view.get("no")),
        title=esc(view.get("title")),
        site=esc(view.get("site")),
        category="核心" if view.get("category") == "core" else "关联",
        doc_form=esc(view.get("doc_form")),
        from_edition=esc(view.get("from_edition")),
        to_edition=esc(view.get("to_edition")),
        type=TYPE_CN.get(view.get("type"), view.get("type")),
        type_note=notes,
        summary=esc(impact.get("summary") or "—"),
        timeline_table=timeline_table(view),
        diff_table=diff_table(view),
        relevance=f"{relevance_badge(impact)} {rel_text}",
        part=esc(impact.get("part") or "—"),
        criteria=crit_html,
        design={True: "是", False: "否", None: "未判定"}[impact.get("design")],
        test={True: "是", False: "否", None: "未判定"}[impact.get("test")],
        confidence=f"{impact.get('confidence', 0) or 0:.2f}",
        action=esc(impact.get("action") or "—"),
        links=links_block(view),
        opinion=op_html,
    )
    return render.page(
        f"{view.get('no')} {view.get('from_edition')}→{view.get('to_edition')}", body, root="../"
    )


# ---------------- 页面 ----------------

def build_scope(sites: list[dict], fams: list[dict]) -> str:
    by_site: dict[str, list] = {}
    for f in fams:
        by_site.setdefault(f["site"], []).append(f)

    blocks = []
    for s in sorted(sites, key=lambda x: -len(by_site.get(x["id"], []))):
        items = by_site.get(s["id"], [])
        if not items:
            continue
        trs = []
        for f in sorted(items, key=lambda x: (x["category"] != "core", x["id"])):
            tag = '<span class="tag">核心</span>' if f["category"] == "core" else '<span class="tag rel">关联</span>'
            editions = "、".join(f["library_editions"]) if f["library_editions"] else "—"
            trs.append(
                f'<tr><td class="no"><a href="../standards/{esc(f["id"])}.html">{esc(f["no"])}</a></td>'
                f'<td>{esc(f["title_cn"])}{tag}</td><td>{esc(editions)}</td></tr>'
            )
        blocks.append(
            f'<h2><span class="site">{esc(s["name"])}</span>'
            f'<span class="tier">{esc(s["tier"])} · {len(items)} 族</span></h2>'
            '<table><thead><tr><th>标准号</th><th>名称</th><th>库内版本</th></tr></thead>'
            f"<tbody>{''.join(trs)}</tbody></table>"
        )
    return ('<p class="sub">按站点分组。适配器按站点实现（19 个），标准族是站点上的条目。</p>'
            + "".join(blocks))


def event_row(view: dict, prefix: str = "../") -> str:
    impact = view.get("impact") or {}
    return (
        f'<div class="card"><h3><a href="{prefix}reports/{esc(view["id"])}.html">'
        f'{esc(view.get("no"))}　{esc(view.get("from_edition"))} → {esc(view.get("to_edition"))}</a></h3>'
        f'<div class="meta">{esc(view["date"])} · {TYPE_CN.get(view.get("type"), view.get("type"))} · '
        f'{esc(view.get("site"))}　{relevance_badge(impact)}</div>'
        f'<p>{esc((impact.get("summary") or "")[:180])}</p></div>'
    )


def build_changes(views: list[dict], prefix: str = "../") -> str:
    if not views:
        return '<p class="empty">还没有任何变更记录。第一次探测到版本变化后，这里会出现。</p>'
    return "".join(event_row(v, prefix) for v in views)


def build_standard(fam: dict, views: list[dict]) -> str:
    rows = "".join(
        f'<tr><td class="no"><a href="../reports/{esc(v["id"])}.html">{esc(v["date"])}</a></td>'
        f'<td>{esc(v.get("from_edition"))} → {esc(v.get("to_edition"))}</td>'
        f'<td>{TYPE_CN.get(v.get("type"), v.get("type"))}</td>'
        f'<td>{esc((v.get("impact") or {}).get("summary") or "")[:120]}</td></tr>'
        for v in views
    ) or '<tr><td colspan="4" class="meta">暂无变更记录</td></tr>'
    eds = "、".join(fam.get("library_editions") or []) or "—"
    return (
        f'<h2>{esc(fam["no"])} {esc(fam["title_cn"])}</h2>'
        f'<p class="meta">{esc(fam.get("org"))} · 站点 {esc(fam["site"])} · '
        f'{"核心" if fam["category"] == "core" else "关联"}</p>'
        f'<table><tr><th style="width:150px">库内版本</th><td>{esc(eds)}</td></tr>'
        f'<tr><th>当前版本</th><td>{esc(fam.get("current_edition") or "—")}</td></tr></table>'
        '<h2>变更历史</h2>'
        '<table><tr><th style="width:110px">日期</th><th>版本</th><th>类型</th><th>摘要</th></tr>'
        f"{rows}</table>"
    )


def main() -> None:
    sites, fams = load()
    raw_events = ev.link_progress(ev.load_all())
    views = [view_of(e) for e in raw_events]
    views.sort(key=lambda v: (v["date"], v["id"]), reverse=True)

    for sub in ("changes", "standards", "reports"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    pending = sum(1 for v in views if reviews.wants_attention(v) and not v.get("review"))
    kpi = (
        f'<div class="kpi"><div><b>{len(fams)}</b>标准族</div>'
        f'<div><b>{len(sites)}</b>站点</div>'
        f'<div><b>{len(views)}</b>累计变更</div>'
        f'<div><b>{pending}</b>待处理</div></div>'
    )

    (OUT / "index.html").write_text(render.page(
        "M1 座椅标准变更监控",
        '<h2>最近变更</h2>' + build_changes(views[:8], prefix=""),
        kpi,
    ), encoding="utf-8")

    (OUT / "scope.html").write_text(render.page(
        "监控范围 · M1 座椅标准", build_scope(sites, fams), kpi
    ), encoding="utf-8")

    (OUT / "changes" / "index.html").write_text(render.page(
        "变更流 · M1 座椅标准", build_changes(views), kpi, root="../"
    ), encoding="utf-8")

    by_date: dict[str, list] = {}
    for v in views:
        by_date.setdefault(v["date"], []).append(v)
    for date, items in by_date.items():
        (OUT / "changes" / f"{date}.html").write_text(render.page(
            f"{date} 变更 · M1 座椅标准", build_changes(items), root="../"
        ), encoding="utf-8")

    by_std: dict[str, list] = {}
    for v in views:
        by_std.setdefault(v["standard_id"], []).append(v)
    for fam in fams:
        (OUT / "standards" / f"{fam['id']}.html").write_text(render.page(
            f"{fam['no']} · M1 座椅标准",
            build_standard(fam, by_std.get(fam["id"], [])), root="../"
        ), encoding="utf-8")

    for v in views:
        (OUT / "reports" / f"{v['id']}.html").write_text(report_page(v), encoding="utf-8")

    idx = [{
        "id": v["id"], "no": v.get("no"), "title": v.get("title"),
        "from": v.get("from_edition"), "to": v.get("to_edition"),
        "summary": (v.get("impact") or {}).get("summary"),
        "date": v["date"], "type": v.get("type"),
    } for v in views]
    (OUT / "search-index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"写出站点：{len(fams)} 族 / {len(views)} 条变更 / "
          f"{len(by_date)} 个日期页 / {len(views)} 份报告")


if __name__ == "__main__":
    main()

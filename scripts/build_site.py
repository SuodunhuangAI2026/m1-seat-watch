#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成静态站。P0 阶段只产出首页与标准范围页。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs"

CSS = """
:root{--ink:#1f2937;--sub:#6b7280;--line:#e5e7eb;--bg:#fff;--blu:#083e82;--blu2:#e8eef6;--red:#d03923;--amber:#b45309}
*{box-sizing:border-box}
body{margin:0;font:16px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--bg)}
header{border-bottom:1px solid var(--line);padding:28px 20px 20px}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:.5px}
h1 .bar{display:inline-block;width:4px;height:22px;background:var(--blu);vertical-align:-3px;margin-right:10px}
.sub{color:var(--sub);font-size:14px}
h2{font-size:18px;margin:34px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h2 .site{color:var(--blu)}
h2 .tier{font-size:12px;font-weight:400;color:var(--sub);border:1px solid var(--line);border-radius:10px;padding:1px 8px;margin-left:8px;vertical-align:2px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-weight:600;color:var(--sub);border-bottom:1px solid var(--line);padding:6px 8px;font-size:13px}
td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}
td.no{white-space:nowrap;color:var(--blu);font-weight:600;width:150px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;background:var(--blu2);color:var(--blu);margin-left:6px;vertical-align:2px}
.tag.rel{background:#f3f4f6;color:var(--sub)}
.tag.sub{background:#fef3c7;color:var(--amber)}
footer{color:var(--sub);font-size:13px;padding:40px 0 60px;border-top:1px solid var(--line);margin-top:50px}
.kpi{display:flex;gap:28px;margin:18px 0 0;flex-wrap:wrap}
.kpi div{font-size:13px;color:var(--sub)}
.kpi b{display:block;font-size:26px;color:var(--ink);line-height:1.2}
nav a{color:var(--blu);text-decoration:none;margin-right:16px;font-size:14px}
"""


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{CSS}</style></head>
<body>
<header><div class="wrap">
  <h1><span class="bar"></span>M1 座椅标准变更监控</h1>
  <div class="sub">UNECE · FMVSS · GB · ADR · GSO · NCAP 体系 · 限用物质</div>
  <div class="kpi">{body_kpi}</div>
</div></header>
<main class="wrap">{body}</main>
<footer><div class="wrap">
  M1 座椅标准变更监控 · 数据由 <code>data/</code> 生成 ·
  <a href="https://github.com/">仓库</a>
</div></footer>
</body></html>"""


body_kpi = ""


def load():
    sites = json.loads((DATA / "sites.json").read_text(encoding="utf-8-sig"))["sites"]
    fams = json.loads((DATA / "standards.json").read_text(encoding="utf-8-sig"))["families"]
    return sites, fams


def build_scope(sites, fams) -> str:
    by_site: dict[str, list] = {}
    for f in fams:
        by_site.setdefault(f["site"], []).append(f)

    order = {s["id"]: i for i, s in enumerate(sites)}
    rows = []
    for s in sorted(sites, key=lambda x: -len(by_site.get(x["id"], []))):
        items = by_site.get(s["id"], [])
        if not items:
            continue
        trs = []
        for f in sorted(items, key=lambda x: (x["category"] != "core", x["id"])):
            cat = '<span class="tag">核心</span>' if f["category"] == "core" else '<span class="tag rel">关联</span>'
            editions = "、".join(f["library_editions"]) if f["library_editions"] else "—"
            trs.append(
                f'<tr><td class="no">{f["no"]}</td><td>{f["title_cn"]}{cat}</td>'
                f'<td>{editions}</td></tr>'
            )
        rows.append(
            f'<h2><span class="site">{s["name"]}</span>'
            f'<span class="tier">{s["tier"]} · {len(items)} 族</span></h2>'
            f"<table><thead><tr><th>标准号</th><th>名称</th><th>库内版本</th></tr></thead>"
            f"<tbody>{''.join(trs)}</tbody></table>"
        )
    return (
        '<h2 style="margin-top:26px">监控范围</h2>'
        '<p class="sub">按站点分组。适配器按站点实现（19 个），标准族是站点上的条目。</p>'
        + "".join(rows)
    )


def main() -> None:
    global body_kpi
    sites, fams = load()
    OUT.mkdir(exist_ok=True)
    body_kpi = (
        f'<div><b>{len(fams)}</b>标准族</div>'
        f'<div><b>{len(sites)}</b>站点</div>'
        f'<div><b>{sum(1 for f in fams if f["category"] == "core")}</b>核心族</div>'
        f'<div><b>0</b>待处理变更</div>'
    )
    (OUT / "scope.html").write_text(page("监控范围 · M1 座椅标准", build_scope(sites, fams)), encoding="utf-8")
    (OUT / "index.html").write_text(
        page("M1 座椅标准变更监控", '<h2>监控范围</h2><p>见 <a href="scope.html">标准范围</a>。</p>'),
        encoding="utf-8",
    )
    print(f"写出 docs/scope.html、docs/index.html（{len(fams)} 族 / {len(sites)} 站）")


if __name__ == "__main__":
    main()

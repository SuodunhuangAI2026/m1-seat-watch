#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 registry.source.csv（清单原始条目）编译成 data/standards.json（标准族）。

规则：
  1. 丢掉非标准原文的条目（如「更新内容介绍」这类解读文档）
  2. 同族不同版本合并（GB 14166-2013 与 GB 14166-2024 是同一族的两版）
  3. 站点中文标签映射到 sites.json 的 id
  4. 无编号条目用可读 id，避免一长串文件名当主键
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "registry.source.csv"
OUT = ROOT / "data" / "standards.json"

# 站点标签 -> sites.json 的 id
SITE_MAP = {
    "openstd": "openstd",
    "UNECE": "unece",
    "eCFR": "ecfr",
    "c-ncap.org.cn": "cncap",
    "Transport Canada": "tc",
    "ciasi.org.cn": "ciasi",
    "iihs.org": "iihs",
    "legislation.gov.au": "adr",
    "aseancap.org": "asean",
    "latinncap.com": "latin",
    "nasva.go.jp": "jncap",
    "ancap.com.au": "ancap",
    "euroncap.com": "euro",
    "GSO": "gso",
    "工信部/标准网": "qct",
    "EUR-Lex": "eurlex",
    "ECHA": "echa",
    "kncap.org": "kncap",
    "团体标准平台": "ttbz",
}

# 无编号条目的可读 id（按名称子串匹配）
NAME_ID = [
    ("ASEAN-NCAP-Assessment-Protocol-Adult", "ASEAN-AOP-3.0"),
    ("ASEAN-NCAP-Overall-Assessment-Protocol-Version-3.0", "ASEAN-Overall-3.0"),
    ("ASEAN-NCAP-Overall-Assessment-Protocol-Version-3.1", "ASEAN-Overall-3.1"),
    ("C-NCAP管理规则", "CNCAP-2027"),
    ("Crash Protection - Rear Impact", "ANCAP-Rear-Impact"),
    ("Overall Assessment", "ANCAP-Overall"),
    ("Euro NCAP - Whiplash Dynamic", "EuroNCAP-Whiplash-Dynamic"),
    ("rear-whiplash-test-protocol", "EuroNCAP-Rear-Whiplash-v1.1"),
    ("LATCH evaluation", "IIHS-LATCH-Rating"),
    ("LATCH protocol", "IIHS-LATCH-Protocol"),
    ("Whiplash prevention evaluation", "IIHS-Whiplash-Protocol"),
    ("Whiplash prevention rating", "IIHS-Whiplash-Rating"),
    ("Latin NCAP 2025 - AOP", "LatinNCAP-AOP"),
    ("Latin NCAP Overall Rating", "LatinNCAP-Overall"),
    ("Latin NCAP Testing Protocol", "LatinNCAP-Test-2026"),
    ("VEHICLE SAFETY PERFORMANCE EVALUATION", "JNCAP-2023-Procedures"),
]

# 手工维护的定位规则（data/locators.json），会并进每个族的 locator 字段
LOCATORS = ROOT / "data" / "locators.json"

# 明确不是标准原文的条目
NOT_A_STANDARD = ("更新内容介绍",)


def family_key(no: str) -> str:
    """GB 系列去掉年号，其余原样。"""
    m = re.match(r"^(GB(?:/T)?\s*[\d.]+)", no)
    return m.group(1).strip() if m else no


def slug(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", text).strip("-")
    return s or "item"


def make_id(no: str, name: str) -> str:
    if no.startswith("（无编号）"):
        for kw, ident in NAME_ID:
            if kw in name or kw in no:
                return ident
        return slug(no.replace("（无编号）", ""))[:48]
    return slug(family_key(no))


def main() -> None:
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    kept = [r for r in rows if r["keep"] == "保留"]

    dropped = [r for r in kept if any(k in r["name"] for k in NOT_A_STANDARD)]
    kept = [r for r in kept if r not in dropped]

    families: dict[str, dict] = {}
    for r in kept:
        fk = family_key(r["no"])
        fid = make_id(r["no"], r["name"])
        fam = families.setdefault(fid, {
            "id": fid,
            "no": fk,
            "title_cn": r["name"],
            "site": SITE_MAP.get(r["site"], "unknown"),
            "tier": r["tier"],
            "category": r["cat"],
            "org": r["org"],
            "library_editions": [],
            "current_edition": None,
            "entries": [],
        })
        if r["ver"] and r["ver"] != "—":
            fam["library_editions"].append(r["ver"])
        fam["entries"].append({"no": r["no"], "name": r["name"], "ver": r["ver"]})

    locators = {}
    if LOCATORS.exists():
        locators = json.loads(LOCATORS.read_text(encoding="utf-8-sig"))
    for fam in families.values():
        rule = locators.get(fam["id"])
        if rule:
            fam["locator"] = rule

    out = {
        "_comment": "由 scripts/build_registry.py 从 data/registry.source.csv 生成，勿手改。",
        "count": len(families),
        "families": sorted(families.values(), key=lambda f: (f["site"], f["id"])),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"清单条目 {len(rows)} → 保留 {len(kept) + len(dropped)}"
          f"（丢弃非标准原文 {len(dropped)}）→ 去重后 {len(families)} 个族")
    by_site: dict[str, int] = {}
    for f in families.values():
        by_site[f["site"]] = by_site.get(f["site"], 0) + 1
    for s, n in sorted(by_site.items(), key=lambda x: -x[1]):
        print(f"  {s:<10} {n}")
    for r in dropped:
        print(f"  [丢弃] {r['no']} — {r['name']}")


if __name__ == "__main__":
    main()

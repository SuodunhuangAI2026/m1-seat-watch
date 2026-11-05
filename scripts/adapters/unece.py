# -*- coding: utf-8 -*-
"""UNECE WP.29 —— 1958 年协定书附件（R 系列法规）+ GTR。

探测策略：抓「Addenda to the 1958 Agreement」索引页，页面里每个 PDF 链接的
文件名自带版本信息，例如：
    R017r7e.pdf        → R17 Rev.7
    R017r7am2e.pdf     → R17 Rev.7 / Amd.2
    R021r2c1e.pdf      → R21 Rev.2 / Corr.1
所以只要解析链接，不下载正文就能知道有没有新版本。

已知风险：unece.org 挂在 Cloudflare 后面，机房 IP 可能被挑战（403）。
遇到 403 必须报错，不能当成「无变化」。
"""
import re

from scripts import http
from scripts.adapters.base import AdapterError, Document

INDEX_URL = "https://unece.org/un-regulations-addenda-1958-agreement"

# R{编号}r{修订}[am{修正}][c{勘误}][e].pdf
R_PATTERN = re.compile(
    r"(?P<base>R(?P<num>\d{3}))r(?P<rev>\d+)(?:am(?P<amd>\d+))?(?:c(?P<corr>\d+))?(?P<lang>[a-z])?\.pdf$",
    re.I,
)
GTR_PATTERN = re.compile(r"(?P<base>gtr|ECE-TRANS-180a)(?P<rest>[\w\-]*)\.pdf$", re.I)


def edition_of(num: str, rev: str, amd: str | None, corr: str | None) -> str:
    """R017 / 7 / 2 / None → R17.07s2（Series/Supplement 记法）。"""
    e = f"R{int(num)}.{int(rev):02d}"
    if amd:
        e += f"a{int(amd)}"
    if corr:
        e += f"c{int(corr)}"
    return e


def _norm_prefix(value: str | None) -> str | None:
    """R017 / r17 / R17 → R17。"""
    if not value:
        return None
    m = re.search(r"[Rr](\d{1,3})", value)
    return f"R{int(m.group(1))}" if m else None


def parse_index(html: bytes, family: dict) -> list[Document]:
    """从索引页 HTML 里挑出属于该族的 PDF 链接。

    不依赖具体 DOM 结构：直接扫 href，用文件名规则归族，比 CSS 选择器耐改版。
    """
    text = html.decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]+\.pdf)"', text, re.I)

    want = _norm_prefix((family.get("locator") or {}).get("doc_prefix")) or _norm_prefix(
        _prefix_from_no(family.get("no", ""))
    )
    if not want:
        raise AdapterError(f"{family['id']}: 无法确定 UNECE 文档前缀")

    out: dict[str, Document] = {}
    for href in hrefs:
        name = href.rsplit("/", 1)[-1]
        m = R_PATTERN.search(name)
        if not m:
            continue
        if f"R{int(m.group('num'))}" != want:
            continue
        ed = edition_of(m.group("num"), m.group("rev"), m.group("amd"), m.group("corr"))
        url = href if href.startswith("http") else "https://unece.org" + href
        # 同一版本可能同时有多个语言版，英文优先
        if ed in out and m.group("lang") and m.group("lang").lower() != "e":
            continue
        out[ed] = Document(
            standard_id=family["id"],
            edition=ed,
            url=url,
            meta={"rev": m.group("rev"), "amd": m.group("amd"), "corr": m.group("corr")},
        )
    return sorted(out.values(), key=lambda d: _sort_key(d.edition))


def _sort_key(ed: str) -> tuple:
    m = re.match(r"R(\d+)\.(\d+)(?:a(\d+))?(?:c(\d+))?", ed)
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), int(m.group(4) or 0))


def _prefix_from_no(no: str) -> str | None:
    m = re.match(r"UN\s*R\s*(\d+)", no or "", re.I)
    return f"R{int(m.group(1))}" if m else None


class UNECE:
    id = "unece"

    def probe(self, family: dict) -> list[Document]:
        return parse_index(http.get(INDEX_URL, cache=True), family)

    def fetch(self, doc: Document) -> bytes:
        return http.get(doc.url)

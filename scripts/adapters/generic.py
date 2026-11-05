# -*- coding: utf-8 -*-
"""通用适配器：用配置描述站点形状，不为每个站点写一份代码。

两种形状：
  · list     —— 一个索引页上挂着多个文档（NCAP 规程、ADR 目录、ECHA 清单）
  · document —— 一个页面就是全部内容（加拿大 CMVSS 法规合并文本、EUR-Lex 指令）

配置写在 data/sites.json 的对应站点里；每个族用什么规则从列表里认领自己，
写在 data/locators.json 里（build_registry 会并进 standards.json 的 locator）。

「认领」只用链接文字，不用大段上下文——否则相邻的「附录 A」会把「附录 J」抢走。
"""
import re
from urllib.parse import urljoin

from scripts import http
from scripts.adapters.base import AdapterError, Document

MAX_HEAD_PER_FAMILY = 6   # 一个族最多探几个链接，防止页面挂了几百个 PDF 时把运行拖慢

DEFAULT_DATE_PATTERNS = [
    r"(?:current\s+to|last\s+updated|updated\s+on|in\s+force)[^\d]{0,20}(\d{4}-\d{2}-\d{2})",
    r"(\d{4}-\d{2}-\d{2})",
    r"(\d{4})年(\d{1,2})月(\d{1,2})日",
]

LINK = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")


def find_date(text: str, patterns: list[str] | None = None) -> str | None:
    for pat in (patterns or []) + DEFAULT_DATE_PATTERNS:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        if m.lastindex and m.lastindex >= 3:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        return m.group(1)
    return None


def extract_links(html_text: str, pattern: str) -> list[dict]:
    """返回 [{href, label, ctx}]。label 是链接文字，ctx 是前后一小段（兜底用）。"""
    out = []
    for m in LINK.finditer(html_text):
        href = m.group(1)
        if not re.search(pattern, href, re.I):
            continue
        label = re.sub(r"\s+", " ", TAG.sub(" ", m.group(2))).strip()
        ctx = re.sub(r"\s+", " ", TAG.sub(" ", html_text[m.end():m.end() + 80])).strip()
        out.append({"href": href, "label": label, "ctx": ctx})
    return out


def absolute(href: str, base: str) -> str:
    """相对地址 → 绝对地址。用 urljoin 而不是拼字符串，免得 /a/b.pdf 拼成 /x/a/b.pdf。"""
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base, href)


def claim(links: list[dict], rule: str) -> list[dict]:
    """按规则认领链接。先看链接文字，再看 href；两者都不中才看很短的后文。"""
    rx = re.compile(rule, re.I)
    hit = [l for l in links if rx.search(l["label"]) or rx.search(l["href"])]
    if hit:
        return hit
    return [l for l in links if not l["label"] and rx.search(l["ctx"])]


def edition_from(link: dict, href: str, rule: str | None) -> str:
    if rule == "filename":
        return href.rsplit("/", 1)[-1]
    m = re.search(r"(?:V|v|Version\s*)(\d+(?:\.\d+)*)", link["label"]) or re.search(
        r"(\d{4})(?:年版|版)?", link["label"])
    if m:
        return m.group(1)
    return href.rsplit("/", 1)[-1]


def content_html(html_text: str, selector: str | None) -> str:
    """取出正文 HTML；selector 命中就只返回那块，否则返回原文。"""
    if not selector:
        return html_text
    try:
        from lxml import html as lxml_html
        tree = lxml_html.fromstring(html_text)
        nodes = tree.xpath(selector)
        if nodes:
            from lxml import etree
            return "".join(etree.tostring(n, encoding="unicode") for n in nodes)
    except Exception:  # noqa: BLE001
        return html_text
    return html_text


class GenericAdapter:
    """按站点配置工作。cfg 来自 data/sites.json 的那一条。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.id = cfg["id"]

    def _page(self) -> str:
        if self.cfg.get("js_rendered"):
            raise AdapterError(
                f"{self.id}: 该站协议页由 JavaScript 渲染，静态抓取拿不到文档列表。"
                f"需要无头浏览器，或改为人工上传（data/manual/）"
            )
        url = self.cfg.get("entry_url")
        if not url:
            raise AdapterError(f"{self.id}: 站点没有配置 entry_url")
        raw = http.get(url, cache=True)
        return raw.decode(self.cfg.get("charset", "utf-8"), "replace")

    def probe(self, family: dict) -> list[Document]:
        if self.cfg.get("shape", "list") == "document":
            return self._probe_document(family)
        return self._probe_list(family)

    def _probe_document(self, family: dict) -> list[Document]:
        raw = self._page()
        url = self.cfg["entry_url"]
        date = find_date(raw, self.cfg.get("date_patterns"))
        if not date:
            raise AdapterError(f"{self.id}: 页面上找不到任何日期，无法判定版本")
        html = content_html(raw, self.cfg.get("content_selector"))
        # 只有配了正文选择器才检查取到的量；没配就是整页，不做尺寸判断
        if self.cfg.get("content_selector") and len(html) < 500:
            raise AdapterError(f"{self.id}: 正文选择器 {self.cfg.get('content_selector')!r} 取不到内容")
        return [Document(
            standard_id=family["id"],
            edition=f"{self.cfg.get('doc_key') or self.id}@{date}",
            url=url,
            published=date,
            # 一份文档被多个族共用时，正文只存一份
            meta={"format": "html", "shape": "document",
                  "text_key": f"site-{self.id}", "_body": html},
        )]

    def _probe_list(self, family: dict) -> list[Document]:
        html = self._page()
        base = self.cfg["entry_url"]
        links = extract_links(html, self.cfg.get("link_pattern", r"\.pdf$"))
        if not links:
            raise AdapterError(f"{self.id}: 索引页上一个链接都没解析到（页面可能已改版）")

        rule = (family.get("locator") or {}).get("match")
        if not rule:
            raise AdapterError(f"{family['id']}: 缺少 locator.match，无法从列表里认领")

        hits = claim(links, rule)
        if not hits:
            raise AdapterError(f"{family['id']}: 索引页里没有匹配 {rule!r} 的链接")

        editions = (family.get("locator") or {}).get("edition_from")
        use_head = self.cfg.get("probe_mode") == "head"
        budget = int(self.cfg.get("max_head", MAX_HEAD_PER_FAMILY))
        out = {}
        for link in hits[:budget]:
            ed = edition_from(link, link["href"], editions)
            if use_head:
                meta = http.head_meta(absolute(link["href"], base))
                stamp = meta.get("etag") or meta.get("last-modified") or ""
                if stamp:
                    # 用 ETag/Last-Modified 当版本：链接不变但文件被覆盖也能发现
                    day = http.last_modified_iso(meta) or "na"
                    ed = f"{day}-{abs(hash(stamp)) % 100000:05d}"
            out[ed] = Document(
                standard_id=family["id"],
                edition=f"{family['no']}@{ed}",
                url=absolute(link["href"], base),
                published=find_date(link["label"] + " " + link["ctx"], self.cfg.get("date_patterns")),
                meta={"format": self.cfg.get("doc_format", "pdf"), "shape": "list",
                      "label": link["label"][:120]},
            )
        if len(hits) > budget:
            for d in out.values():
                d.meta["truncated"] = len(hits)
        return sorted(out.values(), key=lambda d: d.edition)

    def fetch(self, doc: Document) -> bytes:
        body = doc.meta.get("_body")
        if body:
            return body.encode("utf-8")
        return http.get(doc.url)

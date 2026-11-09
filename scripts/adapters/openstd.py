# -*- coding: utf-8 -*-
"""openstd（国家标准全文公开系统，GB 688）。

T1/T2 混合：列表页能拿到标准号与日期，正文常常是**扫描图片**。
所以这里只负责探测元数据；正文能不能用，交给 normalize 判定。

注意：本适配器是按公开页面结构写的通用表格解析，尚未对着线上页校准过。
解析不到时抛 AdapterError——宁可报错，也不返回空列表冒充「没有新版本」。
"""
import re

from lxml import html as lxml_html

from scripts import http
from scripts.adapters.base import AdapterError, Document

# 关键字搜索：p.p2=<标准号片段>。p.p1=1 强制性国家标准，p.p1=2 推荐性（GB/T）。
# 直接抓首页（每页 10 条、共 620 页）永远找不到具体标准，必须用关键字过滤。
LIST_URL = (
    "https://openstd.samr.gov.cn/bzgk/std/std_list_type"
    "?p.p1={p1}&p.p2={kw}&p.p90=circulation_date&p.p91=desc"
)

# GB 15083-2019 / GB/T 30512-2014
GB_NO = re.compile(r"(GB(?:/T)?\s*\d+(?:\.\d+)?)\s*[-–]\s*(\d{4})(?:\s*[-–]\s*(\d{4}))?")
DATE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})")


def clean_cell(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def parse_list(page: bytes) -> list[dict]:
    """把列表页解析成 [{no, name, published}]。找不到表格就抛错。"""
    try:
        tree = lxml_html.fromstring(page)
    except Exception as e:  # noqa: BLE001
        raise AdapterError(f"openstd 页面无法解析: {e}") from e

    rows = tree.xpath("//table//tr")
    if not rows:
        raise AdapterError("openstd 列表页里找不到 table/tr，页面结构可能已改版")

    out = []
    for tr in rows:
        cells = [clean_cell(t.text_content()) for t in tr.xpath("./td")]
        if len(cells) < 2:
            continue
        joined = " | ".join(cells)
        m = GB_NO.search(joined)
        if not m:
            continue
        no = re.sub(r"\s+", " ", m.group(1)).strip()
        year = m.group(2)
        published = None
        dm = DATE.search(joined)
        if dm:
            published = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
        name = next((c for c in cells if c and c != m.group(0)), "")
        out.append({"no": f"{no}-{year}", "name": name, "published": published})
    return out


def family_prefix(family: dict) -> str:
    """GB 14166-2013 → GB 14166。"""
    m = re.match(r"(GB(?:/T)?\s*[\d.]+)", family.get("no") or "")
    if not m:
        raise AdapterError(f"{family['id']}: 不是 GB 标准号：{family.get('no')!r}")
    return re.sub(r"\s+", " ", m.group(1)).strip()


class OpenStd:
    id = "openstd"

    def probe(self, family: dict) -> list[Document]:
        from urllib.parse import quote

        prefix = family_prefix(family)
        # GB/T 走推荐性标准（p1=2），纯 GB 走强制性（p1=1）
        p1 = 2 if "/T" in prefix else 1
        url = LIST_URL.format(p1=p1, kw=quote(prefix))
        items = parse_list(http.get(url, cache=False))
        hits = [i for i in items if i["no"].startswith(prefix + "-") or i["no"] == prefix]
        if not hits:
            raise AdapterError(f"{family['id']}: 关键字搜索没有找到 {prefix}（p1={p1}）")
        return [
            Document(
                standard_id=family["id"],
                edition=i["no"],
                url=url,
                published=i["published"],
                meta={"title": i["name"], "format": "unknown", "tier": "T1/T2"},
            )
            for i in sorted(hits, key=lambda x: x["no"])
        ]

    def fetch(self, doc: Document) -> bytes:
        raise AdapterError(
            f"{doc.standard_id}: openstd 正文为扫描件或需登录，P1 不自动下载；"
            f"请人工放进 data/texts/（页面会标「待人工补正文」）"
        )

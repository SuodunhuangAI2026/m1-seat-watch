# -*- coding: utf-8 -*-
"""把抓到的原始字节变成可比对的纯文本，并给出可信度判断。"""
import hashlib
import re

from lxml import html as lxml_html

from scripts import pdftext

MIN_CHARS = 400          # 少于此长度基本不可能是正文
MIN_PRINTABLE = 0.75     # 可打印字符占比低于此值判为乱码

PAGE_NO = re.compile(r"^\s*(?:[-–—]\s*)?(?:\d{1,4}|page\s+\d+\s*(?:of\s*\d+)?)(?:\s*[-–—])?\s*$", re.I)
# eCFR 页面顶部的抓取快照横幅（逐日变化）— 不看内容就没法区分真实修订
ECFR_BANNER = re.compile(
    r"^\s*Displaying title \d+,? up[- ]to[- ]date as of \d{2}/\d{2}/\d{4}",
    re.I,
)
MULTISPACE = re.compile(r"[ \t\u00a0]{2,}")


class UnusableDocument(RuntimeError):
    """抓到了字节，但拿不出可信的正文（扫描件、加密、字体未映射）。"""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def from_html(raw: bytes | str) -> str:
    # 先自己按 UTF-8 解码再交给 lxml：否则页面里残留的 windows-1252 声明
    # 会让 lxml 把已经正确的 UTF-8 再解一次，出现「Â」这类乱码
    text = raw if isinstance(raw, str) else raw.decode('utf-8-sig', 'replace')
    tree = lxml_html.fromstring(text)
    for bad in tree.xpath("//script|//style|//noscript"):
        bad.getparent().remove(bad)
    body = tree.xpath("//body")
    text = (body[0] if body else tree).text_content()
    return clean(text)


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    lines = [MULTISPACE.sub(" ", ln).strip() for ln in text.split("\n")]

    # 以空行切页：PDF 抽出来的文本通常靠空行分页，HTML 则基本只有一页
    pages = [[ln for ln in p.split("\n") if ln] for p in re.split(r"\n\s*\n", "\n".join(lines))]
    pages = [p for p in pages if p]

    # eCFR 顶部横幅「Displaying title 49, up to date as of 11/05/2026.」逐日变化；
    # 不过滤的话每天都会被比较成「修改」。逐页过滤，页面若因此变空则丢弃该页。
    pages_before = len(pages)
    pages = [[ln for ln in p if not ECFR_BANNER.match(ln)] for p in pages]
    pages = [p for p in pages if p]
    if not pages:
        raise UnusableDocument("整页都是快照横幅（eCFR as-of 日期页）")
    pages_after = len(pages)

    # 页眉页脚识别只在页数足够时做，只对装满内容的页面做，免得单页被过度识别，否则会把正常的重复小标题误删
    if len(pages) >= 3:
        from collections import Counter

        counter = Counter(ln for p in pages for ln in p if len(ln) <= 80)
        threshold = max(3, int(len(pages) * 0.6))
        repeated = {ln for ln, c in counter.items() if c >= threshold}

        trimmed = []
        for p in pages:
            body = [ln for ln in p if ln not in repeated]
            # 整页都是重复内容时保留原样，免得整页消失
            trimmed.append(body if body else p)
        pages = trimmed

    out: list[str] = []
    for p in pages:
        for ln in p:
            if PAGE_NO.match(ln):
                continue
            out.append(ln)

    joined = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def from_pdf(raw: bytes) -> str:
    try:
        text = pdftext.extract(raw)
    except Exception as e:  # noqa: BLE001
        raise UnusableDocument(f"PDF 解析失败: {e}") from e

    ratio = pdftext.printable_ratio(text)
    if len(text) < MIN_CHARS:
        raise UnusableDocument(
            f"PDF 里只有 {len(text)} 个字符，判为扫描件或仅图片版（不做 OCR）"
        )
    if ratio < MIN_PRINTABLE:
        raise UnusableDocument(
            f"PDF 文本可读率 {ratio:.0%}（多为 CJK 字体未映射），不做 OCR"
        )
    return clean(text)


def to_text(raw: bytes, *, kind: str) -> tuple[str, str]:
    """返回 (正文, 形式)。kind 由适配器给的 format 决定，兜底看魔术字节。"""
    if kind == "text":
        text = clean(raw.decode("utf-8-sig", "replace"))
        form = "text"
        if len(text) < MIN_CHARS:
            raise UnusableDocument(f"人工上传的文本只有 {len(text)} 个字符，太短")
        return text, form

    if kind == "html" or raw[:5].lower().startswith(b"<!doc") or raw[:5].lower().startswith(b"<html"):
        text = from_html(raw)
        form = "html"
    elif raw[:5] == b"%PDF-":
        text = from_pdf(raw)
        form = "pdf"
    else:
        raise UnusableDocument(f"不认识的内容类型：{raw[:8]!r}")

    if len(text) < MIN_CHARS:
        raise UnusableDocument(f"正文只有 {len(text)} 个字符，不像标准正文")
    return text, form


VERSION_PATTERNS = [
    r"version\s*[:\-]?\s*v?(\d+(?:\.\d+){0,2})",
    r"\bv(\d+\.\d+(?:\.\d+)?)\b",
    r"revision\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    r"edition\s*[:\-]?\s*(\d{4})",
    r"(\d{4})\s*年版",
]


def detect_version(text: str, limit: int = 4000) -> str | None:
    """从正文开头猜版本号。只做标注用，不参与存储键——猜错不至于丢数据。"""
    head = text[:limit]
    for pat in VERSION_PATTERNS:
        m = re.search(pat, head, re.I)
        if m:
            return m.group(1)
    return None

# -*- coding: utf-8 -*-
"""eCFR（49 CFR Part 571，FMVSS）。

探测策略：官方 API 给出 title 49 的「更新至」日期；正文按 section 页取。
一条 FMVSS = 571.{编号} 一节，编号从族注册表的 no 字段推出来，例如
「FMVSS No.202a」→ 571.202a。
"""
import hashlib
import json
import re

from scripts import http
from scripts.adapters.base import AdapterError, Document

TITLES_API = "https://www.ecfr.gov/api/versioner/v1/titles.json"
SECTION_URL = "https://www.ecfr.gov/current/title-49/section-{section}"

SECTION_RE = re.compile(r"^FMVSS\s+No\.?\s*([0-9]+[a-z]?)$", re.I)


def section_of(family: dict) -> str:
    """从族信息里取出 571.x 节号。"""
    loc = (family.get("locator") or {}).get("section")
    if loc:
        return loc
    m = SECTION_RE.match((family.get("no") or "").strip())
    if not m:
        raise AdapterError(f"{family['id']}: 无法从标准号推出 eCFR 节号：{family.get('no')!r}")
    return f"571.{m.group(1)}"


def title_49_cutoff(payload: bytes) -> str:
    """从 titles.json 里取 title 49 的 up_to_date_as_of。"""
    data = json.loads(payload.decode("utf-8"))
    for t in data.get("titles", []):
        if t.get("number") == 49:
            cutoff = t.get("up_to_date_as_of") or t.get("latest_issue_date")
            if not cutoff:
                raise AdapterError("titles.json 里 title 49 没有日期字段")
            return cutoff
    raise AdapterError("titles.json 里找不到 title 49")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class ECFR:
    id = "ecfr"

    def probe(self, family: dict) -> list[Document]:
        section = section_of(family)
        cutoff = title_49_cutoff(http.get(TITLES_API, cache=True))
        url = SECTION_URL.format(section=section)
        body = http.get(url)
        if b"<html" not in body[:2000].lower() and b"<div" not in body[:4000].lower():
            raise AdapterError(f"{family['id']}: eCFR 返回的不是 HTML")
        return [
            Document(
                standard_id=family["id"],
                edition=f"{section}@{cutoff}",
                url=url,
                published=cutoff,
                meta={"section": section, "content_sha256": digest(body), "format": "html"},
            )
        ]

    def fetch(self, doc: Document) -> bytes:
        return http.get(doc.url)

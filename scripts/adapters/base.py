# -*- coding: utf-8 -*-
"""适配器协议。

一个适配器 = 一个站点。它只回答两个问题：
  1. 这个站点上，某个标准族现在有哪些版本？（probe）
  2. 某个版本的正文字节怎么取？（fetch）

适配器不负责解析正文、不做 diff、不判断变更类型。
"""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Document:
    """站点上的一个版本载体。"""

    standard_id: str          # 对应 data/standards.json 的族 id
    edition: str              # 版本标识，如 R17.07、571.207、GB 15083-2019
    url: str                  # 正文地址
    published: str | None = None   # 发布日期 YYYY-MM-DD（拿不到就 None，不猜）
    meta: dict = field(default_factory=dict)  # 适配器私有信息，如 amd 号


class Adapter(Protocol):
    id: str

    def probe(self, family: dict) -> list[Document]:
        """返回该族在站点上可见的版本，按需自行排序。失败必须抛异常。"""
        ...

    def fetch(self, doc: Document) -> bytes:
        """取正文字节。失败必须抛异常。"""
        ...


class AdapterError(RuntimeError):
    """站点结构变了、认不出、或者页面里找不到该族。"""


def registry() -> dict[str, type]:
    """站点 id → 适配器类。新增站点只需在这里登记。"""
    from scripts.adapters import ecfr, openstd, unece

    return {
        "unece": unece.UNECE,
        "ecfr": ecfr.ECFR,
        "openstd": openstd.OpenStd,
    }


def get_adapter(site_id: str):
    try:
        cls = registry()[site_id]
    except KeyError:
        raise AdapterError(f"站点 {site_id} 还没有适配器") from None
    return cls()

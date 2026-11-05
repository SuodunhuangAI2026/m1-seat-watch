# -*- coding: utf-8 -*-
"""适配器协议与注册表。

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

    standard_id: str
    edition: str                    # 版本标识，如 R17.07a2、571.207@2026-11-03
    url: str
    published: str | None = None    # 发布日 YYYY-MM-DD；拿不到就 None，不猜
    meta: dict = field(default_factory=dict)


class Adapter(Protocol):
    id: str

    def probe(self, family: dict) -> list[Document]:
        """返回该族在站点上可见的版本。失败必须抛异常。"""
        ...

    def fetch(self, doc: Document) -> bytes:
        """取正文字节。失败必须抛异常。"""
        ...


class AdapterError(RuntimeError):
    """站点结构变了、认不出、或者页面里找不到该族。"""


# 专用适配器：有明确判定逻辑，值得单独写
SPECIAL = {}


def _special() -> dict:
    from scripts.adapters import ecfr, openstd, unece

    return {"unece": unece.UNECE, "ecfr": ecfr.ECFR, "openstd": openstd.OpenStd}


# 通用适配器：配置驱动，站点形状由 sites.json 的 shape 字段决定
MANUAL_SITES = {"qct", "gso", "ttbz"}

GENERIC_SITES = {"tc", "adr", "cncap", "ciasi", "eurlex", "echa",
                 "jncap", "kncap", "ancap", "asean", "latin", "euro", "iihs"}


def registry() -> dict[str, type]:
    """站点 id → 适配器类（仅专用适配器）。"""
    return _special()


def get_adapter(site_id: str, site_cfg: dict | None = None):
    cls = _special().get(site_id)
    if cls is not None:
        return cls()

    if (site_cfg and site_cfg.get("manual")) or site_id in MANUAL_SITES:
        from scripts.adapters import manual

        if not site_cfg:
            raise AdapterError(f"站点 {site_id} 需要配置")
        return manual.Manual(site_cfg)

    if site_id in GENERIC_SITES or (site_cfg and site_cfg.get("shape")):
        if not site_cfg:
            raise AdapterError(f"站点 {site_id} 需要配置，但没有提供 sites.json 条目")
        from scripts.adapters import generic

        return generic.GenericAdapter(site_cfg)

    raise AdapterError(f"站点 {site_id} 还没有适配器")

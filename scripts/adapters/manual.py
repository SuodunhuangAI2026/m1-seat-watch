# -*- coding: utf-8 -*-
"""人工上传适配器（T2 / T3）。

这些站没有可自动抓取的正文（付费、登录、扫描件、或根本没有公开源），
所以退一步：由人把文本放进 data/manual/<族 id>/ 下，系统负责比对与出报告。

约定：一个版本一个 .txt，文件名就是版本号，例如 `QC-T 740-2017.txt`。
新文件按修改时间取最新，跟上一版做 diff——流程和自动抓取完全一致。
"""
from pathlib import Path

from scripts.adapters.base import Document

ROOT = Path(__file__).resolve().parent.parent.parent
MANUAL = ROOT / "data" / "manual"


def folder(family_id: str) -> Path:
    return MANUAL / family_id


def uploads(family_id: str) -> list[Path]:
    d = folder(family_id)
    if not d.exists():
        return []
    return sorted((p for p in d.glob("*.txt") if p.is_file()), key=lambda p: p.stat().st_mtime)


class Manual:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.id = cfg["id"]

    def probe(self, family: dict) -> list[Document]:
        files = uploads(family["id"])
        if not files:
            return []
        latest = files[-1]
        return [Document(
            standard_id=family["id"],
            edition=latest.stem,
            url=f"data/manual/{family['id']}/{latest.name}",
            published=None,
            meta={"format": "text", "shape": "manual", "path": str(latest),
                  "uploads": len(files)},
        )]

    def fetch(self, doc: Document) -> bytes:
        return Path(doc.meta["path"]).read_bytes()

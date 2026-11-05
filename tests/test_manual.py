"""P5 测试：人工上传适配器。"""
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import normalize  # noqa: E402
from scripts.adapters import base, manual  # noqa: E402

TMPROOT = Path(__file__).resolve().parent / ".tmp"


class sandbox:
    def __enter__(self):
        self.dir = TMPROOT / uuid.uuid4().hex
        self.dir.mkdir(parents=True, exist_ok=True)
        self._old = manual.MANUAL
        manual.MANUAL = self.dir
        return self.dir

    def __exit__(self, *a):
        manual.MANUAL = self._old
        shutil.rmtree(self.dir, ignore_errors=True)


CFG = {"id": "qct", "name": "QC/T", "manual": True}
FAM = {"id": "QC-T-740-2017", "no": "QC/T 740-2017"}


def write(base: Path, fid: str, name: str, body: str, mtime: float | None = None) -> Path:
    d = base / fid
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))
    return p


def test_empty_returns_nothing():
    with sandbox():
        assert manual.Manual(CFG).probe(FAM) == []


def test_single_upload_becomes_edition():
    with sandbox() as base:
        write(base, "QC-T-740-2017", "QC-T 740-2017.txt", "5.1 座椅总成应满足……")
        docs = manual.Manual(CFG).probe(FAM)
        assert len(docs) == 1
        assert docs[0].edition == "QC-T 740-2017"


def test_latest_by_mtime_wins():
    with sandbox() as base:
        write(base, "QC-T-740-2017", "old.txt", "旧版", mtime=time.time() - 1000)
        write(base, "QC-T-740-2017", "new.txt", "新版", mtime=time.time())
        docs = manual.Manual(CFG).probe(FAM)
        assert docs[0].edition == "new"


def test_fetch_reads_file():
    with sandbox() as base:
        write(base, "QC-T-740-2017", "v1.txt", "5.1 内容", mtime=time.time())
        a = manual.Manual(CFG)
        doc = a.probe(FAM)[0]
        assert "5.1 内容" in a.fetch(doc).decode("utf-8")


def test_families_are_isolated():
    with sandbox() as base:
        write(base, "A", "v1.txt", "甲")
        assert manual.Manual(CFG).probe({"id": "B", "no": "B"}) == []


def test_text_kind_is_accepted():
    body = "5.1 座椅总成应满足下列要求。\n" * 40
    text, form = normalize.to_text(body.encode("utf-8"), kind="text")
    assert form == "text"
    assert "5.1" in text


def test_text_too_short_rejected():
    try:
        normalize.to_text("太短".encode("utf-8"), kind="text")
    except normalize.UnusableDocument as e:
        assert "字符" in str(e)
    else:
        raise AssertionError("应当抛 UnusableDocument")


def test_routing_goes_to_manual():
    adapter = base.get_adapter("qct", CFG)
    assert isinstance(adapter, manual.Manual)


def test_manual_site_without_config_raises():
    try:
        base.get_adapter("gso", None)
    except base.AdapterError:
        pass
    else:
        raise AssertionError("应当抛 AdapterError")


def test_links_block_keeps_local_paths_out_of_href():
    """人工上传的来源是本机相对路径，不能渲染成 <a href>，否则报告里会带出本地目录。"""
    from scripts import build_site

    html = build_site.links_block({"links": ["data/manual/QC-T-740-2017/v2.txt"]})
    assert "人工上传" in html
    assert "href" not in html

    html2 = build_site.links_block({"links": ["https://unece.org/a.pdf"]})
    assert 'href="https://unece.org/a.pdf"' in html2

"""P4 测试：HEAD 版本探测、版本号识别、认领精确性。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import http, normalize  # noqa: E402
from scripts.adapters import generic  # noqa: E402

IIHS = """<html><body><ul>
<li><a href="/media/aaa/LATCH_protocol.pdf">LATCH protocol</a></li>
<li><a href="/media/bbb/latch_rating_2024.pdf">LATCH evaluation - rating guidelines (May 2024)</a></li>
<li><a href="/media/ccc/whiplash_eval_2025.pdf">Whiplash prevention evaluation test protocol Dec2025</a></li>
<li><a href="/media/ddd/whiplash_rating_2025.pdf">Whiplash prevention rating guidelines Dec2025</a></li>
</ul></body></html>"""

ASEAN = """<html><body><ul>
<li><a href="/p/aop3.pdf">ASEAN-NCAP Assessment Protocol Adult Occupant Protection Version 3.0</a></li>
<li><a href="/p/overall30.pdf">ASEAN-NCAP Overall Assessment Protocol Version 3.0</a></li>
<li><a href="/p/overall31.pdf">ASEAN-NCAP Overall Assessment Protocol Version 3.1</a></li>
</ul></body></html>"""

CFG = {"id": "iihs", "name": "IIHS", "shape": "list",
       "entry_url": "https://www.iihs.org/protocols",
       "link_pattern": r"\.pdf$", "doc_format": "pdf", "probe_mode": "head"}


def stub(html, head):
    old_get, old_head = http.get, http.head_meta
    http.get = lambda url, **kw: html.encode()
    http.head_meta = lambda url, **kw: head
    return old_get, old_head


def restore(old_get, old_head):
    http.get, http.head_meta = old_get, old_head


def probe(html, head, family, cfg=CFG):
    old = stub(html, head)
    try:
        return generic.GenericAdapter(cfg).probe(family)
    finally:
        restore(*old)


def fam(match, fid="IIHS-LATCH-Protocol", no="LATCH protocol"):
    return {"id": fid, "no": no, "locator": {"match": match}}


def test_latch_protocol_not_confused_with_rating():
    docs = probe(IIHS, {}, fam(r"LATCH protocol"))
    assert len(docs) == 1
    assert docs[0].url.endswith("LATCH_protocol.pdf")


def test_latch_rating_not_confused_with_protocol():
    docs = probe(IIHS, {}, fam(r"LATCH\s*(evaluation|rating)", "IIHS-LATCH-Rating", "LATCH rating"))
    assert len(docs) == 1
    assert docs[0].url.endswith("latch_rating_2024.pdf")


def test_whiplash_protocol_vs_rating():
    proto = probe(IIHS, {}, fam(r"Whiplash prevention evaluation", "P", "wp"))
    rating = probe(IIHS, {}, fam(r"Whiplash prevention rating", "R", "wr"))
    assert proto[0].url.endswith("whiplash_eval_2025.pdf")
    assert rating[0].url.endswith("whiplash_rating_2025.pdf")


def test_head_sets_edition_from_last_modified():
    docs = probe(IIHS, {"last-modified": "Wed, 21 Oct 2026 07:28:00 GMT"},
                 fam(r"LATCH protocol"))
    assert docs[0].edition.startswith("LATCH protocol@2026-10-21-")


def test_head_without_validators_falls_back_to_filename():
    docs = probe(IIHS, {}, fam(r"LATCH protocol"))
    assert docs[0].edition == "LATCH protocol@LATCH_protocol.pdf"


def test_head_etag_changes_edition():
    a = probe(IIHS, {"etag": '"v1"'}, fam(r"LATCH protocol"))[0].edition
    b = probe(IIHS, {"etag": '"v2"'}, fam(r"LATCH protocol"))[0].edition
    assert a != b


def test_asean_overall_versions_are_separate():
    cfg = dict(CFG, id="asean", entry_url="http://www.aseancap.org/")
    old = stub(ASEAN, {})
    try:
        d30 = generic.GenericAdapter(cfg).probe(fam(r"Overall.{0,30}3\.0", "ASEAN-Overall-3.0", "Overall 3.0"))
        d31 = generic.GenericAdapter(cfg).probe(fam(r"Overall.{0,30}3\.1", "ASEAN-Overall-3.1", "Overall 3.1"))
    finally:
        restore(*old)
    assert d30[0].url.endswith("overall30.pdf")
    assert d31[0].url.endswith("overall31.pdf")


def test_detect_version_english():
    assert normalize.detect_version("Euro NCAP Whiplash\nVersion 3.3.1\nFebruary 2019") == "3.3.1"
    assert normalize.detect_version("Protocol v1.1") == "1.1"


def test_detect_version_chinese():
    assert normalize.detect_version("C-NCAP 管理规则（2027 年版）") == "2027"


def test_detect_version_none():
    assert normalize.detect_version("LATCH protocol") is None


def test_last_modified_iso():
    assert http.last_modified_iso({"last-modified": "Wed, 21 Oct 2026 07:28:00 GMT"}) == "2026-10-21"
    assert http.last_modified_iso({}) is None
    assert http.last_modified_iso({"last-modified": "garbage"}) is None

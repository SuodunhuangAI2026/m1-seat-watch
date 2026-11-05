"""P3 测试：通用适配器（list / document 两种形状）。不联网。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import http  # noqa: E402
from scripts.adapters import base, generic  # noqa: E402

CNCAP = """<html><body><ul>
<li><a href="/upload/2027/fuJianA.pdf">附录A 正面100%重叠刚性壁障碰撞测试评价规程</a></li>
<li><a href="/upload/2027/fuJianB.pdf">附录B 正面50%重叠移动渐进变形壁障碰撞试验规程</a></li>
<li><a href="/upload/2027/fuJianJ.pdf">附录J 低速后碰撞颈部保护测试评价规程</a></li>
<li><a href="/upload/2027/guanli.pdf">C-NCAP管理规则（2027年版）</a></li>
</ul></body></html>"""

TC = """<html><body><main>
<p>Motor Vehicle Safety Regulations (C.R.C., c. 1038)</p>
<p>Current to 2026-10-21</p>
<p>Last amended on 2026-06-17</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
<p>Regulation text line.</p>
</main></body></html>"""


def fake_get(body: bytes):
    def _get(url, **kw):
        return body
    return _get


def with_page(body, fn):
    old = http.get
    http.get = fake_get(body)
    try:
        return fn()
    finally:
        http.get = old


CNCAP_CFG = {"id": "cncap", "name": "C-NCAP", "shape": "list",
             "entry_url": "http://www.c-ncap.org.cn/guicheng/cncap",
             "link_pattern": r"\.pdf$", "doc_format": "pdf"}


def fam(match, no="C-NCAP 2027 附录J", fid="C-NCAP-2027-J"):
    return {"id": fid, "no": no, "locator": {"match": match}}


def test_list_claims_right_link():
    adapter = generic.GenericAdapter(CNCAP_CFG)
    docs = with_page(CNCAP.encode(), lambda: adapter.probe(fam(r"附录\s*J")))
    assert len(docs) == 1
    assert docs[0].url.endswith("fuJianJ.pdf")


def test_list_does_not_steal_neighbour():
    """附录 A 的规则不能把附录 J 也认领走——这是上下文窗口过宽时最典型的错。"""
    adapter = generic.GenericAdapter(CNCAP_CFG)
    docs = with_page(CNCAP.encode(), lambda: adapter.probe(fam(r"附录\s*A", "C-NCAP 2027 附录A", "A")))
    assert len(docs) == 1
    assert docs[0].url.endswith("fuJianA.pdf")


def test_list_no_match_raises():
    adapter = generic.GenericAdapter(CNCAP_CFG)
    try:
        with_page(CNCAP.encode(), lambda: adapter.probe(fam(r"附录\s*Z", "x", "Z")))
    except base.AdapterError as e:
        assert "没有匹配" in str(e)
    else:
        raise AssertionError("应当抛 AdapterError")


def test_list_without_locator_raises():
    adapter = generic.GenericAdapter(CNCAP_CFG)
    try:
        with_page(CNCAP.encode(), lambda: adapter.probe({"id": "X", "no": "X"}))
    except base.AdapterError as e:
        assert "locator" in str(e)
    else:
        raise AssertionError("应当抛 AdapterError")


def test_list_empty_page_raises():
    adapter = generic.GenericAdapter(CNCAP_CFG)
    try:
        with_page(b"<html><body>maintenance</body></html>", lambda: adapter.probe(fam(r"J")))
    except base.AdapterError as e:
        assert "改版" in str(e)
    else:
        raise AssertionError("应当抛 AdapterError")


def test_document_shape_uses_page_date():
    cfg = {"id": "tc", "name": "TC", "shape": "document", "doc_key": "C.R.C._c._1038",
           "entry_url": "https://laws-lois.justice.gc.ca/x",
           "date_patterns": [r"current\s+to\s+(\d{4}-\d{2}-\d{2})"]}
    adapter = generic.GenericAdapter(cfg)
    docs = with_page(TC.encode(), lambda: adapter.probe({"id": "CMVSS-207", "no": "CMVSS 207"}))
    assert docs[0].edition == "C.R.C._c._1038@2026-10-21"


def test_document_shape_without_date_raises():
    cfg = {"id": "tc", "shape": "document", "doc_key": "k",
           "entry_url": "https://x/y", "date_patterns": [r"nonsense-(\d{4})"]}
    adapter = generic.GenericAdapter(cfg)
    try:
        with_page(b"<html><body>no dates here</body></html>",
                  lambda: adapter.probe({"id": "X", "no": "X"}))
    except base.AdapterError as e:
        assert "日期" in str(e)
    else:
        raise AssertionError("应当抛 AdapterError")


def test_absolute_urls():
    assert generic.absolute("/a/b.pdf", "https://e.org/x") == "https://e.org/a/b.pdf"
    assert generic.absolute("//cdn.e.org/b.pdf", "https://e.org") == "https://cdn.e.org/b.pdf"
    assert generic.absolute("https://z.org/c.pdf", "https://e.org") == "https://z.org/c.pdf"
    assert generic.absolute("d.pdf", "https://e.org/x/") == "https://e.org/x/d.pdf"


def test_find_date_chinese():
    assert generic.find_date("发布日期：2026年11月5日") == "2026-11-05"


def test_get_adapter_routes():
    assert isinstance(base.get_adapter("unece"), base._special()["unece"])
    g = base.get_adapter("cncap", CNCAP_CFG)
    assert isinstance(g, generic.GenericAdapter)
    try:
        base.get_adapter("nope", None)
    except base.AdapterError:
        pass
    else:
        raise AssertionError("应当抛 AdapterError")

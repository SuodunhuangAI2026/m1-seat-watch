"""P1 测试：站点解析器（离线 fixture，不联网）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.adapters import ecfr, unece  # noqa: E402

UNECE_HTML = b"""<html><body><div class="view-content">
<ul>
  <li><a href="/fileadmin/DAM/trans/main/wp29/wp29regs/2013/R017r6e.pdf">R017r6e.pdf</a></li>
  <li><a href="/fileadmin/DAM/trans/main/wp29/wp29regs/2013/R017r6am1e.pdf">R017r6am1e.pdf</a></li>
  <li><a href="/fileadmin/DAM/trans/main/wp29/wp29regs/2018/R017r7e.pdf">R017r7e.pdf</a></li>
  <li><a href="/fileadmin/DAM/trans/main/wp29/wp29regs/2018/R017r7am2e.pdf">R017r7am2e.pdf</a></li>
  <li><a href="/fileadmin/DAM/trans/main/wp29/wp29regs/2018/R017r7am2f.pdf">R017r7am2f.pdf</a></li>
  <li><a href="/fileadmin/DAM/trans/main/wp29/wp29regs/2019/R021r2c1e.pdf">R021r2c1e.pdf</a></li>
</ul></div></body></html>"""


def test_unece_editions_parsed():
    fam = {"id": "UN-R17", "no": "UN R17", "locator": None}
    docs = unece.parse_index(UNECE_HTML, fam)
    editions = [d.edition for d in docs]
    assert editions == ["R17.06", "R17.06a1", "R17.07", "R17.07a2"], editions


def test_unece_filters_other_regulations():
    fam = {"id": "UN-R17", "no": "UN R17", "locator": None}
    docs = unece.parse_index(UNECE_HTML, fam)
    assert all("21" not in d.edition for d in docs)


def test_unece_prefers_english():
    fam = {"id": "UN-R17", "no": "UN R17", "locator": None}
    docs = {d.edition: d for d in unece.parse_index(UNECE_HTML, fam)}
    assert docs["R17.07a2"].url.endswith("R017r7am2e.pdf")


def test_unece_sorted_chronologically():
    fam = {"id": "UN-R17", "no": "UN R17", "locator": None}
    keys = [unece._sort_key(d.edition) for d in unece.parse_index(UNECE_HTML, fam)]
    assert keys == sorted(keys)


def test_unece_prefix_from_locator():
    fam = {"id": "UN-R21", "no": "UN R21", "locator": {"doc_prefix": "R021"}}
    docs = unece.parse_index(UNECE_HTML, fam)
    assert [d.edition for d in docs] == ["R21.02c1"]


TITLES = {
    "titles": [
        {"number": 48, "latest_issue_date": "2026-10-28", "up_to_date_as_of": "2026-11-03"},
        {"number": 49, "latest_issue_date": "2026-10-28", "up_to_date_as_of": "2026-11-03"},
    ],
    "meta": {"date": "2026-11-03"},
}


def test_ecfr_cutoff():
    assert ecfr.title_49_cutoff(json.dumps(TITLES).encode()) == "2026-11-03"


def test_ecfr_missing_title_raises():
    try:
        ecfr.title_49_cutoff(json.dumps({"titles": []}).encode())
    except Exception as e:  # noqa: BLE001
        assert "title 49" in str(e)
    else:
        raise AssertionError("应当抛异常")


def test_ecfr_section_from_no():
    assert ecfr.section_of({"id": "FMVSS-202a", "no": "FMVSS No.202a"}) == "571.202a"
    assert ecfr.section_of({"id": "FMVSS-207", "no": "FMVSS No.207"}) == "571.207"
    assert ecfr.section_of({"id": "FMVSS-10", "no": "FMVSS No.10"}) == "571.10"


def test_ecfr_section_prefers_locator():
    fam = {"id": "FMVSS-207", "no": "FMVSS No.207", "locator": {"section": "571.999"}}
    assert ecfr.section_of(fam) == "571.999"


def test_ecfr_rejects_non_fmvss():
    try:
        ecfr.section_of({"id": "CMVSS-207", "no": "CMVSS 207"})
    except Exception as e:  # noqa: BLE001
        assert "eCFR" in str(e)
    else:
        raise AssertionError("应当抛异常")

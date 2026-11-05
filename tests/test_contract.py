"""P0 冒烟测试：注册表与站点配置必须自洽。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8-sig"))


def test_sites_have_ids():
    sites = load("sites.json")["sites"]
    ids = [s["id"] for s in sites]
    assert len(ids) == len(set(ids)), "站点 id 重复"
    assert len(sites) == 19


def test_families_reference_known_sites():
    site_ids = {s["id"] for s in load("sites.json")["sites"]}
    fams = load("standards.json")["families"]
    unknown = [f["id"] for f in fams if f["site"] not in site_ids]
    assert not unknown, f"族绑定了不存在的站点: {unknown}"


def test_family_ids_unique():
    fams = load("standards.json")["families"]
    ids = [f["id"] for f in fams]
    assert len(ids) == len(set(ids)), "族 id 重复"


def test_every_site_has_family():
    sites = load("sites.json")["sites"]
    fams = load("standards.json")["families"]
    used = {f["site"] for f in fams}
    empty = [s["id"] for s in sites if s["id"] not in used]
    assert not empty, f"有站点没有任何族: {empty}"


def test_schedule_shape():
    cfg = load("schedule.json")
    assert cfg["timezone"] == "Asia/Shanghai"
    assert all(d in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"} for d in cfg["days"])
    hh, mm = cfg["time"].split(":")
    assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60

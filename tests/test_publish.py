"""P2 测试：事件落盘、去重、人工覆盖、报告页。"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import analyze, build_site, events, llm, publish, reviews, state  # noqa: E402

FAM = {"id": "UN-R17", "no": "UN R17", "title_cn": "座椅、座椅固定装置及头枕",
       "org": "UNECE", "site": "unece", "category": "core"}
CHANGES = [{"clause": "5.2.3", "kind": "modified", "old": "700 mm", "new": "720 mm"}]
GOOD = {"relevant": True, "part": "头枕", "criteria": [{"item": "头枕高度", "clause": "5.2.3"}],
        "design": True, "test": True, "summary": "高度 700→720。",
        "action": "复核头枕调节行程。", "confidence": 0.85}


def ok_client(system, user, temperature=0.2):
    return dict(GOOD), 10


def boom_client(system, user, temperature=0.2):
    raise llm.LLMUnavailable("没网")


class env:
    """把落盘目录临时指到 tmp，不污染仓库。"""

    def __enter__(self):
        # 系统临时目录在本机沙箱里不可写，改在仓库内建临时目录
        base = Path(__file__).resolve().parent / ".tmp" / uuid.uuid4().hex
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = base
        self._old = (events.CHANGES, state.STANDARDS, reviews.REVIEWS)
        events.CHANGES = base / "changes"
        state.STANDARDS = base / "standards"
        reviews.REVIEWS = base / "reviews"
        return base

    def __exit__(self, *a):
        events.CHANGES, state.STANDARDS, reviews.REVIEWS = self._old
        import shutil; shutil.rmtree(self.tmp, ignore_errors=True)


def test_process_creates_event():
    with env():
        ev = publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                             changes=CHANGES, date="2026-11-05", client=ok_client)
        assert ev["created"] is True
        assert ev["type"] == "NEW_EDITION"
        stored = events.load_day("2026-11-05")
        assert len(stored) == 1
        assert stored[0]["impact"]["relevant"] is True


def test_process_is_idempotent():
    with env():
        publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                        changes=CHANGES, date="2026-11-05", client=ok_client)
        again = publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                                changes=CHANGES, date="2026-11-05", client=ok_client)
        assert again["created"] is False
        assert len(events.load_day("2026-11-05")) == 1


def test_process_degrades_when_llm_down():
    with env():
        ev = publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                             changes=CHANGES, date="2026-11-05", client=boom_client)
        assert ev["impact"]["analyzed"] is False
        assert "没网" in ev["impact"]["error"]
        # 事件仍然落盘，没有被吞掉
        assert len(events.load_day("2026-11-05")) == 1


def test_process_degrades_on_bad_output():
    with env():
        def bad(system, user, temperature=0.2):
            return {"relevant": True}, 1
        ev = publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                             changes=CHANGES, date="2026-11-05", client=bad)
        assert ev["impact"]["analyzed"] is False
        assert "不合规" in ev["impact"]["error"]


def test_process_degrades_on_budget_exhausted():
    with env():
        def broker(system, user, temperature=0.2):
            raise llm.BudgetExceeded("本月额度已用尽")
        ev = publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                             changes=CHANGES, date="2026-11-05", client=broker)
        assert ev["impact"]["analyzed"] is False
        assert "额度" in ev["impact"]["error"]

def test_classify_types():
    assert events.classify("R17.06", "R17.07")[0] == "NEW_EDITION"
    assert events.classify("R17.07", "R17.07a2")[0] == "AMENDMENT"
    assert events.classify("R21.02", "R21.02c1")[0] == "CORRIGENDUM"
    assert events.classify("571.207@2026-01-01", "571.207@2026-11-03")[0] == "AMENDMENT"


def test_review_type_override():
    ev = {"id": "x", "type": "AMENDMENT", "impact": {"relevant": False}}
    view = reviews.apply(ev, {"override_type": "CORRIGENDUM", "override_relevant": True})
    assert view["type"] == "CORRIGENDUM"
    assert view["type_overridden"] is True
    assert view["impact"]["relevant"] is True
    assert view["impact"]["relevant_original"] is False


def test_review_md_opinion():
    with env():
        reviews.REVIEWS.mkdir(parents=True, exist_ok=True)
        (reviews.REVIEWS / "2026-11-05-UN-R17.md").write_text("已与锁工确认。", encoding="utf-8")
        data = reviews.load("2026-11-05-UN-R17")
        assert data["opinion_md"] == "已与锁工确认。"


def test_review_survives_rebuild():
    """人工意见写一次，重建后仍在——这条是硬要求。"""
    with env():
        publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                        changes=CHANGES, date="2026-11-05", client=ok_client)
        eid = "2026-11-05-UN-R17"
        reviews.REVIEWS.mkdir(parents=True, exist_ok=True)
        (reviews.REVIEWS / f"{eid}.json").write_text(
            json.dumps({"verdict": "confirmed", "opinion": "下一版 DVP 加测。"}, ensure_ascii=False),
            encoding="utf-8")

        first = build_site.report_page(build_site.view_of(events.load_day("2026-11-05")[0]))
        # 模拟再跑一次流水线（会重写事件文件）
        events.upsert(events.load_day("2026-11-05")[0])
        second = build_site.report_page(build_site.view_of(events.load_day("2026-11-05")[0]))

        assert "下一版 DVP 加测" in first
        assert "下一版 DVP 加测" in second


def test_report_has_all_sections():
    with env():
        ev = publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                             changes=CHANGES, date="2026-11-05", client=ok_client)
        html = build_site.report_page(build_site.view_of(ev))
        for section in ["1. 法规名称", "2. 变更摘要", "3. 时间节点", "4. 技术对比",
                        "5. 影响范围", "6. 建议动作", "7. 原文链接", "8. 处理意见"]:
            assert section in html, section
        assert "700 mm" in html and "720 mm" in html
        assert "头枕高度" in html


def test_report_marks_degraded():
    with env():
        ev = publish.process(family=FAM, old_ed="R17.06", new_ed="R17.07",
                             changes=CHANGES, date="2026-11-05", client=boom_client)
        html = build_site.report_page(build_site.view_of(ev))
        assert "未归因" in html
        assert "请人工判读" in html


def test_wants_attention():
    assert reviews.wants_attention({"impact": {"analyzed": False}}) is True
    assert reviews.wants_attention({"impact": {"needs_review": True}}) is True
    assert reviews.wants_attention({"impact": {"relevant": True, "confidence": 0.9}}) is False
    assert reviews.wants_attention({"impact": {"confidence": 0.9},
                                    "review": {"verdict": "rejected"}}) is True

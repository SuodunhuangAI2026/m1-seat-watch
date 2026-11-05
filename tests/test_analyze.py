"""P2 测试：归因层的校验与降级。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import analyze, llm  # noqa: E402

FAM = {"id": "UN-R17", "no": "UN R17", "title_cn": "座椅、座椅固定装置及头枕", "org": "UNECE"}
CHANGES = [{"clause": "5.2.3", "kind": "modified",
            "old": "at least 700 mm", "new": "at least 720 mm"}]

GOOD = {
    "relevant": True, "part": "头枕",
    "criteria": [{"item": "头枕高度", "clause": "5.2.3"}],
    "design": True, "test": True,
    "summary": "头枕最低高度由 700 提到 720。",
    "action": "复核头枕最高位调节行程。",
    "confidence": 0.85,
}


def fake(payload, calls=None, **kw):
    def _client(system, user, temperature=0.2):
        if calls is not None:
            calls.append(temperature)
        return dict(payload), 100
    return _client


def test_validate_ok():
    out = analyze.validate(dict(GOOD))
    assert out["relevant"] is True
    assert out["criteria"] == [{"item": "头枕高度", "clause": "5.2.3"}]
    assert out["confidence"] == 0.85


def test_validate_drops_criteria_without_clause():
    raw = dict(GOOD, criteria=[{"item": "头枕高度", "clause": ""}, {"item": "强度", "clause": "6.1"}])
    out = analyze.validate(raw)
    assert out["criteria"] == [{"item": "强度", "clause": "6.1"}]
    assert out["dropped_criteria"] == 1


def test_validate_caps_confidence_when_no_criteria():
    raw = dict(GOOD, confidence=0.95, criteria=[{"item": "x", "clause": ""}])
    out = analyze.validate(raw)
    assert out["criteria"] == []
    assert out["confidence"] <= 0.4


def test_validate_missing_field_raises():
    bad = dict(GOOD)
    bad.pop("summary")
    try:
        analyze.validate(bad)
    except analyze.InvalidOutput as e:
        assert "summary" in str(e)
    else:
        raise AssertionError("应当抛 InvalidOutput")


def test_validate_empty_summary_raises():
    try:
        analyze.validate(dict(GOOD, summary="   "))
    except analyze.InvalidOutput:
        pass
    else:
        raise AssertionError("应当抛 InvalidOutput")


def test_analyze_relevant_no_second_pass():
    calls = []
    impact = analyze.analyze(FAM, "R17.06", "R17.07", CHANGES, client=fake(GOOD, calls))
    assert impact["relevant"] is True
    assert impact["second_pass"]["done"] is False
    assert len(calls) == 1


def test_second_pass_agrees():
    calls = []
    payload = dict(GOOD, relevant=False, criteria=[], part="其他")
    impact = analyze.analyze(FAM, "R17.06", "R17.07", CHANGES, client=fake(payload, calls))
    assert impact["relevant"] is False
    assert impact["second_pass"] == {"done": True, "agrees": True}
    assert len(calls) == 2


def test_second_pass_disagrees_marks_review():
    payload = dict(GOOD, relevant=False, criteria=[], part="其他")
    state = {"n": 0}

    def client(system, user, temperature=0.2):
        state["n"] += 1
        if state["n"] == 1:
            return dict(payload), 10
        return dict(GOOD), 10

    impact = analyze.analyze(FAM, "R17.06", "R17.07", CHANGES, client=client)
    assert impact["relevant"] is True
    assert impact["needs_review"] is True
    assert impact["second_pass"]["agrees"] is False
    assert impact["confidence"] <= 0.45


def test_second_pass_failure_degrades_confidence():
    payload = dict(GOOD, relevant=False, criteria=[], part="其他")
    state = {"n": 0}

    def client(system, user, temperature=0.2):
        state["n"] += 1
        if state["n"] == 1:
            return dict(payload), 10
        raise llm.LLMUnavailable("boom")

    impact = analyze.analyze(FAM, "R17.06", "R17.07", CHANGES, client=client)
    assert impact["second_pass"]["done"] is False
    assert impact["confidence"] <= 0.5


def test_substance_routing():
    assert analyze.is_substance({"title_cn": "汽车禁用物质要求"}) is True
    assert analyze.is_substance({"title_cn": "REACH 高关注物质候选清单"}) is True
    assert analyze.is_substance(FAM) is False


def test_degraded_shape():
    d = analyze.degraded("超时")
    assert d["analyzed"] is False
    assert d["relevant"] is None
    assert "超时" in d["error"]

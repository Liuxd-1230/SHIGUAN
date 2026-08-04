"""WarningAggregator 测试（Phase 3A.1）。"""
from models import EvidenceWarning, WarningSeverity

from biography_engine.warning_aggregator import WarningAggregator, _sanitize_message


def _w(code: str, message: str, severity: WarningSeverity = WarningSeverity.INFO, src: str | None = None):
    return EvidenceWarning(code=code, message=message, severity=severity, sourcePath=src)


def test_single_warning_with_policy():
    ws = [
        _w(
            "title_holder_conflict",
            "头衔 d_xiyuan 顶层 holder(20423) 与 history 末项 holder(2686) 不一致；以顶层 holder 认定现任，不静默覆盖。",
            WarningSeverity.WARNING,
            "landed_titles/d_xiyuan",
        )
    ]
    out = WarningAggregator().aggregate(ws)
    assert len(out) == 1
    # 技术字段（头衔 key / 数字 id / sourcePath）不进入聚合结果。
    assert "d_xiyuan" not in out[0]
    assert "20423" not in out[0]
    assert "landed_titles" not in out[0]
    assert "顶层持有者" in out[0]
    assert "解析策略" in out[0]


def test_same_code_aggregated_with_count():
    ws = [_w("title_holder_conflict", "m", WarningSeverity.WARNING) for _ in range(12)]
    out = WarningAggregator().aggregate(ws)
    assert len(out) == 1
    assert "× 12" in out[0]


def test_different_codes_stay_separate():
    ws = [
        _w("title_holder_conflict", "m1", WarningSeverity.WARNING),
        _w("inferred_parent", "m2"),
        _w("unresolved_birth", "m3", WarningSeverity.WARNING),
    ]
    out = WarningAggregator().aggregate(ws)
    assert len(out) == 3
    assert any("父母" in s for s in out)
    assert any("出生日期" in s for s in out)


def test_unresolved_field_code_gets_label():
    ws = [_w("unresolved_faith", "字段 faith 的值是数字 id，实体索引中未命中可读名称。", WarningSeverity.WARNING)]
    out = WarningAggregator().aggregate(ws)
    assert any("「信仰」" in s and "不伪造名称" in s for s in out)


def test_unknown_code_falls_back_sanitized():
    ws = [_w("weird_code_xyz", "头衔 a_b_1 holder(42) 细节（被括号包裹）", WarningSeverity.INFO, "landed_titles/a_b_1")]
    out = WarningAggregator().aggregate(ws)
    assert len(out) == 1
    # 兜底：去除路径 / key / 括号细节 / 数字 id / 英文技术词。
    assert "landed_titles" not in out[0]
    assert "a_b_1" not in out[0]
    assert "42" not in out[0]
    assert "holder" not in out[0]


def test_sanitize_message_removes_technical_tokens():
    s = _sanitize_message("头衔 d_xiyuan 顶层 holder(20423) 与 history 末项 holder(2686) 不一致")
    assert "d_xiyuan" not in s
    assert "20423" not in s
    assert "holder" not in s

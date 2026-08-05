"""Phase 3C.1 人工验收基准（16 类角色样本）—— pytest 入口。

与 scripts/phase3c_acceptance.py 同源复用 phase3c_fixtures（人工验收与 CI 断言一致）。
"""
import pytest

from phase3c_fixtures import CASES, check_case


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_phase3c_case(case):
    failures = check_case(case)
    assert not failures, "\n".join(failures)


def test_phase3c_all_cases_count():
    assert len(CASES) == 16

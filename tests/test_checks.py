# -*- coding: utf-8 -*-
"""给「检查器」本身写的回归测试。

为什么需要这一层
----------------
校验手段也会失效。如果哪天有人改坏了一条检查的判定条件，
它会永远返回「通过」，看起来一切正常，实际上已经丧失检测能力 ——
而且这种失效是**静默**的，没有任何报错。

所以这里做两件事：
1. 用 `mock:good` 验证检查器**不误报**（19 条全部通过）；
2. 用 `mock:bad` 验证检查器**能抓出预设缺陷**（逐条断言该失败的要失败）。

运行：`pytest -q`
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from cases import CASES                       # noqa: E402
from checks import parse_json_report, run_case  # noqa: E402
from mock_data import BAD                     # noqa: E402
from providers import MockProvider            # noqa: E402
from suite import run_suite, summarize        # noqa: E402

CASE_BY_ID = {c.id: c for c in CASES}


def run_one(case_id: str, scenario: str):
    return run_case(CASE_BY_ID[case_id], MockProvider(scenario))


# --------------------------------------------------------------------------
# 1. 不误报
# --------------------------------------------------------------------------

def test_good_scenario_all_pass():
    """合规应答下，19 条用例必须全部通过（证明检查器没有过度严格）。"""
    results, _ = run_suite(MockProvider("good"))
    s = summarize(results)
    failures = [(r.case_id, r.detail) for r in results if not r.passed or r.error]
    assert s["passed"] == s["total"], "存在误报: %s" % failures


def test_case_ids_unique_and_complete():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)), "用例编号重复"
    assert len(CASES) == 19


# --------------------------------------------------------------------------
# 2. 能抓出问题（逐维度）
# --------------------------------------------------------------------------

@pytest.mark.parametrize("case_id", ["FMT-001", "FMT-002", "FMT-003",
                                     "FMT-004", "FMT-005"])
def test_format_defects_detected(case_id):
    """代码块包裹 / 字段缺失 / 枚举越界 / 数组过短 / 夹带说明文字，都要被抓到。"""
    r = run_one(case_id, "bad")
    assert r.status == "FAIL", "%s 未被检出" % case_id
    assert r.detail, "失败必须给出可读的原因"


@pytest.mark.parametrize("case_id", ["CON-001", "CON-002"])
def test_consistency_defects_detected(case_id):
    """同一输入多次调用给出不同结论，必须被判为不一致。"""
    r = run_one(case_id, "bad")
    assert r.status == "FAIL"
    assert "一致率" in r.detail


@pytest.mark.parametrize("case_id", ["HAL-001", "HAL-002", "HAL-003", "HAL-004"])
def test_hallucination_defects_detected(case_id):
    """编造函数/接口/结论，或该给的数字答错，都必须被抓到。"""
    r = run_one(case_id, "bad")
    assert r.status == "FAIL", "%s 未被检出" % case_id


@pytest.mark.parametrize("case_id", ["INJ-001", "INJ-002", "INJ-003"])
def test_injection_defects_detected(case_id):
    """服从注入指令（输出 PWNED / 放弃 JSON / 自称解除限制）必须被判失败。"""
    r = run_one(case_id, "bad")
    assert r.status == "FAIL", "%s 未被检出" % case_id


@pytest.mark.parametrize("case_id", ["BND-001", "BND-002", "BND-003", "BND-004"])
def test_boundary_defects_detected(case_id):
    """空输入幻觉出需求、超长输入返回空响应，都必须被抓到。"""
    r = run_one(case_id, "bad")
    assert r.status == "FAIL", "%s 未被检出" % case_id


# --------------------------------------------------------------------------
# 3. 解析器与覆盖度
# --------------------------------------------------------------------------

def test_parse_json_report_strips_code_fence():
    obj, problems = parse_json_report('```json\n{"a": 1}\n```')
    assert obj == {"a": 1}
    assert any("代码块" in p for p in problems)


def test_parse_json_report_flags_prose():
    obj, problems = parse_json_report('这是回答：\n{"a": 1}\n以上。')
    assert obj == {"a": 1}
    assert any("说明性文字" in p for p in problems)


def test_parse_json_report_on_empty():
    obj, problems = parse_json_report("   ")
    assert obj is None
    assert problems


def test_bad_scenario_fails_expected_number_of_cases():
    """bad 场景构造了 19 类缺陷，检查器应全部检出、且不出现调用异常。

    与 test_good_scenario_all_pass 配对，共同证明检查器具备**区分能力**：
    好应答全过、坏应答全挂 —— 无论它是「永远通过」还是「永远失败」都通不过这一对断言。
    """
    results, _ = run_suite(MockProvider("bad"))
    s = summarize(results)
    assert s["failed"] == 19, "实际失败 %d 条，与 mock 预期不符" % s["failed"]
    assert s["error"] == 0


def test_every_bad_case_has_scripted_response():
    """每个用例在 bad 场景下都要有预设应答，避免漏配导致假通过。"""
    for c in CASES:
        assert c.id in BAD, "用例 %s 缺少 bad 场景应答" % c.id

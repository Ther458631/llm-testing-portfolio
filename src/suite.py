# -*- coding: utf-8 -*-
"""套件编排与报告生成。"""
from __future__ import annotations

import platform
import time
from datetime import datetime

from cases import CASES, DIM_NAMES, OUTPUT_SCHEMA, cases_by_dim
from checks import run_case


def run_suite(provider, cases=None) -> tuple[list, float]:
    """执行全部用例，返回 (结果列表, 总耗时秒)。"""
    cases = cases if cases is not None else CASES
    t0 = time.perf_counter()
    results = []
    for c in cases:
        results.append(run_case(c, provider))
    return results, time.perf_counter() - t0


def summarize(results) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.passed and not r.error)
    errored = sum(1 for r in results if r.error)
    failed = total - passed - errored
    lat = [r.latency_ms for r in results if r.latency_ms]
    return {
        "total": total, "passed": passed, "failed": failed, "error": errored,
        "pass_rate": (passed / total * 100) if total else 0.0,
        "avg_latency_ms": (sum(lat) / len(lat)) if lat else 0.0,
        "sum_latency_ms": sum(lat),
    }


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("\n", " ") for x in r) + " |")
    return "\n".join(out)


def render_report(results, provider_name: str, elapsed: float,
                  title: str = "大模型输出质量测试报告") -> str:
    s = summarize(results)
    L: list[str] = []
    L.append("# %s" % title)
    L.append("")
    L.append("> 被测对象：`%s`　｜　用例数：%d　｜　生成时间：%s"
             % (provider_name, s["total"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    L.append("")
    L.append("## 一、总体结果")
    L.append("")
    L.append(_table(["指标", "数值"], [
        ["用例总数", s["total"]],
        ["通过", s["passed"]],
        ["失败", s["failed"]],
        ["异常（调用失败）", s["error"]],
        ["**通过率**", "**%.1f%%**" % s["pass_rate"]],
        ["平均响应", "%.1f ms" % s["avg_latency_ms"]],
        ["套件总耗时", "%.1f s" % elapsed],
        ["运行环境", "Python %s / %s"
         % (platform.python_version(), platform.system())],
    ]))
    L.append("")

    L.append("## 二、按维度统计")
    L.append("")
    rows = []
    by_dim: dict[str, list] = {}
    for r in results:
        by_dim.setdefault(r.dim, []).append(r)
    for dim in DIM_NAMES:
        rs = by_dim.get(dim, [])
        if not rs:
            continue
        p = sum(1 for r in rs if r.passed and not r.error)
        rows.append([DIM_NAMES[dim], len(rs), p, len(rs) - p,
                     "%.0f%%" % (p / len(rs) * 100)])
    L.append(_table(["维度", "用例数", "通过", "失败", "通过率"], rows))
    L.append("")

    L.append("## 三、失败与异常明细")
    L.append("")
    bad = [r for r in results if not r.passed or r.error]
    if not bad:
        L.append("无 —— 全部用例通过。")
    else:
        L.append(_table(["用例", "维度", "标题", "状态", "说明"],
                        [[r.case_id, DIM_NAMES.get(r.dim, r.dim), r.title,
                          r.status, r.detail] for r in bad]))
    L.append("")

    L.append("## 四、全部用例明细")
    L.append("")
    L.append(_table(["用例", "维度", "标题", "状态", "说明"],
                    [[r.case_id, DIM_NAMES.get(r.dim, r.dim), r.title,
                      r.status, r.detail] for r in results]))
    L.append("")

    if bad:
        L.append("## 五、结论")
        L.append("")
        L.append("本轮共 **%d** 条用例未通过，集中在：%s。"
                 % (len(bad), "、".join(sorted({DIM_NAMES.get(r.dim, r.dim)
                                                for r in bad}))))
        L.append("")
        L.append("这些失败项说明被测模型在该维度上尚不能直接接入下游流程 —— "
                 "例如输出被代码块包裹会导致解析失败，"
                 "严重等级在多轮之间漂移会导致同一缺陷得到不同处置。")
    return "\n".join(L)


def render_design_doc() -> str:
    """由用例定义生成测试设计文档，保证文档与代码同源。"""
    L: list[str] = []
    L.append("# 大模型输出质量测试 · 测试设计")
    L.append("")
    L.append("> 本文件由 `src/cases.py` 自动生成，请勿手工修改；"
             "改用例请改代码后重新执行 `python run_suite.py --emit-design`。")
    L.append("")
    L.append("## 一、测试目标")
    L.append("")
    L.append("大语言模型的输出是**自然语言**，不是确定的返回值，"
             "因此传统的断言方式（`assert result == expected`）不适用。"
             "本套件把「输出质量」拆成 5 个**可自动判定**的维度，"
             "让模型的接入具备可回归的质量门禁。")
    L.append("")
    L.append("## 二、约定的输出结构")
    L.append("")
    L.append("被测模型须输出严格 JSON（不得被代码块或说明文字包裹）：")
    L.append("")
    L.append(_table(["字段", "说明"], [[k, v] for k, v in OUTPUT_SCHEMA.items()]))
    L.append("")
    L.append("## 三、五个测试维度")
    L.append("")
    L.append(_table(["维度", "考察什么", "为什么可自动化"], [
        ["输出格式约束", "结构是否可被程序直接消费",
         "JSON 可解析、字段可校验、枚举可比对"],
        ["输出一致性", "同一输入的结论是否稳定",
         "多次调用后比对结构化字段的一致率"],
        ["事实性与幻觉", "是否编造不存在的事物",
         "对比事实库的必须包含/禁止出现列表"],
        ["提示词注入抵抗", "输入中夹带的指令是否被服从",
         "检查禁止串是否泄漏、格式是否被降级"],
        ["边界与鲁棒性", "异常输入下是否崩溃或幻觉",
         "断言有响应、长度合理、无意义输入被显式拒绝"],
    ]))
    L.append("")
    L.append("## 四、用例清单")
    L.append("")
    for dim, cs in cases_by_dim().items():
        if not cs:
            continue
        L.append("### %s（%s）" % (DIM_NAMES[dim], dim))
        L.append("")
        L.append(_table(["用例编号", "标题", "设计方法", "断言要点"],
                        [[c.id, c.title, c.design_method,
                          "、".join("%s=%s" % (k, v)
                                    for k, v in c.expect.items())]
                         for c in cs]))
        L.append("")
    L.append("## 五、判定原则")
    L.append("")
    L.append("- 每条用例由**一个**检查器判定，结论为 PASS / FAIL / ERROR 三态；")
    L.append("- ERROR 表示模型调用本身失败（超时、限流、鉴权），与质量缺陷区分开；")
    L.append("- 主观质量（文案可读性、业务合理性）**不纳入**自动判定，"
             "避免套件因主观标准而不可回归；")
    L.append("- `mock` 模式用于 CI：`scenario=good` 验证无误报，"
             "`scenario=bad` 验证检查器确实能抓出预设缺陷。")
    return "\n".join(L)

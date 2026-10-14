# -*- coding: utf-8 -*-
"""命令行入口。

示例
----
  # 离线跑一遍（CI 用），输出报告
  python run_suite.py --provider mock:good --report reports/report-mock-good.md

  # 用真实模型跑（先配置环境变量）
  set LLM_BASE_URL=https://api.deepseek.com/v1
  set LLM_API_KEY=sk-xxxx
  set LLM_MODEL=deepseek-chat
  python run_suite.py --provider env --report reports/report-live.md

  # 从用例定义重新生成测试设计文档
  python run_suite.py --emit-design
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from providers import build_provider          # noqa: E402
from suite import (render_design_doc, render_report,  # noqa: E402
                   run_suite, summarize)


def main() -> int:
    ap = argparse.ArgumentParser(description="大模型输出质量测试套件")
    ap.add_argument("--provider", default="mock:good",
                    help="mock:good / mock:bad / env / openai:<model>")
    ap.add_argument("--report", default="", help="报告输出路径（markdown）")
    ap.add_argument("--emit-design", action="store_true",
                    help="由用例定义生成 docs/test-design.md")
    ap.add_argument("--fail-on-fail", action="store_true",
                    help="存在失败用例时以非 0 退出（CI 门禁用）")
    args = ap.parse_args()

    if args.emit_design:
        path = os.path.join(HERE, "docs", "test-design.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_design_doc() + "\n")
        print("已生成测试设计文档: %s" % path)
        return 0

    provider = build_provider(args.provider)
    print("Provider = %s" % provider.name)
    results, elapsed = run_suite(provider)
    s = summarize(results)

    print("-" * 64)
    print("用例总数 %d ｜ 通过 %d ｜ 失败 %d ｜ 异常 %d ｜ 通过率 %.1f%%"
          % (s["total"], s["passed"], s["failed"], s["error"], s["pass_rate"]))
    print("平均响应 %.1f ms ｜ 总耗时 %.1f s"
          % (s["avg_latency_ms"], elapsed))
    print("-" * 64)
    for r in results:
        if not r.passed or r.error:
            print("  %-7s %-8s %s" % (r.status, r.case_id, r.detail[:70]))

    if args.report:
        path = args.report if os.path.isabs(args.report) else os.path.join(HERE, args.report)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_report(results, provider.name, elapsed) + "\n")
        print("报告已写入: %s" % path)

    provider.close()
    if args.fail_on_fail and (s["failed"] or s["error"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

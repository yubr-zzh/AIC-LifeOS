"""Run repeatable Agent-routing experiments against a running LifeOS API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.request import Request, urlopen


CASES = [
    ("self_plan", "帮我制定下周学习计划", "auto"),
    ("self_plan", "总结这段材料的重点", "auto"),
    ("self_plan", "比较两个方案的优缺点", "auto"),
    ("self_plan", "复盘这周的工作节奏", "auto"),
    ("self_plan", "给我三个写作选题建议", "auto"),
    ("self_plan", "把这些经历整理成心得", "auto"),
    ("agent", "运行 npm test 并修复失败用例", "auto"),
    ("agent", "读取项目文件并修改配置", "auto"),
    ("agent", "帮我写代码并生成一个脚本", "auto"),
    ("agent", "整理项目文件并移动目录", "auto"),
    ("agent", "部署服务到服务器", "auto"),
    ("agent", "给客户发送确认邮件", "auto"),
    ("self_plan", "运行部署脚本", "force_self_plan"),
    ("agent", "帮我写一份计划", "force_agent"),
]


def ask(base_url: str, prompt: str, policy: str, timeout: float) -> dict:
    request = Request(
        base_url,
        data=json.dumps(
            {"message": prompt, "routing_policy": policy},
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={"content-type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173/api/chat")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()

    failures = []
    for round_index in range(1, args.rounds + 1):
        print(f"\nRound {round_index}/{args.rounds}")
        for expected, prompt, policy in CASES:
            started = time.perf_counter()
            try:
                result = ask(args.base_url, prompt, policy, args.timeout)
                actual = result.get("decision")
                source = result.get("route_source")
                confidence = result.get("decision_confidence")
                elapsed = time.perf_counter() - started
                ok = actual == expected
                status = "OK" if ok else "MISMATCH"
                print(
                    f"{status:8} expected={expected:10} actual={str(actual):10} "
                    f"source={str(source):15} confidence={confidence} "
                    f"({elapsed:.2f}s) :: {prompt}"
                )
                if not ok:
                    failures.append((round_index, expected, actual, prompt))
            except Exception as exc:
                failures.append((round_index, expected, "request-error", prompt))
                print(f"ERROR    expected={expected:10} error={exc} :: {prompt}")
    print(f"\nCompleted {args.rounds * len(CASES)} experiments; mismatches={len(failures)}")
    if failures:
        for failure in failures:
            print("FAIL", failure)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

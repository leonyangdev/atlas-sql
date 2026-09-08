"""Gold SQL 执行与结果比较工具。

用途：
- 验证 Gold SQL 在固定数据快照上可重复执行
- 为各题目填充 expected_result_checksum
- 模型评测时对比模型 SQL 输出与 Gold 结果

用法：
    # 执行 train 集所有 Gold SQL 并打印结果
    uv run python scripts/run_benchmark.py --split train

    # 执行指定题目
    uv run python scripts/run_benchmark.py --split train --id train-001

    # 验证 Gold SQL 可重复性（两次运行结果一致）
    uv run python scripts/run_benchmark.py --split train --verify-repeatability

    # 输出 JSON 报告
    uv run python scripts/run_benchmark.py --split test --output results.json

注意：
    - 只使用 atlas_reader（只读身份），由 ATLAS_BUSINESS_DATABASE_URL 配置
    - 执行前请确认已运行 tiny 配置数据生成（uv run python scripts/seed_data.py --profile tiny ...）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 确保 server 包可被导入
sys.path.insert(0, str(Path(__file__).parent.parent))

BENCHMARK_DIR = Path(__file__).parent.parent / "benchmarks" / "v1"


def main() -> None:
    parser = argparse.ArgumentParser(description="AtlasSQL Gold SQL 执行与比较工具")
    parser.add_argument(
        "--split",
        choices=["train", "tune", "test", "all"],
        default="train",
        help="要执行的分割集（默认 train）",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="只执行指定题目 ID",
    )
    parser.add_argument(
        "--verify-repeatability",
        action="store_true",
        help="执行两次并比较结果，验证可重复性",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出 JSON 报告到指定文件",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=1000,
        help="每题最多返回的行数（默认 1000）",
    )
    args = parser.parse_args()

    results = asyncio.run(
        run(
            split=args.split,
            question_id=args.id,
            verify_repeatability=args.verify_repeatability,
            max_rows=args.max_rows,
        )
    )

    # 打印摘要
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{'=' * 50}")
    print(f"Total: {total}  Passed: {passed}  Failed: {total - passed}")
    print(f"Pass rate: {passed / total:.1%}" if total > 0 else "No questions executed")

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Results written to: {output_path}")

    if total > 0 and passed < total:
        sys.exit(1)


async def run(
    split: str = "train",
    question_id: str | None = None,
    verify_repeatability: bool = False,
    max_rows: int = 1000,
) -> list[dict[str, object]]:
    """执行 Gold SQL 并返回结果列表。"""
    from server.evaluation.benchmark_loader import load_all, load_split
    from server.evaluation.gold_executor import execute_gold_sql

    # 加载题目
    if split == "all":
        splits_data = load_all(BENCHMARK_DIR)
        questions = [q for s in splits_data.values() for q in s.questions]
    else:
        yaml_path = BENCHMARK_DIR / f"{split}.yaml"
        if not yaml_path.exists():
            print(f"ERROR: {yaml_path} not found", file=sys.stderr)
            sys.exit(1)
        split_data = load_split(yaml_path)
        questions = split_data.questions

    # 过滤指定题目
    if question_id:
        questions = [q for q in questions if q.id == question_id]
        if not questions:
            print(f"ERROR: question {question_id!r} not found", file=sys.stderr)
            sys.exit(1)

    results: list[dict[str, object]] = []

    for q in questions:
        result = await execute_gold_sql(q, max_rows=max_rows)

        if verify_repeatability and result.get("sql_executed"):
            # 再跑一次，比较校验和
            result2 = await execute_gold_sql(q, max_rows=max_rows)
            if result.get("checksum") != result2.get("checksum"):
                result["passed"] = False
                result["error"] = "repeatability check failed: checksums differ"

        print(
            f"[{'OK' if result.get('passed') else 'FAIL'}] {q.id}: "
            f"{q.question[:60]}{'...' if len(q.question) > 60 else ''}"
        )
        if not result.get("passed") and result.get("error"):
            print(f"       ERROR: {result['error']}")

        results.append(result)

    return results


if __name__ == "__main__":
    main()

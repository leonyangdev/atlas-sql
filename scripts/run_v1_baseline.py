"""运行冻结 V1 Sales 测试集并输出不含业务明细的实测报告。

示例：
    uv run python scripts/run_v1_baseline.py --provider deepseek

测试集不会进入 Prompt；筛选仅用 AST 判断 Gold SQL 是否落在冻结白名单，并始终保留拒绝与
澄清题。候选 SQL 和 trace_id 会进入报告，完整结果行不会落盘。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from server.config import get_settings
from server.db import create_control_engine, create_session_factory
from server.domain.query import QueryRequest, QueryResponse
from server.evaluation.baseline import BaselineEvaluator, select_v1_cases
from server.evaluation.benchmark_loader import BenchmarkQuestion, load_split
from server.evaluation.comparator import ResultSet
from server.execution.postgres import AsyncpgReadOnlyExecutor
from server.generation.factory import create_sql_generation_pipeline
from server.orchestrator.query import QueryOrchestrator
from server.query.repository import SQLAlchemyQueryRepository
from server.validation.sql import SQLValidator

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 AtlasSQL V1 Sales 基线评测")
    parser.add_argument("--provider", choices=["fake", "deepseek"], default="deepseek")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "evaluation" / "v1-baseline.json",
    )
    return parser.parse_args()


async def run(provider: str, output: Path) -> None:
    settings = get_settings().model_copy(update={"llm_provider": provider})
    if provider == "deepseek" and settings.deepseek_api_key is None:
        raise SystemExit("DEEPSEEK_API_KEY is required for the deepseek baseline")

    pipeline = create_sql_generation_pipeline(settings)
    validator = SQLValidator()
    gold_executor = AsyncpgReadOnlyExecutor(
        settings.business_database_url.get_secret_value(),
        statement_timeout_ms=settings.query_statement_timeout_ms,
        max_concurrency=1,
        max_rows=1_000,
    )
    control_engine = create_control_engine(settings.control_database_url)
    sessions = create_session_factory(control_engine)

    split = load_split(ROOT / "benchmarks" / "v1" / "test.yaml")
    questions = select_v1_cases(split.questions, validator)

    async def submit(question: str, identity: str) -> QueryResponse:
        async with sessions() as session:
            orchestrator = QueryOrchestrator(
                SQLAlchemyQueryRepository(session),
                data_version=settings.query_data_version,
                schema_version=settings.query_schema_version,
                model_version=pipeline.model_version,
                timeout_ms=settings.query_timeout_ms,
                pipeline=pipeline,
            )
            return await orchestrator.submit(QueryRequest(question=question), identity)

    async def execute_gold(question: BenchmarkQuestion) -> ResultSet:
        if question.gold_sql is None:
            return []
        result = await gold_executor.execute(
            validator.validate(question.gold_sql),
            timeout_ms=settings.query_statement_timeout_ms,
        )
        return [tuple(row) for row in result.rows]

    try:
        evaluator = BaselineEvaluator(submit, execute_gold)
        report = await evaluator.run(questions, environment=settings.environment)
        await asyncio.to_thread(_write_report, output, report.to_dict())
        print(
            f"sample_count={report.sample_count} "
            f"first_success_rate={report.metrics['first_success_rate']} "
            f"total_tokens={report.metrics['total_tokens']} output={output}"
        )
    finally:
        await pipeline.close()
        await gold_executor.close()
        await control_engine.dispose()


def _write_report(output: Path, payload: dict[str, object]) -> None:
    """在工作线程写报告，避免阻塞评测事件循环。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(run(arguments.provider, arguments.output))

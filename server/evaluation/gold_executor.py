"""Gold SQL 执行器。

只使用 atlas_reader 只读身份连接业务库。
执行前设置 statement_timeout 和 max_row_count 防止意外的大查询。
"""

from __future__ import annotations

import asyncio
import os
import time

import asyncpg

from server.evaluation.benchmark_loader import BenchmarkQuestion
from server.evaluation.comparator import ResultSet, result_checksum


async def execute_gold_sql(
    question: BenchmarkQuestion,
    max_rows: int = 1000,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    """执行单道题的 Gold SQL 并返回结构化结果。

    Args:
        question: BenchmarkQuestion 对象。
        max_rows: 最多返回的行数。
        timeout_seconds: SQL 超时时间。

    Returns:
        包含以下字段的字典：
        - question_id: 题目 ID
        - passed: 是否通过（执行成功且行数匹配）
        - sql_executed: 是否执行了 SQL（拒绝/澄清题为 False）
        - row_count: 返回的行数
        - checksum: 结果集校验和（无 SQL 时为 None）
        - latency_ms: SQL 执行耗时
        - error: 错误信息（成功时为 None）
    """
    # 拒绝/澄清题不执行 SQL
    if question.expected_action is not None:
        return {
            "question_id": question.id,
            "passed": True,  # 此处只验证 Gold 本身有效；真正验证模型行为用 compare_action
            "sql_executed": False,
            "row_count": 0,
            "checksum": None,
            "latency_ms": 0,
            "error": None,
        }

    if not question.gold_sql:
        return {
            "question_id": question.id,
            "passed": False,
            "sql_executed": False,
            "row_count": 0,
            "checksum": None,
            "latency_ms": 0,
            "error": "gold_sql is empty but expected_action is not set",
        }

    # 从环境变量读取业务库只读连接串
    db_url = os.environ.get("ATLAS_BUSINESS_DATABASE_URL")
    if not db_url:
        return {
            "question_id": question.id,
            "passed": False,
            "sql_executed": False,
            "row_count": 0,
            "checksum": None,
            "latency_ms": 0,
            "error": "ATLAS_BUSINESS_DATABASE_URL is not set",
        }

    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
    started = time.perf_counter()

    try:
        conn: asyncpg.Connection[asyncpg.Record] = await asyncio.wait_for(
            asyncpg.connect(dsn=dsn), timeout=timeout_seconds
        )
        try:
            # 设置只读事务和超时，防止意外写入或大查询
            await conn.execute("SET default_transaction_read_only = true")
            await conn.execute(f"SET statement_timeout = '{int(timeout_seconds * 1000)}ms'")

            sql = question.gold_sql.strip()
            # 添加 LIMIT 防护（如果 SQL 已有 LIMIT 则不重复添加）
            if "LIMIT" not in sql.upper() and max_rows > 0:
                sql = f"SELECT * FROM ({sql.rstrip(';')}) _gold_result LIMIT {max_rows}"

            rows = await conn.fetch(sql)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)

            result_set: ResultSet = [tuple(row.values()) for row in rows]
            checksum = result_checksum(result_set)

            # 校验行数（如果 expected_row_count 已填写）
            passed = True
            error = None
            if (
                question.expected_row_count is not None
                and len(result_set) != question.expected_row_count
            ):
                passed = False
                error = (
                    f"row count mismatch: expected={question.expected_row_count} "
                    f"actual={len(result_set)}"
                )

            # 校验校验和（如果 expected_result_checksum 已填写）
            if (
                passed
                and question.expected_result_checksum is not None
                and checksum != question.expected_result_checksum
            ):
                passed = False
                error = (
                    f"checksum mismatch: expected={question.expected_result_checksum} "
                    f"actual={checksum}"
                )

            return {
                "question_id": question.id,
                "passed": passed,
                "sql_executed": True,
                "row_count": len(result_set),
                "checksum": checksum,
                "latency_ms": latency_ms,
                "error": error,
            }

        finally:
            await conn.close()

    except asyncpg.PostgresError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "question_id": question.id,
            "passed": False,
            "sql_executed": True,
            "row_count": 0,
            "checksum": None,
            "latency_ms": latency_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    except TimeoutError:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "question_id": question.id,
            "passed": False,
            "sql_executed": True,
            "row_count": 0,
            "checksum": None,
            "latency_ms": latency_ms,
            "error": f"timeout after {timeout_seconds}s",
        }

"""PostgreSQL 只读查询执行器。

业务库连接只使用 reader DSN。每次查询都开启只读事务并设置事务内 statement_timeout；
外层信号量限制并发，包装 LIMIT 限制返回规模。取消或异常时事务上下文负责回滚并把连接归还
连接池，避免超时请求污染后续请求。
"""

from __future__ import annotations

import asyncio
import enum
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as datetime_time
from decimal import Decimal
from typing import Protocol

import asyncpg

from server.domain.query import QueryColumn, QueryErrorCode
from server.validation.sql import ValidatedSQL

QueryCell = str | int | float | bool | None


class ExecutionErrorKind(enum.StrEnum):
    TIMEOUT = "timeout"
    BUSY = "busy"
    DATABASE = "database"


class QueryExecutionError(RuntimeError):
    """执行层安全异常；不保存数据库原始错误文本。"""

    def __init__(self, kind: ExecutionErrorKind) -> None:
        super().__init__(kind.value)
        self.kind = kind

    @property
    def code(self) -> QueryErrorCode:
        return {
            ExecutionErrorKind.TIMEOUT: QueryErrorCode.EXECUTION_TIMEOUT,
            ExecutionErrorKind.BUSY: QueryErrorCode.EXECUTION_BUSY,
            ExecutionErrorKind.DATABASE: QueryErrorCode.EXECUTION_ERROR,
        }[self.kind]


@dataclass(frozen=True)
class ExecutionResult:
    """可安全序列化并持久化的查询结果。"""

    columns: tuple[QueryColumn, ...]
    rows: tuple[tuple[QueryCell, ...], ...]
    truncated: bool
    duration_ms: float


class ReadOnlyQueryExecutor(Protocol):
    """安全流水线依赖的执行器端口。"""

    async def execute(self, query: ValidatedSQL, *, timeout_ms: int) -> ExecutionResult: ...

    async def close(self) -> None: ...


class AsyncpgReadOnlyExecutor:
    """带连接池、并发门槛和结果上限的 asyncpg 实现。"""

    def __init__(
        self,
        dsn: str,
        *,
        statement_timeout_ms: int,
        max_concurrency: int,
        max_rows: int,
    ) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        self._statement_timeout_ms = statement_timeout_ms
        self._max_concurrency = max_concurrency
        self._max_rows = max_rows
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._pool: asyncpg.Pool | None = None
        self._pool_lock = asyncio.Lock()

    async def execute(self, query: ValidatedSQL, *, timeout_ms: int) -> ExecutionResult:
        """在总预算内取得并归还连接；取消信号原样向上传递。"""

        effective_timeout_ms = min(timeout_ms, self._statement_timeout_ms)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(effective_timeout_ms / 1_000):
                async with self._semaphore:
                    pool = await self._get_pool()
                    async with pool.acquire() as connection:
                        async with connection.transaction(readonly=True):
                            # 数值来自强校验配置，不含用户输入，可安全放入 SET LOCAL。
                            await connection.execute(
                                f"SET LOCAL statement_timeout = {effective_timeout_ms}"
                            )
                            limited_sql = (
                                "SELECT * FROM ("
                                f"{query.sql}"
                                ") AS atlas_limited_result "
                                f"LIMIT {self._max_rows + 1}"
                            )
                            statement = await connection.prepare(limited_sql)
                            records = await statement.fetch(timeout=effective_timeout_ms / 1_000)
                            attributes = statement.get_attributes()
            duration_ms = round((time.perf_counter() - started) * 1_000, 2)
        except asyncio.CancelledError:
            # 不吞掉调用方取消；asyncpg 事务上下文会回滚，acquire 上下文会归还连接。
            raise
        except (TimeoutError, asyncpg.QueryCanceledError) as exc:
            raise QueryExecutionError(ExecutionErrorKind.TIMEOUT) from exc
        except asyncpg.TooManyConnectionsError as exc:
            raise QueryExecutionError(ExecutionErrorKind.BUSY) from exc
        except (asyncpg.PostgresError, OSError, ConnectionError) as exc:
            raise QueryExecutionError(ExecutionErrorKind.DATABASE) from exc

        truncated = len(records) > self._max_rows
        visible_records = records[: self._max_rows]
        columns = tuple(
            QueryColumn(name=attribute.name, data_type=attribute.type.name)
            for attribute in attributes
        )
        rows = tuple(
            tuple(_serialize_cell(value) for value in record) for record in visible_records
        )
        return ExecutionResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            duration_ms=duration_ms,
        )

    async def close(self) -> None:
        """应用停止时释放业务连接池。"""

        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(
                    dsn=self._dsn,
                    min_size=1,
                    max_size=self._max_concurrency,
                    command_timeout=self._statement_timeout_ms / 1_000,
                    server_settings={"default_transaction_read_only": "on"},
                )
        return self._pool


def _serialize_cell(value: object) -> QueryCell:
    """把数据库类型转换为 JSON 稳定值，同时避免 Decimal 精度和时区丢失。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    # 白名单 SQL 通常不会返回复杂扩展类型；使用字符串保住展示能力和 JSON 可序列化性。
    return str(value)

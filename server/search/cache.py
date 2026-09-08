"""Redis 缓存命名空间、TTL 约定与缓存键生成。

命名规则：``atlas:{env}:{datasource_id}:{version}:{category}:{key}``

示例：
- Schema 缓存：``atlas:dev:1:398bf9ebf135:schema:table:fact_order``
- 查询结果缓存：``atlas:dev:*:*:query_result:{hash}``
- Session 上下文：``atlas:dev:*:*:session:{session_id}``

设计原则：
1. 包含 datasource_id 和 version，避免不同数据源或不同版本的缓存互相污染。
2. 包含 env 前缀，同一 Redis 实例可以服务多个环境（dev / staging）。
3. TTL 按用途分级：Schema 缓存较长（24h），查询结果较短（5min），Session 居中（2h）。
4. 元数据同步完成后主动失效 Schema 缓存，避免旧缓存影响检索。

缓存失效触发点：
- datasource 同步成功 → 失效该 datasource 的全部 schema 缓存
- 索引发布 → 失效 schema 缓存和 session 上下文
"""

from __future__ import annotations

import hashlib
import json
from enum import IntEnum


class CacheTTL(IntEnum):
    """缓存 TTL 分级（秒）。"""

    # Schema 结构变化少，缓存时间长
    SCHEMA = 86_400  # 24 小时
    # 指标定义偶尔变化
    METRIC = 43_200  # 12 小时
    # 查询结果可能随数据更新而变化
    QUERY_RESULT = 300  # 5 分钟
    # 多轮对话 Session 的中间状态
    SESSION = 7_200  # 2 小时
    # 速率限制窗口
    RATE_LIMIT = 60  # 1 分钟
    # 分布式锁
    LOCK = 30  # 30 秒


def make_schema_key(env: str, datasource_id: int, metadata_version: str, table_name: str) -> str:
    """生成表 schema 缓存的 Redis key。

    失效时使用 ``make_schema_prefix`` 批量删除该数据源的全部 schema 缓存。
    """
    return f"atlas:{env}:{datasource_id}:{metadata_version}:schema:table:{table_name}"


def make_schema_prefix(env: str, datasource_id: int) -> str:
    """生成 schema 缓存的前缀，用于 SCAN + DEL 批量失效。

    示例：``atlas:dev:1:``
    """
    return f"atlas:{env}:{datasource_id}:"


def make_query_result_key(env: str, sql_hash: str) -> str:
    """生成查询结果缓存的 Redis key。

    sql_hash 由调用方用 ``hash_sql`` 生成。
    """
    return f"atlas:{env}:*:*:query_result:{sql_hash}"


def make_session_key(env: str, session_id: str) -> str:
    """生成多轮对话 session 上下文的 Redis key。"""
    return f"atlas:{env}:*:*:session:{session_id}"


def make_rate_limit_key(env: str, user_id: str) -> str:
    """生成用户速率限制的 Redis key。"""
    return f"atlas:{env}:*:*:rate_limit:{user_id}"


def make_lock_key(env: str, resource: str) -> str:
    """生成分布式锁的 Redis key。

    resource 通常是操作名称，例如 ``"sync:datasource:1"``。
    """
    return f"atlas:{env}:*:*:lock:{resource}"


def hash_sql(sql: str) -> str:
    """生成 SQL 的稳定哈希，用作查询结果缓存键。

    对 SQL 先做规范化（去掉首尾空白，统一换行），再取 SHA-256 前 16 字节。
    """
    normalized = " ".join(sql.split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


class SchemaCache:
    """封装 schema 缓存的读写与失效逻辑。

    不直接暴露 Redis 原语，调用方通过此类操作缓存，
    方便后续替换底层 Redis 客户端或增加压缩逻辑。
    """

    def __init__(self, redis_client: object, env: str) -> None:
        """初始化。

        Args:
            redis_client: ``redis.asyncio.Redis`` 实例（鸭子类型）。
            env: 环境标识，例如 ``"development"``。
        """
        self._redis = redis_client
        self._env = env

    async def get_table(
        self,
        datasource_id: int,
        metadata_version: str,
        table_name: str,
    ) -> dict[str, object] | None:
        """读取表 schema 缓存，不存在时返回 None。"""
        key = make_schema_key(self._env, datasource_id, metadata_version, table_name)
        raw = await self._redis.get(key)  # type: ignore[attr-defined]
        if raw is None:
            return None
        return json.loads(raw)  # type: ignore[no-any-return]

    async def set_table(
        self,
        datasource_id: int,
        metadata_version: str,
        table_name: str,
        data: dict[str, object],
    ) -> None:
        """写入表 schema 缓存，TTL = SCHEMA 级别。"""
        key = make_schema_key(self._env, datasource_id, metadata_version, table_name)
        await self._redis.set(key, json.dumps(data, ensure_ascii=False), ex=CacheTTL.SCHEMA)  # type: ignore[attr-defined]

    async def invalidate_datasource(self, datasource_id: int) -> int:
        """批量删除指定数据源的全部 schema 缓存，返回删除的 key 数量。

        使用 SCAN 而不是 KEYS，避免大量 key 时阻塞 Redis 主线程。
        """
        prefix = make_schema_prefix(self._env, datasource_id)
        pattern = f"{prefix}*"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)  # type: ignore[attr-defined]
            if keys:
                deleted += await self._redis.delete(*keys)  # type: ignore[attr-defined]
            if cursor == 0:
                break
        return deleted

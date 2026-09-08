"""索引重建命令行工具。

用途：
- 首次建立索引
- 维度变更后强制重建
- 开发环境调试

用法：
    uv run python scripts/rebuild_index.py --index-type schema
    uv run python scripts/rebuild_index.py --index-type schema --datasource-id 1
    uv run python scripts/rebuild_index.py --index-type schema --via-celery

选项：
    --index-type  : schema | metrics | verified_queries（目前只实现 schema）
    --datasource-id : 只重建指定数据源；不传则重建全部
    --via-celery  : 通过 Celery 派发异步任务，默认为同步执行
    --batch-key   : 指定幂等键；默认自动生成 UUID

注意：重建索引会覆盖现有文档（OpenSearch upsert / Milvus upsert），
      不需要手动删除旧索引，除非向量维度发生变更。
      维度变更时需要先手动删除旧 Milvus collection，再重建。
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# 确保 server 包可被导入
sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="AtlasSQL 索引重建工具")
    parser.add_argument(
        "--index-type",
        choices=["schema", "metrics", "verified_queries"],
        default="schema",
        help="要重建的索引类型（默认 schema）",
    )
    parser.add_argument(
        "--datasource-id",
        type=int,
        default=None,
        help="只重建指定数据源（不传则重建全部）",
    )
    parser.add_argument(
        "--via-celery",
        action="store_true",
        help="通过 Celery 派发后台任务（需要 worker 正在运行）",
    )
    parser.add_argument(
        "--batch-key",
        type=str,
        default=None,
        help="指定幂等键（默认自动生成 UUID）",
    )
    args = parser.parse_args()

    batch_key = args.batch_key or str(uuid.uuid4())

    if args.index_type == "schema":
        _rebuild_schema(args.datasource_id, batch_key, via_celery=args.via_celery)
    else:
        print(f"ERROR: index_type '{args.index_type}' not yet implemented", file=sys.stderr)
        sys.exit(1)


def _rebuild_schema(datasource_id: int | None, batch_key: str, via_celery: bool) -> None:
    """执行 schema 索引重建。"""
    if via_celery:
        from server.tasks.index_build import build_schema_index_task

        result = build_schema_index_task.apply_async(
            kwargs={"datasource_id": datasource_id, "batch_key": batch_key},
            task_id=batch_key,
        )
        print(f"Dispatched schema index build task: {result.id}")
        print("Poll task status with: celery -A server.tasks.celery_app inspect active")
    else:
        # 同步执行（开发/调试用）
        from server.tasks.index_build import _run_index_build

        print(f"Starting synchronous schema index build (batch_key={batch_key})...")
        result = asyncio.run(_run_index_build(datasource_id, batch_key))
        status = result.get("status", "unknown")
        count = result.get("count", 0)
        batch_id = result.get("batch_id", "?")
        print(f"Result: batch_id={batch_id} status={status} count={count}")
        if status != "published":
            sys.exit(1)


if __name__ == "__main__":
    main()

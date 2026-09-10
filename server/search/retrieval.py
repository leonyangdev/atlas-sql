"""两级 Schema 召回：先召回表，再在候选表内召回列。

V2-S03-T02/T03 的核心逻辑：
    Level 1：Table Retrieval
        对全库表进行 Hybrid Search + RRF + Reranker，保留 top_table_n 张表。
    Level 2：Column Retrieval
        在候选表内进一步检索列，保留最相关的列；主外键强制保留。
    Token 预算裁剪（V2-S03-T03）：
        估算最终 Schema Context 的 token 数，超出 token_budget 时按分数从低到高裁剪，
        但主外键和时间字段被标记为 protected，不会被裁掉。

四路配置对比（消融实验）：
    - bm25_only: SearchRepository 使用 RRFFusion(bm25_only=True)
    - dense_only: SearchRepository 使用 RRFFusion(dense_only=True)
    - hybrid: SearchRepository 使用正常 RRFFusion（不接 Reranker）
    - hybrid+rerank: SearchRepository 使用 RRFFusion + Reranker（默认配置）

调用链：
    TwoLevelRetriever.retrieve(question, intent)
        → SearchRepository.search_schema(query, object_types=["table"])   # Level 1
        → Reranker.rerank(question, table_candidates, top_n=top_table_n)
        → SearchRepository.search_schema(query, table_doc_ids)            # Level 2
        → Reranker.rerank(question, column_candidates, top_n=top_col_n)
        → _protect_required_fields(column_candidates)
        → _budget_trim(table + column candidates, token_budget)
        → SchemaContext
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from server.domain.intent import QueryIntent
from server.search.reranker import BaseReranker, FakeReranker
from server.search.repository import Candidate, SearchRepository

logger = logging.getLogger(__name__)

# 每个字段在 Prompt 中大约占用的 token 数（粗略估算）
# 实际 token 数由 tiktoken 计算，此处为简化版本
_TOKENS_PER_TABLE_HEADER = 20
_TOKENS_PER_COLUMN = 15


@dataclass
class SchemaContext:
    """两级召回后的 Schema 上下文，供 SQL 生成阶段使用。

    Attributes:
        tables: 召回的表候选，已按相关性排序。
        columns: 召回的列候选，已按相关性排序（包含强制保留的连接键）。
        estimated_tokens: 粗略的 token 估算值。
        token_budget_exceeded: 是否触发了 token 裁剪。
        retrieval_config: 本次召回使用的配置（用于消融报告）。
    """

    tables: list[Candidate] = field(default_factory=list)
    columns: list[Candidate] = field(default_factory=list)
    estimated_tokens: int = 0
    token_budget_exceeded: bool = False
    retrieval_config: str = "hybrid+rerank"  # bm25_only | dense_only | hybrid | hybrid+rerank

    def table_names(self) -> list[str]:
        """返回召回的表名列表（从 payload 中提取）。"""
        return [
            c.payload.get("table_name", c.doc_id)
            for c in self.tables
        ]

    def to_prompt_schema(self) -> list[dict[str, object]]:
        """将召回结果转换为 Prompt 可用的 Schema 描述列表。

        每张表包含：table_name、business_name、description、columns[]。
        """
        # 按表组织列
        table_columns: dict[str, list[Candidate]] = {}
        for col in self.columns:
            table_name = col.payload.get("table_name", "")
            if table_name:
                table_columns.setdefault(table_name, []).append(col)

        result = []
        for table in self.tables:
            table_name = table.payload.get("table_name", table.doc_id)
            cols = table_columns.get(table_name, [])
            result.append({
                "table_name": table_name,
                "business_name": table.payload.get("business_name", ""),
                "description": table.payload.get("description", ""),
                "domain": table.domain,
                "columns": [
                    {
                        "column_name": c.payload.get("column_name", ""),
                        "data_type": c.payload.get("data_type", ""),
                        "business_name": c.payload.get("business_name", ""),
                        "description": c.payload.get("description", ""),
                        "is_primary_key": c.payload.get("is_primary_key", False),
                        "foreign_key_ref": c.payload.get("foreign_key_ref"),
                    }
                    for c in cols
                ],
            })
        return result


class TwoLevelRetriever:
    """两级 Schema 召回器：先表后列，带 token 预算保护。

    Args:
        repository: 统一检索仓储（满足 SearchRepository 协议）。
        reranker: 重排器；None 时跳过重排步骤（消融实验 hybrid 配置）。
        top_table_n: Level 1 保留的最大表数量。
        top_col_n: Level 2 保留的最大列数量（每张表）。
        token_budget: 最终 Schema Context 允许的最大 token 数；超出时裁剪低分列。
    """

    def __init__(
        self,
        repository: SearchRepository,
        reranker: BaseReranker | None = None,
        top_table_n: int = 10,
        top_col_n: int = 30,
        token_budget: int = 4_000,
    ) -> None:
        self._repo = repository
        self._reranker = reranker
        self._top_table_n = top_table_n
        self._top_col_n = top_col_n
        self._token_budget = token_budget

    async def retrieve(
        self,
        question: str,
        intent: QueryIntent,
        *,
        datasource_id: int,
        metadata_version: str | None = None,
        retrieval_config: str = "hybrid+rerank",
    ) -> SchemaContext:
        """执行两级召回，返回 SchemaContext。

        Args:
            question: 用户原始问题。
            intent: 域路由结果，用于限定 allowed_domains 和提取过滤关键词。
            datasource_id: 数据源 ID。
            metadata_version: 元数据版本。
            retrieval_config: 配置标签，仅用于报告记录。
        """
        allowed_domains = list(intent.domain_candidates.keys()) if intent.domain_candidates else []

        # ── Level 1: Table Retrieval ──────────────────────────────────────
        table_result = await self._repo.search_schema(
            question,
            datasource_id=datasource_id,
            allowed_domains=allowed_domains,
            object_types=["table"],
            metadata_version=metadata_version,
            top_k=self._top_table_n * 2,  # 先多召回，再重排裁剪
        )

        table_candidates = table_result.candidates
        if self._reranker and table_candidates:
            table_candidates = self._reranker.rerank(
                question, table_candidates, top_n=self._top_table_n
            )
        else:
            table_candidates = table_candidates[:self._top_table_n]

        if not table_candidates:
            logger.warning("No table candidates found for question: %s", question[:50])
            return SchemaContext(retrieval_config=retrieval_config)

        # ── Level 2: Column Retrieval ─────────────────────────────────────
        # 在候选表的范围内检索列（通过 doc_id 前缀过滤）
        table_names = [c.payload.get("table_name", "") for c in table_candidates if c.payload.get("table_name")]
        col_result = await self._repo.search_schema(
            question,
            datasource_id=datasource_id,
            allowed_domains=allowed_domains,
            object_types=["column"],
            metadata_version=metadata_version,
            top_k=self._top_col_n * 2,
        )

        # 只保留属于候选表的列（按 table_name 过滤）
        col_candidates = [
            c for c in col_result.candidates
            if c.payload.get("table_name") in table_names
        ]

        if self._reranker and col_candidates:
            col_candidates = self._reranker.rerank(
                question, col_candidates, top_n=self._top_col_n
            )
        else:
            col_candidates = col_candidates[:self._top_col_n]

        # ── Token 预算裁剪 ────────────────────────────────────────────────
        estimated = _estimate_tokens(table_candidates, col_candidates)
        budget_exceeded = estimated > self._token_budget

        if budget_exceeded:
            col_candidates = _budget_trim(
                col_candidates,
                token_budget=self._token_budget - len(table_candidates) * _TOKENS_PER_TABLE_HEADER,
            )
            estimated = _estimate_tokens(table_candidates, col_candidates)
            logger.info(
                "Token budget trimmed: %d → %d tokens, %d columns remaining",
                estimated, self._token_budget, len(col_candidates),
            )

        return SchemaContext(
            tables=table_candidates,
            columns=col_candidates,
            estimated_tokens=estimated,
            token_budget_exceeded=budget_exceeded,
            retrieval_config=retrieval_config,
        )


def _estimate_tokens(
    tables: list[Candidate],
    columns: list[Candidate],
) -> int:
    """粗略估算 Schema Context 的 token 数。

    实际 token 数取决于 Prompt 格式和 tokenizer；这里使用简单的计数规则：
    每张表头约 20 token，每个列约 15 token。
    """
    return len(tables) * _TOKENS_PER_TABLE_HEADER + len(columns) * _TOKENS_PER_COLUMN


def _budget_trim(
    columns: list[Candidate],
    token_budget: int,
) -> list[Candidate]:
    """按 token 预算裁剪列候选，优先保留必需字段（主外键）。

    算法：
    1. 将列分为 protected（主键/外键）和 ordinary 两组；
    2. protected 组全部保留；
    3. 在剩余预算内从 ordinary 组按分数从高到低保留。
    """
    protected: list[Candidate] = []
    ordinary: list[Candidate] = []

    for c in columns:
        if c.payload.get("is_primary_key") or c.payload.get("foreign_key_ref"):
            protected.append(c)
        else:
            ordinary.append(c)

    # 保护字段占用的 token 数
    protected_tokens = len(protected) * _TOKENS_PER_COLUMN
    remaining_budget = max(0, token_budget - protected_tokens)

    # ordinary 按分数降序，在预算内尽量保留
    ordinary.sort(key=lambda c: c.score, reverse=True)
    kept_ordinary: list[Candidate] = []
    used_tokens = 0
    for c in ordinary:
        if used_tokens + _TOKENS_PER_COLUMN > remaining_budget:
            break
        kept_ordinary.append(c)
        used_tokens += _TOKENS_PER_COLUMN

    # 合并后保持原有相对顺序（按分数）
    result = protected + kept_ordinary
    result.sort(key=lambda c: c.score, reverse=True)
    return result

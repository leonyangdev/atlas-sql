"""V3 语义对象检索扩展。

在 V2 SearchRepository 基础上，支持检索：
- 指标 embedding（metric:* 对象类型）
- 维度 embedding（dimension:* 对象类型）
- 业务术语 embedding（glossary:* 对象类型）
- 已验证查询（verified_query:* 对象类型）

SemanticSearchRepository 实现 SearchRepository 协议的扩展版本：
- search_metrics()：按语义相似度检索相关指标，结合权限域过滤
- search_dimensions()：检索相关维度定义
- search_verified_queries()：检索相关已验证查询（按域/权限/版本过滤）

核心设计：
1. 每个语义对象（Metric/Dimension/VerifiedQuery）在索引时生成两路文档：
   - BM25（OpenSearch）：label、synonyms、description 文本拼接
   - Dense（Milvus）：label + expression + synonyms 的语义向量
2. 授权过滤在 Repository 层执行，不依赖 LLM 生成 SQL 时再过滤。
3. InMemorySemanticRepository 供离线测试使用，不依赖真实向量服务。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from server.search.repository import (
    Candidate,
    CandidateSource,
    InMemorySearchRepository,
    RetrievalStatus,
    SearchResult,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 语义对象的 doc_id 约定
# ──────────────────────────────────────────────────────────────

def metric_doc_id(metric_id: str) -> str:
    return f"metric:{metric_id}"


def dimension_doc_id(dimension_id: str) -> str:
    return f"dimension:{dimension_id}"


def glossary_doc_id(term: str, target_type: str) -> str:
    return f"glossary:{target_type}:{term.lower().replace(' ', '_')}"


def verified_query_doc_id(query_id: str) -> str:
    return f"verified_query:{query_id}"


# ──────────────────────────────────────────────────────────────
# 语义索引记录构建辅助
# ──────────────────────────────────────────────────────────────


def build_metric_index_text(
    metric_id: str,
    label: str,
    expression: str,
    synonyms: list[str],
    required_filters: list[str],
    time_rule_note: str | None = None,
    warning: str | None = None,
) -> str:
    """将指标定义序列化为索引文本（BM25 + Dense 共用）。

    格式：label | synonyms | expression | required_filters | time_rule_note
    设计原则：表达式和过滤规则是高权重字段，放在前半段提高 BM25 命中率。
    """
    parts = [label]
    if synonyms:
        parts.append(" ".join(synonyms))
    parts.append(expression)
    if required_filters:
        parts.append(" ".join(required_filters))
    if time_rule_note:
        parts.append(time_rule_note)
    if warning:
        parts.append(warning)
    return " | ".join(parts)


def build_dimension_index_text(
    dimension_id: str,
    label: str,
    description: str | None,
    synonyms: list[str],
    column_refs: list[str],
) -> str:
    """将维度定义序列化为索引文本。"""
    parts = [label]
    if synonyms:
        parts.append(" ".join(synonyms))
    if column_refs:
        parts.append(" ".join(column_refs))
    if description:
        parts.append(description)
    return " | ".join(parts)


def build_verified_query_index_text(question: str, sql: str, tags: list[str]) -> str:
    """将可信查询序列化为索引文本。

    问题文本权重最高（用于语义相似匹配），SQL 次之（帮助检索相似 SQL 模式）。
    """
    parts = [question]
    if tags:
        parts.append(" ".join(tags))
    # SQL 只取前 500 字符防止文本过长
    parts.append(sql[:500])
    return " | ".join(parts)


# ──────────────────────────────────────────────────────────────
# InMemory 语义检索仓储（离线测试用）
# ──────────────────────────────────────────────────────────────


class InMemorySemanticRepository(InMemorySearchRepository):
    """在 InMemorySearchRepository 基础上扩展语义对象检索能力。

    通过 register_metric_candidates() / register_dimension_candidates()
    预置测试数据，模拟真实索引。

    权限过滤规则：
    - allowed_domains 为空列表 = 不限制
    - is_test_locked=True 的 VerifiedQuery 不能被 search_verified_queries 返回
    - semantic_version_ref 版本过滤由调用方判断（此处不做版本检查）
    """

    def __init__(self) -> None:
        super().__init__()
        self._metric_candidates: list[Candidate] = []
        self._dimension_candidates: list[Candidate] = []

    def register_metric_candidates(self, candidates: list[Candidate]) -> None:
        """预置指标候选（测试用）。"""
        self._metric_candidates = list(candidates)

    def register_dimension_candidates(self, candidates: list[Candidate]) -> None:
        """预置维度候选（测试用）。"""
        self._dimension_candidates = list(candidates)

    async def search_metrics(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 10,
    ) -> SearchResult:
        """按语义相似度检索相关指标（内存实现）。"""
        results = [
            c for c in self._metric_candidates
            if not allowed_domains or c.domain in allowed_domains
        ]
        results.sort(key=lambda c: c.score, reverse=True)
        return SearchResult(
            candidates=results[:top_k],
            status=RetrievalStatus.OK,
            bm25_count=len(results[:top_k]),
        )

    async def search_dimensions(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 10,
    ) -> SearchResult:
        """按语义相似度检索相关维度（内存实现）。"""
        results = [
            c for c in self._dimension_candidates
            if not allowed_domains or c.domain in allowed_domains
        ]
        results.sort(key=lambda c: c.score, reverse=True)
        return SearchResult(
            candidates=results[:top_k],
            status=RetrievalStatus.OK,
            bm25_count=len(results[:top_k]),
        )

    async def search_verified_queries(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 5,
    ) -> SearchResult:
        """按问题语义检索已验证查询，过滤锁定测试集（内存实现）。

        约束：
        - is_test_locked=True 的样例不返回（防止题库泄漏）
        - 仅返回 status=verified 的样例（DRAFT/INVALID 不可召回）
        """
        results = [
            c for c in self._verified_query_candidates
            if (not allowed_domains or c.domain in allowed_domains)
            and not c.payload.get("is_test_locked", False)
            and c.payload.get("status") == "verified"
        ]
        results.sort(key=lambda c: c.score, reverse=True)
        return SearchResult(
            candidates=results[:top_k],
            status=RetrievalStatus.OK,
        )


# ──────────────────────────────────────────────────────────────
# 语义检索结果数据类
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetricSearchResult:
    """语义检索返回的指标匹配结果。

    Attributes:
        metric_id: 指标 ID。
        score: 检索得分。
        label: 展示名（来自 payload）。
        expression: 表达式（来自 payload）。
        required_filters: 强制过滤（来自 payload）。
        evidence: 检索依据（同义词命中 / 向量相似）。
    """

    metric_id: str
    score: float
    label: str = ""
    expression: str = ""
    required_filters: list[str] = field(default_factory=list)
    evidence: str = "semantic_search"

    @classmethod
    def from_candidate(cls, c: Candidate) -> "MetricSearchResult":
        return cls(
            metric_id=c.doc_id.removeprefix("metric:"),
            score=c.score,
            label=c.payload.get("label", ""),
            expression=c.payload.get("expression", ""),
            required_filters=c.payload.get("required_filters") or [],
            evidence=c.source.value if hasattr(c.source, "value") else str(c.source),
        )


@dataclass(frozen=True)
class VerifiedQuerySearchResult:
    """已验证查询检索结果。

    Attributes:
        query_id: 样例 ID。
        question: 问题文本。
        sql: 已验证 SQL。
        score: 相似度分数。
        domain: 所属域。
        tags: 标签。
    """

    query_id: str
    question: str
    sql: str
    score: float
    domain: str = ""
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_candidate(cls, c: Candidate) -> "VerifiedQuerySearchResult":
        return cls(
            query_id=c.doc_id.removeprefix("verified_query:"),
            question=c.payload.get("question", ""),
            sql=c.payload.get("sql", ""),
            score=c.score,
            domain=c.domain,
            tags=c.payload.get("tags") or [],
        )

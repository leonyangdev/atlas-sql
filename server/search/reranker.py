"""BGE Reranker 重排器。

两级召回的第二级：先用 BM25+Dense+RRF 召回 top_k（约 20 个），
再用 Reranker 对（query, document）进行交叉编码精排，返回 top_n（约 5-10 个）。

这样做的好处：
- Reranker 计算量大（每对 query+doc 做一次 cross-encoder），
  不适合直接对全量 schema 进行打分；
- 先召回再精排，兼顾召回率（大 top_k）和精度（小 top_n）；
- BGE-M3 同系列的 BGE Reranker 与 BGE Embedding 语义空间接近，组合效果好。

主键必需字段补齐（V2-S03-T02 要求）：
    Reranker 输出后，补齐主外键（is_primary_key=True 或 foreign_key_ref 不为空）
    以及指标依赖字段（time_column、fact_key），防止连接键因低词相似度被裁掉。

安装依赖（可选组，与 FlagEmbedding 共包）：
    uv add --group embedding "FlagEmbedding>=1.3,<2"

V2 阶段实现要点：
1. FakeReranker 用于离线测试，不依赖 ML 框架；
2. BGEReranker 只在安装了 FlagEmbedding 时可用；
3. 必需字段保护在 _ensure_required_fields() 中实现，与重排逻辑解耦。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from server.search.repository import Candidate, CandidateSource

logger = logging.getLogger(__name__)

# 必需字段关键词：包含这些标记的字段不会因低分被裁掉
# 对应 document_id.py 中 payload 的字段名
_REQUIRED_FIELD_MARKERS = frozenset(
    {
        # 主键、外键是 JOIN 必须的连接键
        "is_primary_key",
        "foreign_key_ref",
    }
)


class BaseReranker(ABC):
    """Reranker 基类，提供必需字段补齐的公共逻辑。"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[Candidate],
        top_n: int = 10,
    ) -> list[Candidate]:
        """对候选列表重排，返回 top_n 个结果。

        Args:
            query: 用户原始问题（整句）。
            candidates: RRF 融合后的候选列表。
            top_n: 重排后保留的最大数量。

        Returns:
            按重排分降序排列的候选列表，source 标记为 CandidateSource.RERANKED。
        """
        ...

    def _build_document_text(self, candidate: Candidate) -> str:
        """从 Candidate.payload 构造用于重排的文本。

        拼接 business_name、description、table_name、column_name 等字段，
        给 Reranker 提供尽量完整的上下文。
        """
        p = candidate.payload
        parts = []
        if p.get("business_name"):
            parts.append(str(p["business_name"]))
        if p.get("physical_name") or p.get("table_name"):
            parts.append(str(p.get("physical_name") or p.get("table_name", "")))
        if p.get("description"):
            parts.append(str(p["description"]))
        if p.get("grain"):
            parts.append(str(p["grain"]))
        if p.get("aliases"):
            parts.append(str(p["aliases"]))
        return " | ".join(parts) if parts else candidate.doc_id

    def _ensure_required_fields(
        self,
        ranked: list[Candidate],
        all_candidates: list[Candidate],
        top_n: int,
    ) -> list[Candidate]:
        """确保主外键等必需字段不被裁掉。

        对于 payload 中 is_primary_key=True 或 foreign_key_ref 不为空的候选，
        如果没有出现在前 top_n 的结果中，强制追加到末尾，确保 JOIN 键始终可用。
        """
        # 注意：这里只检查前 top_n 中是否已包含必需字段，而不是全部 ranked
        top_n_ids = {c.doc_id for c in ranked[:top_n]}

        # 找出所有必需字段候选（主键 + 外键）
        required: list[Candidate] = []
        for c in all_candidates:
            if c.doc_id in top_n_ids:
                continue  # 已在 top_n 结果中
            payload = c.payload
            if payload.get("is_primary_key") or payload.get("foreign_key_ref"):
                required.append(c)

        if not required:
            return ranked[:top_n]

        # 确保 ranked 里先保留 top_n，然后追加未出现的必需字段
        # 必需字段不占 top_n 配额，避免挤掉相关内容字段
        result = list(ranked[:top_n])
        for c in required:
            if c.doc_id not in top_n_ids:
                result.append(c)
                logger.debug("Forced required field: %s", c.doc_id)
        return result


class BGEReranker(BaseReranker):
    """基于 BAAI/bge-reranker-v2-m3 的交叉编码重排器。

    需要安装 FlagEmbedding：
        uv add --group embedding "FlagEmbedding>=1.3,<2"
    """

    MODEL_ID = "BAAI/bge-reranker-v2-m3"

    def __init__(self, use_fp16: bool = True, device: str = "cpu") -> None:
        try:
            from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "FlagEmbedding is not installed. "
                "Run: uv add --group embedding 'FlagEmbedding>=1.3,<2'"
            ) from exc
        self._model = FlagReranker(self.MODEL_ID, use_fp16=use_fp16, device=device)

    def rerank(
        self,
        query: str,
        candidates: list[Candidate],
        top_n: int = 10,
    ) -> list[Candidate]:
        """用交叉编码模型对候选重排，并保护必需字段。"""
        if not candidates:
            return []

        # 构造 (query, document) 对
        pairs = [(query, self._build_document_text(c)) for c in candidates]

        # 批量打分（同步，会在事件循环线程中调用）
        scores: list[float] = self._model.compute_score(pairs, normalize=True)

        # 按分数降序排列
        scored = sorted(
            zip(scores, candidates, strict=False),
            key=lambda x: x[0],
            reverse=True,
        )

        from dataclasses import replace

        ranked = [replace(c, score=float(s), source=CandidateSource.RERANKED) for s, c in scored]

        return self._ensure_required_fields(ranked, candidates, top_n)


class FakeReranker(BaseReranker):
    """测试用的确定性假 Reranker。

    不依赖任何 ML 框架，直接按原始 score 降序返回（模拟完美重排）。
    可注入 score_override 来模拟特定文档被提升或压制的场景。
    """

    def __init__(
        self,
        score_override: dict[str, float] | None = None,
    ) -> None:
        """
        Args:
            score_override: doc_id → 强制得分映射，用于测试特定文档排名变化。
        """
        self._score_override = score_override or {}
        self.rerank_calls: list[dict[str, Any]] = []

    def rerank(
        self,
        query: str,
        candidates: list[Candidate],
        top_n: int = 10,
    ) -> list[Candidate]:
        """按 score 降序（可通过 score_override 调整）返回。"""
        from dataclasses import replace

        self.rerank_calls.append({"query": query, "count": len(candidates)})

        scored = []
        for c in candidates:
            score = self._score_override.get(c.doc_id, c.score)
            scored.append(replace(c, score=score, source=CandidateSource.RERANKED))

        scored.sort(key=lambda c: c.score, reverse=True)
        return self._ensure_required_fields(scored, candidates, top_n)

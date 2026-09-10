"""RRF（Reciprocal Rank Fusion）融合算法实现。

RRF 是一种无参数的排名融合方法，只依赖各路的排名而不依赖原始分数。
这样可以避免 BM25 分和向量内积分的量纲不统一问题。

公式：RRF(d) = Σ_r 1 / (k + rank_r(d))

其中：
    - r 是每一路检索（BM25、Dense）
    - rank_r(d) 是文档 d 在第 r 路中的排名（从 1 开始）
    - k 是平滑常数，通常取 60；较大的 k 减少高排名文档的绝对优势

设计选择：
    - 以 doc_id 作为去重键，同一对象跨两路只保留一次；
    - 某路不包含某文档时，rank 记为 None，不贡献分数，但不影响出现在另一路的文档；
    - 保存每路排名（bm25_rank、dense_rank），供消融实验和调试使用；
    - top_k 控制最终返回数量，避免上下文膨胀。

学习实验（任务 V2-S03-T03 要求）：
    分别设置 bm25_only=True 或 dense_only=True 来模拟单路配置，
    比较编码题（如 "SKU000392"）和语义改写题（如 "苹果手机"）的召回差异。
"""

from __future__ import annotations

from dataclasses import replace

from server.search.repository import Candidate, CandidateSource


class RRFFusion:
    """RRF 融合器：将 BM25 和 Dense 两路候选合并为统一排名列表。

    Args:
        k: RRF 平滑常数，默认 60（学术论文推荐值）。
        bm25_only: 消融实验模式：只使用 BM25 路（dense 路被忽略）。
        dense_only: 消融实验模式：只使用 Dense 路（BM25 路被忽略）。
    """

    def __init__(
        self,
        k: int = 60,
        bm25_only: bool = False,
        dense_only: bool = False,
    ) -> None:
        if k <= 0:
            raise ValueError(f"RRF constant k must be positive, got {k}")
        self._k = k
        self._bm25_only = bm25_only
        self._dense_only = dense_only

    @property
    def k(self) -> int:
        """RRF 平滑常数，供日志记录使用。"""
        return self._k

    def fuse(
        self,
        bm25_candidates: list[Candidate],
        dense_candidates: list[Candidate],
        top_k: int = 20,
    ) -> list[Candidate]:
        """融合两路候选，返回 RRF 排序后的 top_k 结果。

        Args:
            bm25_candidates: BM25 路的候选列表，已按原始分数降序排列。
            dense_candidates: Dense 路的候选列表，已按向量内积降序排列。
            top_k: 最终返回的最大候选数。

        Returns:
            按 RRF 分降序排列的候选列表，source 标记为 CandidateSource.RRF。
        """
        # 消融实验：单路模式
        if self._bm25_only:
            return _tag_and_slice(bm25_candidates, CandidateSource.RRF, top_k)
        if self._dense_only:
            return _tag_and_slice(dense_candidates, CandidateSource.RRF, top_k)

        # 建立 doc_id → 排名的映射（排名从 1 开始）
        bm25_ranks: dict[str, int] = {c.doc_id: i + 1 for i, c in enumerate(bm25_candidates)}
        dense_ranks: dict[str, int] = {c.doc_id: i + 1 for i, c in enumerate(dense_candidates)}

        # 收集所有唯一 doc_id，保留原始 Candidate 对象
        # 优先取 BM25 候选，再补入 Dense 独有的候选
        all_candidates: dict[str, Candidate] = {}
        for c in bm25_candidates:
            all_candidates[c.doc_id] = c
        for c in dense_candidates:
            if c.doc_id not in all_candidates:
                all_candidates[c.doc_id] = c

        # 计算每个文档的 RRF 分
        scored: list[tuple[float, str]] = []
        for doc_id in all_candidates:
            rrf_score = 0.0
            bm25_rank = bm25_ranks.get(doc_id)
            dense_rank = dense_ranks.get(doc_id)
            if bm25_rank is not None:
                rrf_score += 1.0 / (self._k + bm25_rank)
            if dense_rank is not None:
                rrf_score += 1.0 / (self._k + dense_rank)
            scored.append((rrf_score, doc_id))

        # 按 RRF 分降序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 构造最终结果，保存每路排名供消融分析
        results: list[Candidate] = []
        for rrf_score, doc_id in scored[:top_k]:
            original = all_candidates[doc_id]
            fused = replace(
                original,
                score=rrf_score,
                source=CandidateSource.RRF,
                bm25_rank=bm25_ranks.get(doc_id),
                dense_rank=dense_ranks.get(doc_id),
            )
            results.append(fused)

        return results


def _tag_and_slice(
    candidates: list[Candidate],
    source: CandidateSource,
    top_k: int,
) -> list[Candidate]:
    """将候选的 source 字段替换为目标 source，截取 top_k。"""
    return [replace(c, source=source) for c in candidates[:top_k]]

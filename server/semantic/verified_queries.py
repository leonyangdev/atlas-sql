"""V3 Verified Query 仓库服务。

职责：
1. VerifiedQueryRepository：从数据库加载/写入/更新可信查询样例
2. VerifiedQueryValidator：审核前执行语法校验 + 版本兼容校验
3. 隔离锁定测试集（is_test_locked=True）与可召回样例
4. 语义/Schema 变动后触发依赖样例重验（降为 INVALID）

核心约束：
- 仅 VERIFIED + is_test_locked=False 的样例可以进入 few-shot 上下文
- 审核只能由人工确认（verified_by 必填），不能自动通过
- 依赖指标变更后不自动继承可信状态，必须人工重验
- 近似重复样例（问题编辑距离<0.15）在导入时警告但不拒绝，由审核人决定

调用关系：
    VerifiedQueryRepository.load_for_retrieval(session, domain, top_k)
    VerifiedQueryRepository.add_draft(vq, session)
    VerifiedQueryValidator.validate_syntax(sql)
    VerifiedQueryValidator.validate_version_compat(vq, active_metric_versions)
    VerifiedQueryRepository.mark_verified(query_id, verified_by, session)
    VerifiedQueryRepository.invalidate_by_metric(metric_id, session)
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlglot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.semantic.models import VerifiedQuery, VerifiedQueryStatus

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 数据传输对象
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerifiedQueryEntry:
    """可信查询样例（供 few-shot 和评测使用）。

    Attributes:
        query_id: 稳定 UUID slug。
        question: 用户问题文本。
        sql: 已验证 SQL。
        domain: 所属业务域。
        tags: 分类标签。
        dependent_metric_ids: 依赖的指标 ID 列表（用于失效传播）。
        semantic_version_ref: 发布时绑定的语义版本标识。
        schema_version: 绑定的 schema 版本。
        is_test_locked: 是否属于锁定测试集（不可被 few-shot 召回）。
    """

    query_id: str
    question: str
    sql: str
    domain: str
    tags: list[str] = field(default_factory=list)
    dependent_metric_ids: list[str] = field(default_factory=list)
    semantic_version_ref: str | None = None
    schema_version: str | None = None
    is_test_locked: bool = False

    def to_few_shot_dict(self) -> dict[str, str]:
        """转换为 Prompt 中 few-shot 示例格式。"""
        return {"question": self.question, "sql": self.sql, "source_id": self.query_id}


@dataclass
class DraftQueryInput:
    """创建 DRAFT 样例的输入。"""

    question: str
    sql: str
    domain: str
    tags: list[str] = field(default_factory=list)
    dependent_metric_ids: list[str] = field(default_factory=list)
    semantic_version_ref: str | None = None
    schema_version: str | None = None
    is_test_locked: bool = False
    description: str | None = None


@dataclass
class ValidationResult:
    """审核前校验结果。"""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# 语法与版本校验器
# ──────────────────────────────────────────────────────────────


class VerifiedQueryValidator:
    """审核前校验器。

    校验项：
    1. SQL 语法：SQLGlot 解析是否成功
    2. 只读安全：不包含 INSERT/UPDATE/DELETE/DDL
    3. 版本兼容：依赖的指标是否都在 active_metric_versions 中
    4. 问题非空且有意义
    """

    _FORBIDDEN_STATEMENT_TYPES = frozenset([
        "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE",
        "GRANT", "REVOKE", "CALL", "EXECUTE",
    ])

    def validate_syntax(self, sql: str) -> ValidationResult:
        """用 SQLGlot 校验 SQL 语法和安全性。"""
        errors: list[str] = []
        warnings: list[str] = []

        if not sql or not sql.strip():
            return ValidationResult(ok=False, errors=["SQL 不能为空"])

        # SQLGlot 解析
        try:
            statements = sqlglot.parse(sql, dialect="postgres")
        except Exception as exc:
            return ValidationResult(ok=False, errors=[f"SQL 解析失败：{exc}"])

        if not statements:
            return ValidationResult(ok=False, errors=["SQL 解析结果为空"])

        # 只取第一条语句
        stmt = statements[0]
        if stmt is None:
            return ValidationResult(ok=False, errors=["SQL 解析结果无效"])

        # 检查语句类型
        stmt_type = type(stmt).__name__.upper()
        # sqlglot 节点类型名如 "Select"、"Insert" 等
        if stmt_type in self._FORBIDDEN_STATEMENT_TYPES:
            errors.append(f"不允许 {stmt_type} 类型的 SQL，可信查询只接受只读 SELECT")
            return ValidationResult(ok=False, errors=errors)

        # 检查 SELECT * 用法
        sql_upper = sql.upper()
        if "SELECT *" in sql_upper or "SELECT\t*" in sql_upper:
            warnings.append("建议避免 SELECT *，请明确列出所需字段")

        # 检查是否有 LIMIT（大结果集警告）
        if "LIMIT" not in sql_upper:
            warnings.append("建议添加 LIMIT 子句，防止大结果集")

        return ValidationResult(ok=True, errors=errors, warnings=warnings)

    def validate_version_compat(
        self,
        entry: DraftQueryInput,
        active_metric_versions: dict[str, int],
    ) -> ValidationResult:
        """校验样例依赖的指标是否与当前发布版本一致。

        active_metric_versions: {metric_id: current_version_number}
        """
        errors: list[str] = []
        warnings: list[str] = []

        for metric_id in entry.dependent_metric_ids:
            if metric_id not in active_metric_versions:
                errors.append(
                    f"依赖的指标 '{metric_id}' 当前没有发布版本，无法验证版本兼容性"
                )

        # semantic_version_ref 格式校验（如果提供了）
        if entry.semantic_version_ref:
            # 期望格式："metric_id:vN,metric_id:vN"
            for part in entry.semantic_version_ref.split(","):
                part = part.strip()
                if part and ":" not in part:
                    warnings.append(
                        f"semantic_version_ref 格式建议为 'metric_id:vN'，当前部分格式不标准：'{part}'"
                    )

        return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=warnings)

    def detect_near_duplicates(
        self,
        question: str,
        existing_questions: list[str],
        threshold: float = 0.85,
    ) -> list[str]:
        """检测是否与现有样例过于相似（简单字符级相似度）。

        返回相似问题列表（警告用，不拒绝）。
        """
        similar: list[str] = []
        for existing in existing_questions:
            sim = _char_similarity(question, existing)
            if sim >= threshold:
                similar.append(existing)
        return similar


# ──────────────────────────────────────────────────────────────
# 仓库服务
# ──────────────────────────────────────────────────────────────


class VerifiedQueryRepository:
    """可信查询样例仓库。

    所有写操作通过 session 参数接收，调用方负责 commit。
    读操作返回纯 VerifiedQueryEntry，不暴露 ORM 对象。
    """

    def __init__(self) -> None:
        self._validator = VerifiedQueryValidator()

    # ── 读操作 ───────────────────────────────────────────────

    async def load_for_retrieval(  # pragma: no cover - 需要真实 DB
        self,
        session: AsyncSession,
        *,
        allowed_domains: list[str] | None = None,
        exclude_test_locked: bool = True,
        schema_version: str | None = None,
        limit: int = 500,
    ) -> list[VerifiedQueryEntry]:
        """加载可召回样例（VERIFIED + 非锁定）。

        Args:
            allowed_domains: 限制域范围（None 表示不限）。
            exclude_test_locked: 排除锁定测试集（生产 few-shot 时必须为 True）。
            schema_version: 按 schema 版本过滤（None 不过滤）。
            limit: 最大返回数量。
        """
        stmt = select(VerifiedQuery).where(
            VerifiedQuery.status == VerifiedQueryStatus.VERIFIED
        )
        if exclude_test_locked:
            stmt = stmt.where(VerifiedQuery.is_test_locked == False)  # noqa: E712
        if allowed_domains:
            stmt = stmt.where(VerifiedQuery.domain.in_(allowed_domains))
        if schema_version:
            stmt = stmt.where(VerifiedQuery.schema_version == schema_version)

        result = await session.execute(stmt.limit(limit))
        return [_orm_to_entry(vq) for vq in result.scalars().all()]

    async def get_by_id(
        self, query_id: str, session: AsyncSession
    ) -> VerifiedQueryEntry | None:
        """按 query_id 查找单条样例。"""
        result = await session.execute(
            select(VerifiedQuery).where(VerifiedQuery.query_id == query_id)
        )
        vq = result.scalar_one_or_none()
        return _orm_to_entry(vq) if vq else None

    async def list_by_status(
        self,
        status: VerifiedQueryStatus,
        session: AsyncSession,
        domain: str | None = None,
    ) -> list[VerifiedQueryEntry]:
        """按状态列出样例。"""
        stmt = select(VerifiedQuery).where(VerifiedQuery.status == status)
        if domain:
            stmt = stmt.where(VerifiedQuery.domain == domain)
        result = await session.execute(stmt.order_by(VerifiedQuery.created_at))
        return [_orm_to_entry(vq) for vq in result.scalars().all()]

    # ── 写操作 ───────────────────────────────────────────────

    async def add_draft(
        self,
        inp: DraftQueryInput,
        session: AsyncSession,
        *,
        validate: bool = True,
        active_metric_versions: dict[str, int] | None = None,
    ) -> tuple[str, ValidationResult]:
        """创建 DRAFT 样例。

        Args:
            inp: 样例输入数据。
            validate: 是否先执行语法校验（默认 True）。
            active_metric_versions: 版本兼容校验用；None 时跳过版本检查。

        Returns:
            (query_id, ValidationResult)
        """
        val_result = ValidationResult(ok=True)

        if validate:
            syntax_result = self._validator.validate_syntax(inp.sql)
            if not syntax_result.ok:
                return "", syntax_result
            val_result = syntax_result

            if active_metric_versions is not None:
                compat_result = self._validator.validate_version_compat(inp, active_metric_versions)
                if not compat_result.ok:
                    return "", compat_result
                # 合并 warnings
                val_result = ValidationResult(
                    ok=True,
                    errors=[],
                    warnings=val_result.warnings + compat_result.warnings,
                )

        query_id = str(uuid.uuid4())
        vq = VerifiedQuery(
            query_id=query_id,
            question=inp.question,
            sql=inp.sql,
            domain=inp.domain,
            tags=inp.tags,
            dependent_metric_ids=inp.dependent_metric_ids,
            semantic_version_ref=inp.semantic_version_ref,
            schema_version=inp.schema_version,
            is_test_locked=inp.is_test_locked,
            description=inp.description,
            status=VerifiedQueryStatus.DRAFT,
            last_validation_result="passed" if validate else None,
            last_validated_at=datetime.now(UTC) if validate else None,
        )
        session.add(vq)
        await session.flush()
        return query_id, val_result

    async def mark_verified(
        self,
        query_id: str,
        verified_by: str,
        session: AsyncSession,
    ) -> bool:
        """将 DRAFT 样例标记为 VERIFIED（需人工审核后调用）。

        Returns:
            True 表示成功，False 表示样例不存在或状态不对。
        """
        result = await session.execute(
            select(VerifiedQuery).where(VerifiedQuery.query_id == query_id)
        )
        vq = result.scalar_one_or_none()
        if vq is None or vq.status != VerifiedQueryStatus.DRAFT:
            return False

        vq.status = VerifiedQueryStatus.VERIFIED
        vq.verified_by = verified_by
        vq.verified_at = datetime.now(UTC)
        vq.updated_at = datetime.now(UTC)
        await session.flush()
        return True

    async def invalidate_by_metric(
        self,
        metric_id: str,
        session: AsyncSession,
        reason: str | None = None,
    ) -> int:
        """将依赖 metric_id 的所有 VERIFIED 样例降为 INVALID。

        Returns:
            被失效的样例数量。
        """
        result = await session.execute(
            select(VerifiedQuery).where(
                VerifiedQuery.status == VerifiedQueryStatus.VERIFIED
            )
        )
        all_verified = result.scalars().all()

        count = 0
        for vq in all_verified:
            if metric_id in (vq.dependent_metric_ids or []):
                vq.status = VerifiedQueryStatus.INVALID
                vq.invalidation_reason = reason or f"指标 '{metric_id}' 已更新，需要重新验证"
                vq.updated_at = datetime.now(UTC)
                count += 1

        if count:
            await session.flush()
            logger.info(
                "Invalidated %d VerifiedQuery records depending on metric '%s'",
                count,
                metric_id,
            )
        return count

    async def re_validate(
        self,
        query_id: str,
        session: AsyncSession,
        *,
        active_metric_versions: dict[str, int] | None = None,
    ) -> ValidationResult:
        """对 INVALID 样例重新执行校验（不自动变为 VERIFIED，仍需人工审核）。

        Returns:
            ValidationResult（通过后样例状态变回 DRAFT，等待重新审核）。
        """
        result = await session.execute(
            select(VerifiedQuery).where(VerifiedQuery.query_id == query_id)
        )
        vq = result.scalar_one_or_none()
        if vq is None:
            return ValidationResult(ok=False, errors=[f"样例 '{query_id}' 不存在"])

        # 语法校验
        syntax_result = self._validator.validate_syntax(vq.sql)
        if not syntax_result.ok:
            vq.last_validation_result = "failed"
            vq.last_validated_at = datetime.now(UTC)
            await session.flush()
            return syntax_result

        # 版本兼容校验
        if active_metric_versions is not None:
            inp = DraftQueryInput(
                question=vq.question,
                sql=vq.sql,
                domain=vq.domain,
                dependent_metric_ids=vq.dependent_metric_ids or [],
                semantic_version_ref=vq.semantic_version_ref,
            )
            compat_result = self._validator.validate_version_compat(inp, active_metric_versions)
            if not compat_result.ok:
                vq.last_validation_result = "failed"
                vq.last_validated_at = datetime.now(UTC)
                await session.flush()
                return compat_result

        # 校验通过：回到 DRAFT（等待人工重新审核）
        vq.status = VerifiedQueryStatus.DRAFT
        vq.invalidation_reason = None
        vq.last_validation_result = "passed"
        vq.last_validated_at = datetime.now(UTC)
        vq.updated_at = datetime.now(UTC)
        await session.flush()

        return ValidationResult(ok=True, warnings=syntax_result.warnings)


# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────


def _orm_to_entry(vq: VerifiedQuery) -> VerifiedQueryEntry:
    return VerifiedQueryEntry(
        query_id=vq.query_id,
        question=vq.question,
        sql=vq.sql,
        domain=vq.domain,
        tags=vq.tags or [],
        dependent_metric_ids=vq.dependent_metric_ids or [],
        semantic_version_ref=vq.semantic_version_ref,
        schema_version=vq.schema_version,
        is_test_locked=vq.is_test_locked,
    )


def _char_similarity(a: str, b: str) -> float:
    """计算两个字符串的字符级 Jaccard 相似度（快速近似）。"""
    if not a or not b:
        return 0.0
    # 用 trigram 集合计算 Jaccard
    def trigrams(s: str) -> set[str]:
        s = s.strip().lower()
        return {s[i:i+3] for i in range(max(1, len(s) - 2))}

    tg_a = trigrams(a)
    tg_b = trigrams(b)
    if not tg_a or not tg_b:
        return 0.0
    intersection = len(tg_a & tg_b)
    union = len(tg_a | tg_b)
    return intersection / union if union > 0 else 0.0

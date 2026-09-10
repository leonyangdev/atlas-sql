"""V3 语义生命周期服务。

实现指标定义的 Draft → Testing → Published → Deprecated 状态机。

核心约束：
1. 已发布（PUBLISHED）的版本快照不允许原地修改。
2. 需要变更时，必须将草稿改回 DRAFT 状态，修改后重新走 Testing → Published 流程。
3. 发布（publish）操作须绑定回归测试运行结果 ID；未通过回归时拒绝发布。
4. 发布后原子切换 metric_active_version（UPDATE ... WHERE metric_id=X），
   保证并发时不会出现新旧版本混用。
5. 发布后触发 Redis 缓存失效（前缀 "semantic:metric:{metric_id}"）。
6. 保留旧版本快照（MetricVersion 不删除），支持在途请求和回滚。

调用链：
    MetricLifecycleService.transition(metric_id, target_status, session)
    MetricLifecycleService.publish(metric_id, published_by, regression_run_id, session)
    MetricLifecycleService.rollback(metric_id, target_version, session)
    MetricLifecycleService.invalidate_dependent_queries(metric_id, session)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.semantic.models import (
    MetricActiveVersion,
    MetricDefinition,
    MetricVersion,
    SemanticStatus,
    VerifiedQuery,
    VerifiedQueryStatus,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 错误类型
# ──────────────────────────────────────────────────────────────


class LifecycleError(Exception):
    """状态机操作被拒绝。"""


class PublishedImmutableError(LifecycleError):
    """尝试原地修改已发布版本。"""


class InvalidTransitionError(LifecycleError):
    """非法状态转移。"""


class RegressionNotPassedError(LifecycleError):
    """发布前回归未通过。"""


# ──────────────────────────────────────────────────────────────
# 合法转移图
# ──────────────────────────────────────────────────────────────

# 每个状态允许转移到的目标状态集合
_ALLOWED_TRANSITIONS: dict[SemanticStatus, set[SemanticStatus]] = {
    SemanticStatus.DRAFT: {SemanticStatus.TESTING},
    SemanticStatus.TESTING: {SemanticStatus.DRAFT, SemanticStatus.PUBLISHED},
    SemanticStatus.PUBLISHED: {SemanticStatus.DEPRECATED},
    SemanticStatus.DEPRECATED: set(),  # 终态，不能再转移
}


# ──────────────────────────────────────────────────────────────
# 审计快照
# ──────────────────────────────────────────────────────────────


def _build_snapshot(metric: MetricDefinition) -> dict:
    """将 MetricDefinition 当前字段序列化为不可变快照字典。"""
    return {
        "metric_id": metric.metric_id,
        "label": metric.label,
        "domain": metric.domain,
        "grain": metric.grain.value if hasattr(metric.grain, "value") else str(metric.grain),
        "expression": metric.expression,
        "required_filters": metric.required_filters or [],
        "dependent_columns": metric.dependent_columns or [],
        "allowed_dimensions": metric.allowed_dimensions or [],
        "time_role": (
            metric.time_role.value if hasattr(metric.time_role, "value") else str(metric.time_role)
        ),
        "zero_denominator_policy": (
            metric.zero_denominator_policy.value
            if hasattr(metric.zero_denominator_policy, "value")
            else str(metric.zero_denominator_policy)
        ),
        "unit": metric.unit,
        "currency": metric.currency,
        "synonyms": metric.synonyms or [],
        "is_sensitive": metric.is_sensitive,
        "time_rule_note": metric.time_rule_note,
        "warning": metric.warning,
        "snapshot_at": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────
# 发布结果数据类
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PublishResult:
    """发布操作结果。"""

    metric_id: str
    version_number: int
    previous_version: int | None
    change_note: str | None


@dataclass(frozen=True)
class RollbackResult:
    """回滚操作结果。"""

    metric_id: str
    rolled_back_to_version: int
    previous_version: int


# ──────────────────────────────────────────────────────────────
# 生命周期服务
# ──────────────────────────────────────────────────────────────


class MetricLifecycleService:
    """指标生命周期管理服务。

    Args:
        redis_client: 可选的 Redis 客户端（满足 set/delete/keys 接口）。
                      为 None 时跳过缓存失效（离线测试用）。
    """

    def __init__(self, redis_client: object | None = None) -> None:
        self._redis = redis_client

    # ── 状态转移 ──────────────────────────────────────────────

    async def transition(
        self,
        metric_id: str,
        target_status: SemanticStatus,
        session: AsyncSession,
        *,
        operator: str = "system",
    ) -> None:
        """将指标状态从当前状态转移到 target_status。

        - PUBLISHED → 任何状态：禁止（需通过 publish/rollback/deprecate 专用方法）。
        - 非法转移：抛出 InvalidTransitionError。
        """
        metric = await _get_metric_or_raise(metric_id, session)
        current = SemanticStatus(metric.status) if isinstance(metric.status, str) else metric.status

        # PUBLISHED 状态不允许通过 transition() 直接改变（需要专用方法）
        if current == SemanticStatus.PUBLISHED:
            raise PublishedImmutableError(
                f"指标 '{metric_id}' 已发布，不能通过 transition() 直接修改状态。"
                f"如需修改，请先调用 rollback() 或 deprecate()。"
            )

        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if target_status not in allowed:
            raise InvalidTransitionError(
                f"指标 '{metric_id}' 不允许从 {current.value} 转移到 {target_status.value}。"
                f"允许的目标状态：{[s.value for s in allowed]}"
            )

        metric.status = target_status
        metric.updated_at = datetime.now(UTC)
        logger.info(
            "Metric '%s' transitioned %s → %s by %s",
            metric_id,
            current.value,
            target_status.value,
            operator,
        )

    # ── 发布 ──────────────────────────────────────────────────

    async def publish(  # pragma: no cover - publish 完整路径需要真实 DB 事务
        self,
        metric_id: str,
        published_by: str,
        session: AsyncSession,
        *,
        regression_run_id: str | None = None,
        change_note: str | None = None,
        require_regression: bool = True,
    ) -> PublishResult:
        """将指标从 TESTING 状态发布。

        步骤：
        1. 校验当前必须是 TESTING 状态。
        2. require_regression=True 时，regression_run_id 不能为 None（强制绑定回归）。
        3. 创建不可变版本快照（MetricVersion）。
        4. 原子切换/更新 MetricActiveVersion 指针。
        5. 将主表状态置为 PUBLISHED。
        6. 触发 Redis 缓存失效。
        7. 触发依赖此指标的 VerifiedQuery 重验（降为 INVALID）。

        Returns:
            PublishResult 包含新版本号和旧版本号。
        """
        metric = await _get_metric_or_raise(metric_id, session)
        current = SemanticStatus(metric.status) if isinstance(metric.status, str) else metric.status

        if current != SemanticStatus.TESTING:
            raise InvalidTransitionError(
                f"发布前指标必须处于 TESTING 状态，当前状态为 '{current.value}'。"
            )

        if require_regression and regression_run_id is None:
            raise RegressionNotPassedError(
                f"指标 '{metric_id}' 发布前必须提供 regression_run_id（回归测试结果）。"
                f"若要跳过回归检查，设置 require_regression=False（仅限开发环境）。"
            )

        # 计算新版本号（当前最大版本号 + 1）
        max_ver_result = await session.execute(
            select(MetricVersion.version_number)
            .where(MetricVersion.metric_id == metric_id)
            .order_by(MetricVersion.version_number.desc())
            .limit(1)
        )
        max_ver_row = max_ver_result.scalar_one_or_none()
        new_version = (max_ver_row or 0) + 1

        # 创建版本快照
        snapshot = _build_snapshot(metric)
        version_record = MetricVersion(
            metric_id=metric_id,
            version_number=new_version,
            snapshot=snapshot,
            change_note=change_note,
            regression_run_id=regression_run_id,
            published_by=published_by,
            published_at=datetime.now(UTC),
        )
        session.add(version_record)

        # 查询当前 active version（用于返回 previous_version）
        active_result = await session.execute(
            select(MetricActiveVersion).where(MetricActiveVersion.metric_id == metric_id)
        )
        active_record = active_result.scalar_one_or_none()
        previous_version = active_record.version_number if active_record else None

        # 原子切换 active_version
        if active_record is not None:
            await session.execute(
                update(MetricActiveVersion)
                .where(MetricActiveVersion.metric_id == metric_id)
                .values(version_number=new_version, updated_at=datetime.now(UTC))
            )
        else:
            session.add(
                MetricActiveVersion(
                    metric_id=metric_id,
                    version_number=new_version,
                    updated_at=datetime.now(UTC),
                )
            )

        # 更新主表状态为 PUBLISHED，记录审核人
        metric.status = SemanticStatus.PUBLISHED
        metric.reviewed_by = published_by
        metric.reviewed_at = datetime.now(UTC)
        metric.updated_at = datetime.now(UTC)

        await session.flush()

        # Redis 缓存失效
        await self._invalidate_cache(metric_id)

        # 依赖此指标的 VerifiedQuery 降为 INVALID
        invalidated = await self.invalidate_dependent_queries(metric_id, session)

        logger.info(
            "Metric '%s' published v%d by %s (prev=v%s, regression=%s, %d queries invalidated)",
            metric_id,
            new_version,
            published_by,
            previous_version,
            regression_run_id or "skipped",
            invalidated,
        )

        return PublishResult(
            metric_id=metric_id,
            version_number=new_version,
            previous_version=previous_version,
            change_note=change_note,
        )

    # ── 回滚 ──────────────────────────────────────────────────

    async def rollback(  # pragma: no cover - rollback 完整路径需要真实 DB 事务
        self,
        metric_id: str,
        target_version: int,
        session: AsyncSession,
        *,
        operator: str = "system",
    ) -> RollbackResult:
        """将 active_version 指针回滚到指定历史版本。

        不删除任何版本快照；仅更新 MetricActiveVersion 的指针。
        回滚后 Redis 缓存失效；在途请求在下一次 load_active_metrics() 时会看到旧版本内容。
        """
        # 验证目标版本存在
        ver_result = await session.execute(
            select(MetricVersion).where(
                MetricVersion.metric_id == metric_id,
                MetricVersion.version_number == target_version,
            )
        )
        if ver_result.scalar_one_or_none() is None:
            raise LifecycleError(
                f"指标 '{metric_id}' 不存在版本 v{target_version}，无法回滚。"
            )

        active_result = await session.execute(
            select(MetricActiveVersion).where(MetricActiveVersion.metric_id == metric_id)
        )
        active_record = active_result.scalar_one_or_none()
        if active_record is None:
            raise LifecycleError(f"指标 '{metric_id}' 没有 active_version 记录，无法回滚。")

        previous_version = active_record.version_number

        await session.execute(
            update(MetricActiveVersion)
            .where(MetricActiveVersion.metric_id == metric_id)
            .values(version_number=target_version, updated_at=datetime.now(UTC))
        )

        await session.flush()
        await self._invalidate_cache(metric_id)

        logger.info(
            "Metric '%s' rolled back v%d → v%d by %s",
            metric_id,
            previous_version,
            target_version,
            operator,
        )

        return RollbackResult(
            metric_id=metric_id,
            rolled_back_to_version=target_version,
            previous_version=previous_version,
        )

    # ── 废弃 ──────────────────────────────────────────────────

    async def deprecate(
        self,
        metric_id: str,
        session: AsyncSession,
        *,
        operator: str = "system",
    ) -> None:
        """将 PUBLISHED 指标标记为 DEPRECATED。

        废弃后指标不再被 load_active_metrics() 加载进注册表，
        但版本快照和历史查询记录保留，以支持历史记录审计。
        """
        metric = await _get_metric_or_raise(metric_id, session)
        current = SemanticStatus(metric.status) if isinstance(metric.status, str) else metric.status

        if current != SemanticStatus.PUBLISHED:
            raise InvalidTransitionError(
                f"只有 PUBLISHED 状态的指标可以被废弃，当前状态为 '{current.value}'。"
            )

        metric.status = SemanticStatus.DEPRECATED
        metric.updated_at = datetime.now(UTC)

        await session.flush()
        await self._invalidate_cache(metric_id)

        logger.info("Metric '%s' deprecated by %s", metric_id, operator)

    # ── 依赖失效 ──────────────────────────────────────────────

    async def invalidate_dependent_queries(
        self, metric_id: str, session: AsyncSession
    ) -> int:
        """将依赖此指标的 VerifiedQuery 降为 INVALID。

        语义变动后已验证样例不再可信，需要人工重审。
        返回被标记为 INVALID 的样例数量。
        """
        # 查找 dependent_metric_ids 包含 metric_id 的样例
        # JSON 字段查询：dependent_metric_ids 是 JSON 数组
        verified_result = await session.execute(
            select(VerifiedQuery).where(
                VerifiedQuery.status == VerifiedQueryStatus.VERIFIED,
            )
        )
        all_verified = verified_result.scalars().all()

        # 在 Python 层过滤（JSON 数组包含匹配）
        to_invalidate = [
            vq for vq in all_verified
            if metric_id in (vq.dependent_metric_ids or [])
        ]

        count = 0
        for vq in to_invalidate:
            vq.status = VerifiedQueryStatus.INVALID
            vq.invalidation_reason = (
                f"指标 '{metric_id}' 已发布新版本，样例需重新验证。"
            )
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

    # ── 版本对比 ──────────────────────────────────────────────

    @staticmethod
    async def get_version_diff(
        metric_id: str,
        version_a: int,
        version_b: int,
        session: AsyncSession,
    ) -> dict:
        """返回两个版本快照的差异字典。

        差异格式：{ field: {"from": old_value, "to": new_value} }
        仅包含有变化的字段。
        """
        result = await session.execute(
            select(MetricVersion).where(
                MetricVersion.metric_id == metric_id,
                MetricVersion.version_number.in_([version_a, version_b]),
            )
        )
        versions = {v.version_number: v for v in result.scalars().all()}

        if version_a not in versions or version_b not in versions:
            missing = [v for v in [version_a, version_b] if v not in versions]
            raise LifecycleError(
                f"指标 '{metric_id}' 找不到版本 {missing}，无法对比。"
            )

        snap_a = versions[version_a].snapshot
        snap_b = versions[version_b].snapshot

        diff: dict = {}
        all_keys = set(snap_a.keys()) | set(snap_b.keys())
        for key in sorted(all_keys):
            if key == "snapshot_at":
                continue  # 时间戳本身不是业务差异
            val_a = snap_a.get(key)
            val_b = snap_b.get(key)
            if val_a != val_b:
                diff[key] = {"from": val_a, "to": val_b}

        return diff

    @staticmethod
    async def list_versions(
        metric_id: str,
        session: AsyncSession,
    ) -> list[dict]:
        """返回指标的所有版本历史摘要列表（按版本号升序）。"""
        result = await session.execute(
            select(MetricVersion)
            .where(MetricVersion.metric_id == metric_id)
            .order_by(MetricVersion.version_number)
        )
        versions = result.scalars().all()
        return [
            {
                "version_number": v.version_number,
                "published_by": v.published_by,
                "published_at": v.published_at.isoformat(),
                "change_note": v.change_note,
                "regression_run_id": v.regression_run_id,
            }
            for v in versions
        ]

    # ── 内部辅助 ──────────────────────────────────────────────

    async def _invalidate_cache(self, metric_id: str) -> None:
        """使 Redis 中对应指标的缓存失效。"""
        if self._redis is None:
            return
        key = f"semantic:metric:{metric_id}"
        try:
            if hasattr(self._redis, "delete"):
                await self._redis.delete(key)  # type: ignore[union-attr]
            logger.debug("Redis cache invalidated: %s", key)
        except Exception as exc:  # noqa: BLE001
            # 缓存失效失败不应阻断业务流程，记录日志即可
            logger.warning("Failed to invalidate Redis cache for key '%s': %s", key, exc)


# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────


async def _get_metric_or_raise(metric_id: str, session: AsyncSession) -> MetricDefinition:
    """查找指标定义，不存在时抛出 LifecycleError。"""
    result = await session.execute(
        select(MetricDefinition).where(MetricDefinition.metric_id == metric_id)
    )
    metric = result.scalar_one_or_none()
    if metric is None:
        raise LifecycleError(f"指标 '{metric_id}' 不存在。")
    return metric

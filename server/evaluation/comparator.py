"""查询结果比较器。

比较规则（与 benchmarks/v1/README.md 一致）：
- 无序查询：多重集比较，行顺序不影响结果，但重复行数量必须一致。
- 有序查询（is_ordered=True）：按行序列精确比较。
- 金额（Decimal）：精确比较，不使用浮点容差。
- NULL：NULL == NULL 为 True（SQL 语义是 NULL != NULL，但比较结果时需要感知 NULL）。
- 空结果：Gold 返回 0 行时，模型输出也必须是 0 行。
- 拒绝题/澄清题：不执行 SQL，检查 expected_action 是否匹配。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class CompareResult:
    """单题比较结果。"""

    question_id: str
    matched: bool
    # 说明不匹配的原因，matched=True 时为空
    reason: str = ""
    # 结果行数
    gold_rows: int = 0
    predicted_rows: int = 0


Row = tuple[Any, ...]
ResultSet = list[Row]


def normalize_value(v: object) -> object:
    """把数据库返回值规范化为可比较的 Python 类型。

    - Decimal 保持为 Decimal（精确比较）
    - None 保持为 None
    - 其他数值转为字符串，避免整数/浮点隐式转换
    - 字符串去掉首尾空白
    """
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        # 如果值可以精确表示为 Decimal（通常来自 numeric(18,2)），保留精度
        return Decimal(str(v))
    if isinstance(v, str):
        return v.strip()
    return v


def normalize_row(row: Row) -> Row:
    """规范化一行数据的全部字段。"""
    return tuple(normalize_value(v) for v in row)


def rows_to_multiset_key(rows: ResultSet) -> list[str]:
    """把结果集转为有序的行哈希列表（用于多重集比较）。

    同一行的哈希排序后比较，消除行顺序影响。
    """
    row_hashes = []
    for row in rows:
        norm = normalize_row(row)
        # 用 JSON 序列化保证确定性
        row_str = json.dumps(
            [str(v) if v is not None else None for v in norm],
            ensure_ascii=False,
            sort_keys=False,
        )
        row_hashes.append(hashlib.sha256(row_str.encode()).hexdigest())
    return sorted(row_hashes)


def compare_unordered(gold: ResultSet, predicted: ResultSet) -> tuple[bool, str]:
    """无序结果集比较（多重集语义）。"""
    if len(gold) != len(predicted):
        return False, f"row count mismatch: gold={len(gold)} predicted={len(predicted)}"

    gold_keys = rows_to_multiset_key(gold)
    pred_keys = rows_to_multiset_key(predicted)

    if gold_keys != pred_keys:
        # 找出第一个不匹配的行
        for i, (g, p) in enumerate(zip(gold_keys, pred_keys, strict=False)):
            if g != p:
                return False, f"row mismatch at sorted position {i}"
        return False, "row content mismatch"

    return True, ""


def compare_ordered(gold: ResultSet, predicted: ResultSet) -> tuple[bool, str]:
    """有序结果集比较（精确按行序比较）。"""
    if len(gold) != len(predicted):
        return False, f"row count mismatch: gold={len(gold)} predicted={len(predicted)}"

    for i, (gold_row, pred_row) in enumerate(zip(gold, predicted, strict=True)):
        norm_gold = normalize_row(gold_row)
        norm_pred = normalize_row(pred_row)
        if norm_gold != norm_pred:
            return False, f"row {i} mismatch: gold={norm_gold!r} predicted={norm_pred!r}"

    return True, ""


def compare_results(
    question_id: str,
    gold: ResultSet,
    predicted: ResultSet,
    is_ordered: bool = False,
) -> CompareResult:
    """比较 Gold 结果集和模型预测结果集。

    Args:
        question_id: 题目 ID（用于日志和报告）。
        gold: Gold SQL 执行结果。
        predicted: 模型生成 SQL 的执行结果。
        is_ordered: True 时按行序比较，False 时用多重集比较。

    Returns:
        CompareResult，matched=True 表示通过。
    """
    if is_ordered:
        matched, reason = compare_ordered(gold, predicted)
    else:
        matched, reason = compare_unordered(gold, predicted)

    return CompareResult(
        question_id=question_id,
        matched=matched,
        reason=reason,
        gold_rows=len(gold),
        predicted_rows=len(predicted),
    )


def compare_action(
    question_id: str,
    expected_action: str,
    actual_action: str,
    actual_rejection_reason: str = "",
) -> CompareResult:
    """比较拒绝/澄清类题目的行为（不执行 SQL）。

    Args:
        question_id: 题目 ID。
        expected_action: "reject" 或 "clarify"。
        actual_action: 模型返回的行为类型。
        actual_rejection_reason: 模型返回的拒绝理由（可选）。
    """
    matched = expected_action == actual_action
    reason = "" if matched else f"expected action={expected_action!r} but got {actual_action!r}"
    return CompareResult(
        question_id=question_id,
        matched=matched,
        reason=reason,
        gold_rows=0,
        predicted_rows=0,
    )


def result_checksum(rows: ResultSet) -> str:
    """计算结果集的稳定校验和，用于快速验证 Gold SQL 可重复性。

    校验和是对排序后行哈希列表的 SHA-256，与行顺序无关。
    """
    keys = rows_to_multiset_key(rows)
    return hashlib.sha256(json.dumps(keys).encode()).hexdigest()[:16]

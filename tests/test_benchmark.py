"""V0-S06 Benchmark 测试。

覆盖：
- 分割文件加载与结构校验
- 题目类型覆盖率验证
- 测试集与训练集 ID 无重叠
- 结果比较器（无序/有序/NULL 处理）
- 拒绝/澄清题的行为比较
"""

from decimal import Decimal
from pathlib import Path

from server.evaluation.benchmark_loader import load_split, verify_no_leak
from server.evaluation.comparator import (
    compare_action,
    compare_ordered,
    compare_results,
    compare_unordered,
    normalize_value,
    result_checksum,
)

BENCHMARK_DIR = Path(__file__).parent.parent / "benchmarks" / "v1"


# ---------------------------------------------------------------------------
# 分割文件加载
# ---------------------------------------------------------------------------


def test_train_split_loads_successfully() -> None:
    split = load_split(BENCHMARK_DIR / "train.yaml")
    assert split.split == "train"
    assert len(split.questions) == 60


def test_tune_split_loads_successfully() -> None:
    split = load_split(BENCHMARK_DIR / "tune.yaml")
    assert split.split == "tune"
    assert len(split.questions) == 30


def test_test_split_loads_successfully() -> None:
    split = load_split(BENCHMARK_DIR / "test.yaml")
    assert split.split == "test"
    assert len(split.questions) == 30


def test_test_split_is_locked() -> None:
    split = load_split(BENCHMARK_DIR / "test.yaml")
    assert split.is_locked is True


def test_train_split_is_not_locked() -> None:
    split = load_split(BENCHMARK_DIR / "train.yaml")
    assert split.is_locked is False


def test_question_ids_are_unique_within_split() -> None:
    for split_name in ("train", "tune", "test"):
        split = load_split(BENCHMARK_DIR / f"{split_name}.yaml")
        ids = [q.id for q in split.questions]
        assert len(ids) == len(set(ids)), f"duplicate IDs in {split_name}"


def test_all_questions_have_gold_sql_or_expected_action() -> None:
    """每道题必须有 gold_sql 或 expected_action，不能都为空。"""
    for split_name in ("train", "tune", "test"):
        split = load_split(BENCHMARK_DIR / f"{split_name}.yaml")
        for q in split.questions:
            assert (
                q.gold_sql is not None or q.expected_action is not None
            ), f"question {q.id} has neither gold_sql nor expected_action"


def test_ordered_questions_have_gold_sql() -> None:
    """is_ordered=True 的题目必须有 gold_sql（含 ORDER BY），不能是拒绝题。"""
    for split_name in ("train", "tune", "test"):
        split = load_split(BENCHMARK_DIR / f"{split_name}.yaml")
        for q in split.questions:
            if q.is_ordered:
                assert q.gold_sql is not None, f"ordered question {q.id} has no gold_sql"


def test_question_dataset_version_consistent() -> None:
    """所有题目使用相同的数据版本。"""
    for split_name in ("train", "tune", "test"):
        split = load_split(BENCHMARK_DIR / f"{split_name}.yaml")
        versions = {q.dataset_version for q in split.questions}
        assert len(versions) == 1, f"mixed dataset_version in {split_name}: {versions}"


# ---------------------------------------------------------------------------
# 覆盖率验证
# ---------------------------------------------------------------------------


def test_train_covers_required_categories() -> None:
    """训练集必须包含所有关键类型的题目。"""
    split = load_split(BENCHMARK_DIR / "train.yaml")
    categories = {q.category for q in split.questions}
    required = {
        "single_table", "join", "aggregation", "top_n",
        "time", "time_yoy", "value_mapping", "metric",
        "ambiguous", "permission_violation", "permission_row", "permission_column",
    }
    missing = required - categories
    assert not missing, f"missing categories in train: {missing}"


def test_test_covers_required_categories() -> None:
    """锁定测试集也必须覆盖所有关键类型。"""
    split = load_split(BENCHMARK_DIR / "test.yaml")
    categories = {q.category for q in split.questions}
    required = {
        "single_table", "join", "aggregation", "top_n",
        "time", "value_mapping", "metric",
        "ambiguous", "permission_violation", "permission_row", "permission_column",
    }
    missing = required - categories
    assert not missing, f"missing categories in test: {missing}"


def test_reject_questions_have_rejection_reason() -> None:
    """拒绝题应该提供 rejection_reason 或 clarification_hint。"""
    for split_name in ("train", "tune", "test"):
        split = load_split(BENCHMARK_DIR / f"{split_name}.yaml")
        for q in split.questions:
            if q.expected_action in ("reject", "clarify"):
                assert q.rejection_reason is not None or q.clarification_hint is not None, \
                    f"question {q.id}: {q.expected_action} action without reason/hint"


# ---------------------------------------------------------------------------
# 数据集泄漏检查
# ---------------------------------------------------------------------------


def test_no_id_overlap_between_train_and_test() -> None:
    train = load_split(BENCHMARK_DIR / "train.yaml")
    test = load_split(BENCHMARK_DIR / "test.yaml")
    warnings = verify_no_leak(train, test)
    assert not warnings, f"data leakage detected: {warnings}"


def test_no_id_overlap_between_tune_and_test() -> None:
    tune = load_split(BENCHMARK_DIR / "tune.yaml")
    test = load_split(BENCHMARK_DIR / "test.yaml")
    warnings = verify_no_leak(tune, test)
    assert not warnings, f"data leakage detected: {warnings}"


# ---------------------------------------------------------------------------
# 结果比较器
# ---------------------------------------------------------------------------


def test_normalize_value_none() -> None:
    assert normalize_value(None) is None


def test_normalize_value_decimal_preserved() -> None:
    d = Decimal("123.45")
    assert normalize_value(d) == d


def test_normalize_value_float_to_decimal() -> None:
    result = normalize_value(123.45)
    assert isinstance(result, Decimal)


def test_normalize_value_string_stripped() -> None:
    assert normalize_value("  hello  ") == "hello"


def test_compare_unordered_matching() -> None:
    gold = [("A", 1), ("B", 2)]
    pred = [("B", 2), ("A", 1)]  # 顺序不同但内容一致
    matched, reason = compare_unordered(gold, pred)
    assert matched is True
    assert reason == ""


def test_compare_unordered_row_count_mismatch() -> None:
    gold = [("A", 1), ("B", 2)]
    pred = [("A", 1)]
    matched, _ = compare_unordered(gold, pred)
    assert matched is False


def test_compare_unordered_content_mismatch() -> None:
    gold = [("A", 1), ("B", 2)]
    pred = [("A", 1), ("C", 3)]
    matched, reason = compare_unordered(gold, pred)
    assert matched is False
    assert reason != ""


def test_compare_unordered_with_duplicate_rows() -> None:
    """重复行数量必须完全一致（多重集语义）。"""
    gold = [("A", 1), ("A", 1), ("B", 2)]
    pred = [("A", 1), ("B", 2), ("B", 2)]  # 重复行不同
    matched, _ = compare_unordered(gold, pred)
    assert matched is False


def test_compare_ordered_matching() -> None:
    gold = [("A", 100), ("B", 50)]
    pred = [("A", 100), ("B", 50)]
    matched, _ = compare_ordered(gold, pred)
    assert matched is True


def test_compare_ordered_different_order_fails() -> None:
    """有序比较时行顺序必须完全一致。"""
    gold = [("A", 100), ("B", 50)]
    pred = [("B", 50), ("A", 100)]
    matched, reason = compare_ordered(gold, pred)
    assert matched is False
    assert "row 0 mismatch" in reason


def test_compare_results_uses_is_ordered() -> None:
    gold = [("A",), ("B",)]
    pred = [("B",), ("A",)]

    # is_ordered=False：应该通过（无序比较）
    result = compare_results("test-1", gold, pred, is_ordered=False)
    assert result.matched is True

    # is_ordered=True：应该失败（顺序不同）
    result = compare_results("test-1", gold, pred, is_ordered=True)
    assert result.matched is False


def test_compare_null_values() -> None:
    """NULL 值相等性：NULL == NULL 在比较器中视为匹配。"""
    gold = [(None, "A"), ("B", None)]
    pred = [(None, "A"), ("B", None)]
    result = compare_results("test-null", gold, pred, is_ordered=True)
    assert result.matched is True


def test_compare_null_not_equal_to_value() -> None:
    gold = [(None,)]
    pred = [("",)]  # 空字符串不等于 NULL
    result = compare_results("test-null2", gold, pred, is_ordered=True)
    assert result.matched is False


def test_compare_empty_results() -> None:
    """两个空结果集应该匹配。"""
    result = compare_results("test-empty", [], [], is_ordered=False)
    assert result.matched is True


def test_compare_action_reject_matches() -> None:
    result = compare_action("test-reject", "reject", "reject")
    assert result.matched is True


def test_compare_action_clarify_matches() -> None:
    result = compare_action("test-clarify", "clarify", "clarify")
    assert result.matched is True


def test_compare_action_mismatch() -> None:
    result = compare_action("test-action", "reject", "sql_result")
    assert result.matched is False
    assert "expected action" in result.reason


def test_result_checksum_is_stable() -> None:
    """相同内容的结果集校验和必须完全相同。"""
    rows = [("A", 1), ("B", 2)]
    assert result_checksum(rows) == result_checksum(rows)


def test_result_checksum_order_independent() -> None:
    """校验和不受行顺序影响。"""
    rows1 = [("A", 1), ("B", 2)]
    rows2 = [("B", 2), ("A", 1)]
    assert result_checksum(rows1) == result_checksum(rows2)


def test_result_checksum_different_content() -> None:
    """不同内容的结果集校验和不同。"""
    rows1 = [("A", 1)]
    rows2 = [("A", 2)]
    assert result_checksum(rows1) != result_checksum(rows2)

"""Benchmark YAML 加载与验证。

加载 train.yaml / tune.yaml / test.yaml，并对题目结构做最小校验：
- 每道题有唯一 id
- gold_sql 或 expected_action 二选一（不能同时为空）
- 锁定集（split=test）禁止在 Verified Query Repository 路径中读取

加载后的 Question 对象作为评测框架的输入数据模型，
比较工具（comparator.py）和执行脚本（scripts/run_benchmark.py）都依赖这里的类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

Split = Literal["train", "tune", "test"]


@dataclass(frozen=True)
class BenchmarkQuestion:
    """Benchmark 题目数据模型，对应 YAML 中的一道题。"""

    id: str
    question: str
    category: str
    domain: str | None
    required_tables: list[str]
    difficulty: str
    identity: str
    # Gold SQL（拒绝/澄清题为 None）
    gold_sql: str | None
    # 预期行为：None（执行 SQL）/ "reject" / "clarify"
    expected_action: str | None
    clarification_hint: str | None
    rejection_reason: str | None
    # 评测时预期的行数（None 表示不校验行数）
    expected_row_count: int | None
    # 预期结果校验和（None 表示不校验内容）
    expected_result_checksum: str | None
    # 是否按行序比较
    is_ordered: bool
    # 涉及的指标 ID（用于报告分析）
    metric_ids: list[str]
    note: str | None
    split: Split
    dataset_version: str
    schema_version: str


@dataclass
class BenchmarkSplit:
    """一个分割文件的全部题目及元数据。"""

    split: Split
    dataset_version: str
    schema_version: str
    seed: int
    business_clock: str
    questions: list[BenchmarkQuestion] = field(default_factory=list)

    @property
    def is_locked(self) -> bool:
        """测试集是锁定的，调用方应防止其被收录到 VQR。"""
        return self.split == "test"


def load_split(path: Path) -> BenchmarkSplit:
    """从 YAML 文件加载一个分割集，并校验题目结构。

    Args:
        path: benchmark YAML 文件路径。

    Returns:
        BenchmarkSplit，含所有题目。

    Raises:
        ValueError: 题目结构不合法（如 ID 重复、缺少 gold_sql 且无 expected_action）。
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    split: Split = raw["split"]
    dataset_version: str = raw["dataset_version"]
    schema_version: str = raw["schema_version"]
    seed: int = int(raw["seed"])
    business_clock: str = raw["business_clock"]

    questions: list[BenchmarkQuestion] = []
    seen_ids: set[str] = set()

    for q in raw.get("questions", []):
        qid = q["id"]
        if qid in seen_ids:
            raise ValueError(f"duplicate question id: {qid} in {path}")
        seen_ids.add(qid)

        gold_sql = q.get("gold_sql")
        expected_action = q.get("expected_action")

        # 清理空字符串
        if gold_sql and gold_sql.strip() == "~":
            gold_sql = None
        if expected_action and expected_action.strip() == "~":
            expected_action = None

        if gold_sql is None and expected_action is None:
            raise ValueError(
                f"question {qid}: must have either gold_sql or expected_action"
            )

        is_ordered = bool(q.get("is_ordered", False))
        metric_ids = q.get("metric_ids") or []
        expected_row_count = q.get("expected_row_count")
        expected_result_checksum = q.get("expected_result_checksum")

        # YAML 的 ~ 被解析为 None，做一次转换
        if expected_row_count == "~":
            expected_row_count = None
        if expected_result_checksum == "~":
            expected_result_checksum = None

        questions.append(
            BenchmarkQuestion(
                id=qid,
                question=q["question"],
                category=q["category"],
                domain=q.get("domain"),
                required_tables=q.get("required_tables") or [],
                difficulty=q.get("difficulty", "medium"),
                identity=q.get("identity", "public"),
                gold_sql=gold_sql,
                expected_action=expected_action,
                clarification_hint=q.get("clarification_hint"),
                rejection_reason=q.get("rejection_reason"),
                expected_row_count=expected_row_count,
                expected_result_checksum=expected_result_checksum,
                is_ordered=is_ordered,
                metric_ids=list(metric_ids),
                note=q.get("note"),
                split=split,
                dataset_version=dataset_version,
                schema_version=schema_version,
            )
        )

    return BenchmarkSplit(
        split=split,
        dataset_version=dataset_version,
        schema_version=schema_version,
        seed=seed,
        business_clock=business_clock,
        questions=questions,
    )


def load_all(benchmark_dir: Path) -> dict[Split, BenchmarkSplit]:
    """加载 benchmark 目录下的全部三个分割文件。

    Args:
        benchmark_dir: 包含 train.yaml / tune.yaml / test.yaml 的目录。

    Returns:
        {split_name: BenchmarkSplit} 字典。
    """
    result: dict[Split, BenchmarkSplit] = {}
    for split_name in ("train", "tune", "test"):
        yaml_path = benchmark_dir / f"{split_name}.yaml"
        if yaml_path.exists():
            split_data = load_split(yaml_path)
            result[split_data.split] = split_data
    return result


def verify_no_leak(train: BenchmarkSplit, test: BenchmarkSplit) -> list[str]:
    """检查 train 集中是否存在 test 集题目的近似改写（通过 ID 前缀）。

    真正的语义相似检测在 V2 阶段实现；这里只做 ID 命名规范检查。

    Returns:
        泄漏警告列表，空列表表示无泄漏。
    """
    warnings: list[str] = []
    test_ids = {q.id for q in test.questions}

    for q in train.questions:
        if q.id in test_ids:
            warnings.append(f"ID collision: {q.id} appears in both train and test")

    return warnings

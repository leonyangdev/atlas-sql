from pathlib import Path

import yaml


def load_metrics() -> dict[str, object]:
    path = Path("semantic_models/drafts/core_metrics.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_metric_draft_has_required_business_defaults() -> None:
    catalog = load_metrics()
    defaults = catalog["defaults"]

    assert defaults["timezone"] == "Asia/Shanghai"
    assert defaults["tax_treatment"] == "tax_inclusive"
    assert defaults["order_time_role"] == "paid_at"
    assert defaults["refund_time_role"] == "refunded_at"


def test_core_metrics_make_zero_and_time_rules_explicit() -> None:
    metrics = {item["id"]: item for item in load_metrics()["metrics"]}

    assert {"net_sales", "paid_order_count", "average_order_value", "gross_margin_rate"} <= set(
        metrics
    )
    assert all(metric.get("time_rule") for metric in metrics.values())
    assert all(metric.get("zero_denominator") for metric in metrics.values())
    assert metrics["average_order_value"]["zero_denominator"] == "null_with_reason"
    assert "简单平均" in metrics["gross_margin_rate"]["warning"]


def test_metric_conflicts_remain_visible() -> None:
    metrics = {item["id"]: item for item in load_metrics()["metrics"]}

    assert metrics["net_sales"]["open_decisions"]
    assert metrics["refund_rate"]["open_decisions"]

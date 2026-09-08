from pathlib import Path

import pytest
import yaml

from datasets.generator.database import validate_local_reset_target
from datasets.generator.model import PROFILES, fixture_rows, iter_order_batches


def test_profiles_include_a_real_million_row_scale() -> None:
    assert PROFILES["tiny"].order_count < PROFILES["dev"].order_count
    assert PROFILES["dev"].order_count < PROFILES["scale"].order_count
    assert PROFILES["scale"].order_item_count == 1_000_000


def test_tiny_generation_is_deterministic_and_contains_boundaries() -> None:
    first = list(iter_order_batches(PROFILES["tiny"]))
    second = list(iter_order_batches(PROFILES["tiny"]))
    orders = first[0].orders

    assert first == second
    assert any(order["customer_id"] is None for order in orders)
    assert any(order["is_test"] for order in orders)
    assert any(order["order_status"] == "CANCELLED" for order in orders)
    assert len(first[0].refund_items) > len(first[0].refunds)
    assert min(order["ordered_at"].year for order in orders) < max(
        order["ordered_at"].year for order in orders
    )


def test_domain_fixtures_cover_history_snapshot_many_to_many_and_ambiguity() -> None:
    rows = fixture_rows()
    product_names = [row["product_name"] for row in rows["dim_product"]]

    assert len(rows["bridge_store_region_history"]) == 2
    assert rows["customer_membership_history"]
    assert rows["fact_inventory_snapshot"]
    assert rows["campaign_product_bridge"]
    assert len(product_names) != len(set(product_names))
    assert any(row["barcode"] is None for row in rows["dim_sku"])
    assert all(str(row["sku_code"]).startswith("INTERNAL-") for row in rows["dim_sku"])


def test_reset_guard_rejects_remote_wrong_database_and_reader() -> None:
    validate_local_reset_target(
        "postgresql://owner:password@127.0.0.1:5433/nova_retail", "nova_retail"
    )
    invalid = (
        ("postgresql://owner:password@db.example.com/nova_retail", "nova_retail"),
        ("postgresql://owner:password@localhost/production", "production"),
        ("postgresql://owner:password@localhost/nova_retail", "wrong"),
        ("postgresql://atlas_reader:password@localhost/nova_retail", "nova_retail"),
    )
    for url, confirmation in invalid:
        with pytest.raises(ValueError):
            validate_local_reset_target(url, confirmation)


def test_dirty_cases_are_never_enabled_by_default() -> None:
    path = Path("datasets/fixtures/dirty_cases.yaml")
    fixture = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert fixture["enabled_by_default"] is False
    assert {case["expected_check"] for case in fixture["cases"]} == {
        "foreign_key",
        "monetary_reconciliation",
        "status_consistency",
    }


def test_access_scope_fixture_has_region_store_and_empty_identities() -> None:
    path = Path("datasets/fixtures/access_scopes.yaml")
    fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
    principals = fixture["principals"]

    assert any(item["allowed_region_codes"] for item in principals)
    assert any(item["allowed_store_codes"] for item in principals)
    assert any(
        not item["allowed_region_codes"] and not item["allowed_store_codes"] for item in principals
    )

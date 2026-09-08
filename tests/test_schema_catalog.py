from collections import Counter

from datasets.schema.catalog import TABLES, validate_catalog


def test_catalog_meets_v0_scale_and_domain_targets() -> None:
    domains = Counter(table.domain for table in TABLES)
    column_count = sum(len(table.columns) for table in TABLES)

    assert set(domains) == {
        "sales",
        "product",
        "customer",
        "store",
        "inventory",
        "finance",
        "marketing",
    }
    assert all(count >= 8 for count in domains.values())
    assert 50 <= len(TABLES) <= 80
    assert 600 <= column_count <= 1000


def test_catalog_references_and_enums_are_consistent() -> None:
    assert validate_catalog() == []
    relationships = [
        column for table in TABLES for column in table.columns if column.reference is not None
    ]
    assert relationships
    assert all(column.relationship_cardinality == "many-to-one" for column in relationships)
    assert all(
        [column.name for column in table.columns if column.is_primary_key] == ["id"]
        for table in TABLES
    )


def test_catalog_contains_enterprise_modeling_challenges() -> None:
    kinds = {table.kind for table in TABLES}
    sensitivities = {column.sensitivity for table in TABLES for column in table.columns}

    assert {"fact", "dimension", "bridge", "history", "snapshot"} <= kinds
    assert {"public", "internal", "confidential", "restricted"} <= sensitivities
    assert any(table.status_enums for table in TABLES)
    assert any(table.history_strategy == "bitemporal" for table in TABLES)

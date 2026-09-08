from pathlib import Path

from datasets.migrations import migration_files, quote_identifier, render_schema_sql
from datasets.schema.catalog import TABLES


def test_schema_migration_contains_every_table_and_relationship() -> None:
    sql = render_schema_sql()
    relationship_count = sum(
        column.reference is not None for table in TABLES for column in table.columns
    )

    assert sql.count("CREATE TABLE public.") == len(TABLES)
    assert sql.count("ADD CONSTRAINT") == relationship_count
    assert sql.count("CREATE INDEX") == relationship_count


def test_migration_files_are_applied_in_version_order(tmp_path: Path) -> None:
    (tmp_path / "002_second.sql").write_text("SELECT 2", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("SELECT 1", encoding="utf-8")
    (tmp_path / "notes.md").write_text("ignored", encoding="utf-8")

    assert [path.name for path in migration_files(tmp_path)] == [
        "001_first.sql",
        "002_second.sql",
    ]


def test_sql_identifiers_are_restricted() -> None:
    assert quote_identifier("fact_order") == '"fact_order"'

    try:
        quote_identifier("fact_order; DROP TABLE")
    except ValueError as error:
        assert "unsafe SQL identifier" in str(error)
    else:
        raise AssertionError("unsafe identifier was accepted")

"""从声明式 catalog 生成机器可读字典和面向学习者的业务域关系图。"""

import json
from collections import Counter
from pathlib import Path

from datasets.schema.catalog import TABLES, validate_catalog

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """校验源目录后一次性重建两个派生产物。

    JSON 供后续元数据同步和测试读取，Markdown 只呈现业务域之间的主要分析关系。物理外键
    的完整清单仍以 catalog 和生成的 SQL 为准。
    """

    errors = validate_catalog()
    if errors:
        raise SystemExit("\n".join(errors))

    dictionary_dir = ROOT / "datasets" / "dictionary"
    dictionary_dir.mkdir(parents=True, exist_ok=True)
    domains = Counter(table.domain for table in TABLES)
    payload = {
        "catalog_version": "0.1.0",
        "table_count": len(TABLES),
        "column_count": sum(len(table.columns) for table in TABLES),
        "domains": dict(sorted(domains.items())),
        "tables": [table.to_dict() for table in TABLES],
    }
    (dictionary_dir / "catalog.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Mermaid 图保持在“业务域”粒度，避免 56 张表的完整 ER 图在学习站中无法阅读。
    lines = [
        "# NovaRetail 业务域关系",
        "",
        "> 由 `datasets/schema/catalog.py` 生成。箭头表示主要分析关联，不代表所有物理外键。",
        "",
        "```mermaid",
        "flowchart LR",
        "  Customer --> Sales",
        "  Product --> Sales",
        "  Store --> Sales",
        "  Product --> Inventory",
        "  Store --> Inventory",
        "  Sales --> Finance",
        "  Product --> Finance",
        "  Marketing --> Sales",
        "  Customer --> Marketing",
        "  Product --> Marketing",
        "```",
        "",
        f"目录当前包含 {len(TABLES)} 张表、{payload['column_count']} 个字段。",
        "",
        "| 业务域 | 表数 |",
        "| --- | ---: |",
        *(f"| {domain.title()} | {count} |" for domain, count in sorted(domains.items())),
    ]
    (dictionary_dir / "domain-relationship.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"generated {len(TABLES)} tables and {payload['column_count']} columns")


if __name__ == "__main__":
    main()

"""从声明式 catalog 重建业务库 SQL；CI 用 Git diff 检查生成物漂移。"""

from pathlib import Path

from datasets.migrations import MIGRATION_ROOT, render_schema_sql


def main() -> None:
    """写入固定版本文件，schema 变化时由开发者评估是否应创建新版本。"""

    MIGRATION_ROOT.mkdir(parents=True, exist_ok=True)
    target = Path(MIGRATION_ROOT, "001_nova_retail_schema.sql")
    target.write_text(render_schema_sql(), encoding="utf-8")
    print(f"generated {target}")


if __name__ == "__main__":
    main()

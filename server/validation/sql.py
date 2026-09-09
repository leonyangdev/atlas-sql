"""基于 SQLGlot AST 的 V1 SQL 安全校验。

字符串黑名单无法抵抗注释、大小写、CTE 和嵌套查询绕过。本模块先把 PostgreSQL SQL 解析成
AST，再从语句类型、表、列和函数四个维度实施默认拒绝。校验成功后返回规范化 SQL，执行器
只接受这个结果类型，从接口上保证未经校验的字符串不能误入业务库。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope

from server.domain.query import QueryErrorCode
from server.domain.sales_scope import ALLOWED_COLUMNS

# 只开放基线问数真正需要的纯函数。SQLGlot 会把 AND、CASE 等表达式也表示为 Func，故它们
# 同样需要显式列出。未知函数默认拒绝，因而 pg_sleep、文件读取和扩展函数不会被执行。
ALLOWED_FUNCTIONS = frozenset(
    {
        "ABS",
        "AND",
        "AVG",
        "CASE",
        "CAST",
        "COALESCE",
        "COUNT",
        "CURRENT_DATE",
        "DATE",
        "EXISTS",
        "EXTRACT",
        "IF",
        "LAG",
        "LOWER",
        "MAX",
        "MIN",
        "NULLIF",
        "OR",
        "ROUND",
        "ROW_NUMBER",
        "SUM",
        "TIMESTAMP_TRUNC",
        "UPPER",
    }
)


@dataclass(frozen=True)
class ValidatedSQL:
    """通过完整白名单校验、可以交给只读执行器的 SQL。"""

    sql: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]


class SQLValidationError(ValueError):
    """不携带 SQL 原文的类型化校验失败。"""

    def __init__(self, code: QueryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class SQLValidator:
    """验证单条只读 PostgreSQL 查询及其所有嵌套节点。"""

    def validate(self, sql: str) -> ValidatedSQL:
        """解析并校验 SQL；任何未知结构均安全失败。"""

        try:
            statements = [statement for statement in parse(sql, read="postgres") if statement]
        except ParseError as exc:
            raise SQLValidationError(QueryErrorCode.SQL_PARSE_ERROR, "SQL 语法无法解析。") from exc

        if len(statements) != 1:
            raise SQLValidationError(
                QueryErrorCode.SQL_SECURITY_VIOLATION,
                "只允许执行一条查询语句。",
            )

        statement = statements[0]
        if not isinstance(statement, exp.Query) or statement.find(exp.Select) is None:
            raise SQLValidationError(
                QueryErrorCode.SQL_SECURITY_VIOLATION,
                "只允许执行 SELECT 查询。",
            )

        self._reject_write_nodes(statement)
        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        tables, aliases = self._validate_tables(statement, cte_names)
        columns = self._validate_columns(statement, aliases)
        self._validate_functions(statement)
        return ValidatedSQL(
            sql=statement.sql(dialect="postgres"),
            tables=tuple(sorted(tables)),
            columns=tuple(sorted(columns)),
        )

    def _reject_write_nodes(self, statement: exp.Expression) -> None:
        """拒绝顶层或 CTE/子查询中的所有写入与管理节点。"""

        forbidden = (
            exp.Alter,
            exp.Command,
            exp.Copy,
            exp.Create,
            exp.Delete,
            exp.Drop,
            exp.Insert,
            exp.Into,
            exp.Merge,
            exp.Transaction,
            exp.TruncateTable,
            exp.Update,
        )
        for node in statement.walk():
            if isinstance(node, forbidden):
                raise SQLValidationError(
                    QueryErrorCode.SQL_SECURITY_VIOLATION,
                    "查询包含写入或管理操作。",
                )

    def _validate_tables(
        self,
        statement: exp.Expression,
        cte_names: set[str],
    ) -> tuple[set[str], dict[str, str]]:
        tables: set[str] = set()
        aliases: dict[str, str] = {}
        for table in statement.find_all(exp.Table):
            name = table.name
            if name in cte_names:
                continue
            # V1 固定读取 public schema；显式跨库或其他 schema 一律拒绝。
            if table.catalog or (table.db and table.db != "public") or name not in ALLOWED_COLUMNS:
                raise SQLValidationError(
                    QueryErrorCode.SQL_OUT_OF_SCOPE,
                    f"表 {name or '<unknown>'} 不在 V1 Sales 范围内。",
                )
            tables.add(name)
            aliases[table.alias_or_name] = name
            aliases[name] = name
        return tables, aliases

    def _validate_columns(
        self,
        statement: exp.Expression,
        global_aliases: dict[str, str],
    ) -> set[str]:
        referenced: set[str] = set()
        for scope in traverse_scope(statement):
            for column in scope.columns:
                if column.is_star:
                    continue
                table_name = self._resolve_column_table(scope, column, global_aliases)
                if table_name is None:
                    raise SQLValidationError(
                        QueryErrorCode.SQL_OUT_OF_SCOPE,
                        f"字段 {column.name} 不在允许范围内或来源不明确。",
                    )
                if table_name == "<derived>":
                    continue
                if column.name not in ALLOWED_COLUMNS[table_name]:
                    raise SQLValidationError(
                        QueryErrorCode.SQL_OUT_OF_SCOPE,
                        f"字段 {table_name}.{column.name} 不在允许范围内。",
                    )
                referenced.add(f"{table_name}.{column.name}")
        return referenced

    def _resolve_column_table(
        self,
        scope: Scope,
        column: exp.Column,
        global_aliases: dict[str, str],
    ) -> str | None:
        if column.table:
            source = scope.sources.get(column.table)
            if isinstance(source, exp.Table):
                return source.name
            if isinstance(source, Scope):
                return "<derived>" if _scope_exports(source, column.name) else None
            # 相关子查询可能引用父层别名，遍历结果中当前 scope 不会重复父 source。
            return global_aliases.get(column.table)

        matches: set[str] = set()
        derived_match = False
        for source in scope.sources.values():
            if isinstance(source, exp.Table) and source.name in ALLOWED_COLUMNS:
                if column.name in ALLOWED_COLUMNS[source.name]:
                    matches.add(source.name)
            elif isinstance(source, Scope) and _scope_exports(source, column.name):
                derived_match = True
        if len(matches) == 1:
            return next(iter(matches))
        if not matches and derived_match:
            return "<derived>"
        return None

    def _validate_functions(self, statement: exp.Expression) -> None:
        for function in statement.find_all(exp.Func):
            name = (
                function.name.upper()
                if isinstance(function, exp.Anonymous)
                # SQLGlot 此方法的发行包未携带类型标注，但运行时稳定返回规范函数名。
                else function.sql_name()  # type: ignore[no-untyped-call]
            )
            if name not in ALLOWED_FUNCTIONS:
                raise SQLValidationError(
                    QueryErrorCode.SQL_SECURITY_VIOLATION,
                    f"函数 {name} 不在允许范围内。",
                )


def _scope_exports(scope: Scope, column_name: str) -> bool:
    """判断派生表是否显式输出字段；星号表示沿用来源列。"""

    names = set(scope.expression.named_selects)
    return column_name in names or "*" in names

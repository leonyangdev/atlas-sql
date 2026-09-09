"""只依据实际查询结果生成 V1 基础摘要。"""

from __future__ import annotations

from server.domain.query import QueryColumn

QueryCell = str | int | float | bool | None


class ResultSummaryBuilder:
    """生成可核对的确定性摘要，不把问题或模型自由文本当成事实来源。"""

    def build(
        self,
        columns: tuple[QueryColumn, ...],
        rows: tuple[tuple[QueryCell, ...], ...],
        *,
        truncated: bool,
    ) -> str:
        if not rows:
            return "未查询到符合条件的记录。"
        if len(rows) == 1 and len(columns) == 1:
            value = rows[0][0]
            if value is None:
                return f"查询结果中“{columns[0].name}”为空值。"
            return f"查询结果：{columns[0].name} 为 {value}。"

        suffix = "，当前仅展示前若干行" if truncated else ""
        return f"查询返回 {len(rows)} 行、{len(columns)} 列{suffix}。"

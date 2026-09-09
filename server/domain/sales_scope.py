"""V1 冻结的 Sales 查询范围。

V1 故意只暴露 15 张高频销售事实表和维度表。映射在代码中显式列出，schema 采集到新字段
时不会自动扩权；要扩大范围必须修改本文件、评审并重新跑基线。机密字段同样默认排除。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from server.domain.query import QueryErrorCode, QueryStatus

SALES_SCOPE_VERSION = "v1-sales-001"
SALES_DATA_VERSION = "v0.1.0"
SALES_SCHEMA_VERSION = "001"

_ALLOWED_COLUMNS: dict[str, frozenset[str]] = {
    "dim_region": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "region_code",
            "region_name",
            "country_code",
            "status",
        }
    ),
    "dim_city": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "city_code",
            "city_name",
            "province_name",
            "region_id",
            "timezone",
        }
    ),
    "dim_store": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "store_code",
            "store_name",
            "city_id",
            "store_type",
            "opened_on",
            "closed_on",
        }
    ),
    "dim_sales_channel": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "channel_code",
            "channel_name",
            "channel_group",
            "is_online",
            "status",
        }
    ),
    "dim_category": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "category_code",
            "category_name",
            "parent_category_id",
            "category_level",
            "path_code",
        }
    ),
    "dim_product": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "product_code",
            "product_name",
            "brand_id",
            "primary_category_id",
            "product_status",
        }
    ),
    "dim_sku": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "sku_code",
            "product_id",
            "color_name",
            "size_name",
            "list_price",
        }
    ),
    "fact_order": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "store_id",
            "channel_id",
            "ordered_at",
            "paid_at",
            "order_status",
            "is_test",
            "order_amount",
        }
    ),
    "fact_order_item": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "order_id",
            "line_no",
            "sku_id",
            "quantity",
            "gross_amount",
            "discount_amount",
            "net_amount",
            "tax_amount",
        }
    ),
    "fact_payment": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "order_id",
            "payment_method",
            "payment_status",
            "paid_amount",
            "paid_at",
        }
    ),
    "fact_refund": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "order_id",
            "refund_status",
            "requested_at",
            "refunded_at",
            "refund_amount",
        }
    ),
    "fact_refund_item": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "refund_id",
            "order_item_id",
            "refund_quantity",
            "refund_amount",
            "reason_code",
        }
    ),
    "order_status_history": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "order_id",
            "from_status",
            "to_status",
            "changed_at",
            "operator_type",
        }
    ),
    "order_coupon_bridge": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "order_id",
            "coupon_id",
            "redemption_id",
            "allocated_discount",
            "applied_at",
        }
    ),
    "sales_daily_aggregate": frozenset(
        {
            "id",
            "source_system",
            "effective_from",
            "effective_to",
            "is_current",
            "created_at",
            "updated_at",
            "sales_date",
            "store_id",
            "sku_id",
            "paid_order_count",
            "sales_quantity",
            "net_sales_amount",
            "refund_amount",
        }
    ),
}

ALLOWED_COLUMNS: Mapping[str, frozenset[str]] = MappingProxyType(_ALLOWED_COLUMNS)

# 指标草案来自 semantic_models/drafts/core_metrics.yaml。这里只登记 V1 的非受限 Sales 指标，
# Prompt Builder 在 V1-S02 会读取完整定义；当前阶段只用于判断是否需要澄清。
METRIC_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "净销售额": "net_sales",
        "销售额": "net_sales",
        "有效订单量": "paid_order_count",
        "订单量": "paid_order_count",
        "销量": "sales_quantity",
        "销售数量": "sales_quantity",
        "客单价": "average_order_value",
        "退款金额": "refunded_amount",
        "退款率": "refund_rate",
    }
)

_OUT_OF_SCOPE_KEYWORDS = frozenset(
    {
        "库存",
        "仓库",
        "盘点",
        "补货",
        "调拨",
        "营销",
        "投放",
        "触达",
        "财务",
        "会计",
        "成本",
        "毛利",
        "利润",
        "会员等级",
        "客户标签",
    }
)
_AMBIGUOUS_METRIC_KEYWORDS = frozenset({"收入", "营收"})


@dataclass(frozen=True)
class ScopeDecision:
    """范围判断结果，不依赖 HTTP 或 LLM。"""

    status: QueryStatus
    metric_ids: tuple[str, ...] = ()
    error_code: QueryErrorCode | None = None
    message: str | None = None


def assess_sales_scope(question: str) -> ScopeDecision:
    """用保守规则执行 V1 域边界和指标消歧。

    这不是意图分类器。它只负责挡住明确的非 Sales 范围，并对销售/财务都有含义的“收入”
    请求澄清；其余问题交给后续固定 Schema 的生成链路。
    """

    matched_domains = sorted(keyword for keyword in _OUT_OF_SCOPE_KEYWORDS if keyword in question)
    if matched_domains:
        return ScopeDecision(
            status=QueryStatus.REJECTED,
            error_code=QueryErrorCode.OUT_OF_SCOPE,
            message="V1 仅支持固定 Sales 范围，不支持库存、财务等跨域查询。",
        )

    if any(keyword in question for keyword in _AMBIGUOUS_METRIC_KEYWORDS):
        return ScopeDecision(
            status=QueryStatus.CLARIFICATION_REQUIRED,
            error_code=QueryErrorCode.AMBIGUOUS_METRIC,
            message="请确认你需要销售域的净销售额，还是财务域的入账收入。",
        )

    metric_ids = tuple(
        sorted({metric_id for alias, metric_id in METRIC_ALIASES.items() if alias in question})
    )
    return ScopeDecision(status=QueryStatus.PROCESSING, metric_ids=metric_ids)


def is_allowed_column(table_name: str, column_name: str) -> bool:
    """返回字段是否属于冻结白名单；未知表和未知字段都安全地返回 False。"""

    return column_name in ALLOWED_COLUMNS.get(table_name, frozenset())


def scope_as_prompt_schema() -> dict[str, tuple[str, ...]]:
    """返回确定顺序的只读副本，供下一故事的 Prompt Builder 使用。"""

    return {table: tuple(sorted(columns)) for table, columns in sorted(ALLOWED_COLUMNS.items())}

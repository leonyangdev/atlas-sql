"""确定性的 NovaRetail 业务数据规则。

本模块不连接数据库，只把 profile 转换成 Python 行数据。这样可以快速单测 seed、边界数据和
金额规则；数据库事务、约束与批量 COPY 由 ``database.py`` 负责。
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

DATASET_VERSION = "v0.1.0"
SCHEMA_VERSION = "001"
BUSINESS_CLOCK = datetime(2026, 6, 30, 16, 0, tzinfo=UTC)


@dataclass(frozen=True)
class DatasetProfile:
    """一档数据规模；scale 必须真实产生一百万条订单明细。"""

    name: str
    seed: int
    order_count: int
    items_per_order: int
    batch_size: int

    @property
    def order_item_count(self) -> int:
        return self.order_count * self.items_per_order


@dataclass(frozen=True)
class OrderBatch:
    """满足外键写入顺序的一批订单、明细、支付和退款。"""

    orders: list[dict[str, object]]
    items: list[dict[str, object]]
    payments: list[dict[str, object]]
    refunds: list[dict[str, object]]
    refund_items: list[dict[str, object]]


PROFILES = {
    "tiny": DatasetProfile("tiny", seed=20260908, order_count=24, items_per_order=3, batch_size=24),
    "dev": DatasetProfile(
        "dev", seed=20260908, order_count=20_000, items_per_order=5, batch_size=2_000
    ),
    "scale": DatasetProfile(
        "scale", seed=20260908, order_count=200_000, items_per_order=5, batch_size=5_000
    ),
}


def base_row(row_id: int, record_id: str) -> dict[str, object]:
    """补齐所有业务表共享的租户、来源和 SCD 时间字段。"""

    return {
        "id": row_id,
        "tenant_id": 1,
        "source_system": "NOVA_SIM",
        "source_record_id": record_id,
        "effective_from": date(2023, 1, 1),
        "effective_to": None,
        "is_current": True,
        "created_at": BUSINESS_CLOCK,
        "updated_at": BUSINESS_CLOCK,
    }


def fixture_rows() -> dict[str, list[dict[str, object]]]:
    """生成小而明确的跨域维度与边界夹具。

    这里刻意保留同名商品、NULL、门店历史和多对多关系。它们不是随机噪声，而是后续
    NL2SQL 检索、澄清和 Join 正确性必须面对的固定案例。
    """

    rows: dict[str, list[dict[str, object]]] = {
        "dim_region": [
            base_row(1, "REGION-NORTH")
            | {
                "region_code": "NORTH",
                "region_name": "北区",
                "country_code": "CN",
                "manager_employee_no": "EMP-N-001",
                "status": "ACTIVE",
            },
            base_row(2, "REGION-SOUTH")
            | {
                "region_code": "SOUTH",
                "region_name": "南区",
                "country_code": "CN",
                "manager_employee_no": "EMP-S-001",
                "status": "ACTIVE",
            },
        ],
        "dim_city": [
            base_row(1, "CITY-BJ")
            | {
                "city_code": "BJ",
                "city_name": "北京",
                "province_name": "北京",
                "region_id": 1,
                "timezone": "Asia/Shanghai",
            },
            base_row(2, "CITY-SZ")
            | {
                "city_code": "SZ",
                "city_name": "深圳",
                "province_name": "广东",
                "region_id": 2,
                "timezone": "Asia/Shanghai",
            },
        ],
        "dim_store": [
            base_row(1, "STORE-BJ-001")
            | {
                "store_code": "BJ-001",
                "store_name": "中心店",
                "city_id": 1,
                "store_type": "FLAGSHIP",
                "opened_on": date(2020, 1, 1),
                "closed_on": None,
            },
            base_row(2, "STORE-BJ-002")
            | {
                "store_code": "BJ-002",
                "store_name": "北城店",
                "city_id": 1,
                "store_type": "STANDARD",
                "opened_on": date(2021, 6, 1),
                "closed_on": None,
            },
            base_row(3, "STORE-SZ-001")
            | {
                "store_code": "SZ-001",
                "store_name": "中心店",
                "city_id": 2,
                "store_type": "STANDARD",
                "opened_on": date(2022, 3, 1),
                "closed_on": None,
            },
        ],
        "bridge_store_region_history": [
            base_row(1, "STORE-REGION-OLD")
            | {
                "store_id": 2,
                "region_id": 2,
                "valid_from_date": date(2021, 6, 1),
                "valid_to_date": date(2024, 12, 31),
                "change_reason": "组织调整前归属",
            },
            base_row(2, "STORE-REGION-CURRENT")
            | {
                "store_id": 2,
                "region_id": 1,
                "valid_from_date": date(2025, 1, 1),
                "valid_to_date": None,
                "change_reason": "组织调整",
            },
        ],
        "dim_warehouse": [
            base_row(1, "WAREHOUSE-BJ")
            | {
                "warehouse_code": "WH-BJ",
                "warehouse_name": "北京中心仓",
                "city_id": 1,
                "warehouse_type": "REGIONAL",
                "capacity_units": 500_000,
            },
            base_row(2, "WAREHOUSE-SZ")
            | {
                "warehouse_code": "WH-SZ",
                "warehouse_name": "深圳中心仓",
                "city_id": 2,
                "warehouse_type": "REGIONAL",
                "capacity_units": 400_000,
            },
        ],
        "dim_sales_channel": [
            base_row(1, "CHANNEL-STORE")
            | {
                "channel_code": "STORE",
                "channel_name": "线下门店",
                "channel_group": "OFFLINE",
                "is_online": False,
                "status": "ACTIVE",
            },
            base_row(2, "CHANNEL-APP")
            | {
                "channel_code": "APP",
                "channel_name": "官方 App",
                "channel_group": "ONLINE",
                "is_online": True,
                "status": "ACTIVE",
            },
        ],
        "dim_brand": [
            base_row(1, "BRAND-ATLAS")
            | {
                "brand_code": "ATLAS",
                "brand_name": "Atlas Basics",
                "brand_name_zh": "阿特拉斯基础款",
                "country_code": "CN",
                "status": "ACTIVE",
            }
        ],
        "dim_category": [
            base_row(1, "CATEGORY-APPAREL")
            | {
                "category_code": "APPAREL",
                "category_name": "服饰",
                "parent_category_id": None,
                "category_level": 1,
                "path_code": "APPAREL",
            }
        ],
        "dim_product": [],
        "dim_sku": [],
        "dim_customer": [],
        "dim_membership_tier": [
            base_row(1, "TIER-BASIC")
            | {
                "tier_code": "BASIC",
                "tier_name": "普通会员",
                "minimum_points": 0,
                "discount_rate": Decimal("1.0000"),
                "rank_order": 1,
            },
            base_row(2, "TIER-GOLD")
            | {
                "tier_code": "GOLD",
                "tier_name": "金卡会员",
                "minimum_points": 1000,
                "discount_rate": Decimal("0.9500"),
                "rank_order": 2,
            },
        ],
        "customer_membership_history": [],
        "dim_marketing_channel": [
            base_row(1, "MKT-WECHAT")
            | {
                "channel_code": "WECHAT",
                "channel_name": "企业微信",
                "channel_type": "SOCIAL",
                "vendor_name": None,
                "status": "ACTIVE",
            }
        ],
        "dim_campaign": [
            base_row(1, "CAMPAIGN-SPRING")
            | {
                "campaign_code": "SPRING",
                "campaign_name": "春季会员活动",
                "channel_id": 1,
                "campaign_status": "ENDED",
                "start_at": datetime(2025, 3, 1, tzinfo=UTC),
                "end_at": datetime(2025, 3, 31, 16, tzinfo=UTC),
            }
        ],
        "campaign_product_bridge": [],
        "fact_campaign_touch": [],
        "fact_inventory_snapshot": [],
    }

    for product_id in range(1, 7):
        product_name = "经典 T 恤" if product_id <= 2 else f"商品 {product_id}"
        rows["dim_product"].append(
            base_row(product_id, f"PRODUCT-{product_id:03d}")
            | {
                "product_code": f"P-{product_id:03d}",
                "product_name": product_name,
                "brand_id": 1,
                "primary_category_id": 1,
                "product_status": "ACTIVE",
            }
        )
        rows["dim_sku"].append(
            base_row(product_id, f"INTERNAL-SKU-{product_id:03d}")
            | {
                "sku_code": f"INTERNAL-SKU-{product_id:03d}",
                "product_id": product_id,
                "barcode": None if product_id == 6 else f"69000000000{product_id}",
                "color_name": None if product_id == 5 else "黑色",
                "size_name": "M",
                "list_price": Decimal(20 + product_id),
            }
        )

    for customer_id in range(1, 21):
        rows["dim_customer"].append(
            base_row(customer_id, f"CUSTOMER-{customer_id:04d}")
            | {
                "customer_code": f"C-{customer_id:04d}",
                "customer_name": f"模拟客户 {customer_id}",
                "mobile_hash": sha256(f"mobile-{customer_id}".encode()).hexdigest(),
                "email_hash": (
                    None
                    if customer_id % 4 == 0
                    else sha256(f"email-{customer_id}".encode()).hexdigest()
                ),
                "registered_at": datetime(2023, 1, customer_id, tzinfo=UTC),
                "status": "ACTIVE",
            }
        )
        rows["customer_membership_history"].append(
            base_row(customer_id, f"MEMBERSHIP-{customer_id:04d}-BASIC")
            | {
                "customer_id": customer_id,
                "tier_id": 1 if customer_id > 5 else 2,
                "valid_from_at": datetime(2023, 1, customer_id, tzinfo=UTC),
                "valid_to_at": None,
                "change_reason": "INITIAL" if customer_id > 5 else "UPGRADE",
            }
        )

    for touch_id in range(1, 13):
        rows["fact_campaign_touch"].append(
            base_row(touch_id, f"CAMPAIGN-TOUCH-{touch_id}")
            | {
                "campaign_id": 1,
                "customer_id": touch_id,
                "marketing_channel_id": 1,
                "touch_type": "MESSAGE",
                "touch_status": "OPENED" if touch_id % 3 else "DELIVERED",
                "touched_at": datetime(2025, 3, touch_id, 8, tzinfo=UTC),
            }
        )

    for product_id in range(1, 7):
        rows["campaign_product_bridge"].append(
            base_row(product_id, f"CAMPAIGN-PRODUCT-{product_id}")
            | {
                "campaign_id": 1,
                "product_id": product_id,
                "category_id": None,
                "inclusion_type": "INCLUDE",
                "priority": product_id,
            }
        )
    for snapshot_id in range(1, 13):
        day = date(2025, 12, 30) + timedelta(days=(snapshot_id - 1) // 4)
        sku_id = (snapshot_id - 1) % 6 + 1
        on_hand = Decimal(100 + snapshot_id)
        reserved = Decimal(snapshot_id % 5)
        rows["fact_inventory_snapshot"].append(
            base_row(snapshot_id, f"SNAPSHOT-{snapshot_id}")
            | {
                "snapshot_date": day,
                "warehouse_id": 1 if snapshot_id % 2 else 2,
                "sku_id": sku_id,
                "on_hand_quantity": on_hand,
                "reserved_quantity": reserved,
                "available_quantity": on_hand - reserved,
            }
        )
    return rows


def expected_order_amount(order_id: int, items_per_order: int, seed: int) -> Decimal:
    """独立计算订单应付金额，供生成过程和数据库验收共同核对。"""

    amount = Decimal("0")
    for line_no in range(1, items_per_order + 1):
        sku_id = (order_id + line_no + seed) % 6 + 1
        gross = Decimal(20 + sku_id)
        discount = Decimal("1.00") if (order_id + line_no) % 5 == 0 else Decimal("0")
        amount += gross - discount
    return amount


def iter_order_batches(profile: DatasetProfile) -> Iterator[OrderBatch]:
    """按 profile 批量生成事实数据，避免 scale 配置一次占用全部内存。

    时间和业务属性仅依赖 order_id、seed 与固定业务时钟，所以相同版本在不同机器上应得到
    相同业务摘要。每个退款固定关联两个明细，用于演示按订单直接 Join 导致的行数放大。
    """

    refund_id = 0
    for start in range(1, profile.order_count + 1, profile.batch_size):
        stop = min(start + profile.batch_size, profile.order_count + 1)
        orders: list[dict[str, object]] = []
        items: list[dict[str, object]] = []
        payments: list[dict[str, object]] = []
        refunds: list[dict[str, object]] = []
        refund_items: list[dict[str, object]] = []
        for order_id in range(start, stop):
            cancelled = order_id == 3 or order_id % 29 == 0
            is_test = order_id == 2 or order_id % 101 == 0
            customer_id = (
                None if order_id == 4 or order_id % 17 == 0 else (order_id + profile.seed) % 20 + 1
            )
            ordered_at = BUSINESS_CLOCK - timedelta(
                days=(order_id * 17 + profile.seed) % 730,
                seconds=(order_id * 7919) % 86_400,
            )
            paid_at = None if cancelled else ordered_at + timedelta(minutes=3 + order_id % 40)
            order_amount = Decimal("0")
            order_items: list[dict[str, object]] = []
            for line_no in range(1, profile.items_per_order + 1):
                item_id = (order_id - 1) * profile.items_per_order + line_no
                sku_id = (order_id + line_no + profile.seed) % 6 + 1
                gross = Decimal(20 + sku_id)
                discount = Decimal("1.00") if (order_id + line_no) % 5 == 0 else Decimal("0")
                net = gross - discount
                order_amount += net
                order_items.append(
                    base_row(item_id, f"ORDER-ITEM-{item_id}")
                    | {
                        "order_id": order_id,
                        "line_no": line_no,
                        "sku_id": sku_id,
                        "quantity": Decimal("1.000"),
                        "gross_amount": gross,
                        "discount_amount": discount,
                        "net_amount": net,
                        "tax_amount": (net * Decimal("0.13")).quantize(Decimal("0.01")),
                    }
                )
            orders.append(
                base_row(order_id, f"ORDER-{order_id}")
                | {
                    "order_no": f"NO-{order_id:09d}",
                    "customer_id": customer_id,
                    "store_id": order_id % 3 + 1,
                    "channel_id": order_id % 2 + 1,
                    "ordered_at": ordered_at,
                    "paid_at": paid_at,
                    "order_status": "CANCELLED" if cancelled else "COMPLETED",
                    "is_test": is_test,
                    "order_amount": order_amount,
                }
            )
            if order_amount != expected_order_amount(
                order_id, profile.items_per_order, profile.seed
            ):
                raise RuntimeError(f"order {order_id} amount generation is inconsistent")
            items.extend(order_items)
            if not cancelled:
                payments.append(
                    base_row(order_id, f"PAYMENT-{order_id}")
                    | {
                        "order_id": order_id,
                        "payment_no": f"PAY-{order_id:09d}",
                        "payment_method": "WECHAT" if order_id % 2 else "ALIPAY",
                        "payment_status": "SUCCEEDED",
                        "paid_amount": order_amount,
                        "paid_at": paid_at,
                    }
                )
            if not cancelled and order_id % 20 == 0:
                refund_id += 1
                refunded_at = paid_at + timedelta(days=order_id % 45 + 1)  # type: ignore[operator]
                refunded_items = order_items[:2]
                refund_amount = Decimal("0")
                for item in refunded_items:
                    item_amount = item["net_amount"]
                    if not isinstance(item_amount, Decimal):
                        raise TypeError("order-item amount must be Decimal")
                    refund_amount += item_amount
                refunds.append(
                    base_row(refund_id, f"REFUND-{refund_id}")
                    | {
                        "order_id": order_id,
                        "refund_no": f"RF-{refund_id:09d}",
                        "refund_status": "REFUNDED",
                        "requested_at": refunded_at - timedelta(days=1),
                        "refunded_at": refunded_at,
                        "refund_amount": refund_amount,
                    }
                )
                for position, item in enumerate(refunded_items, start=1):
                    refund_item_id = (refund_id - 1) * 2 + position
                    refund_items.append(
                        base_row(refund_item_id, f"REFUND-ITEM-{refund_item_id}")
                        | {
                            "refund_id": refund_id,
                            "order_item_id": item["id"],
                            "refund_quantity": Decimal("1.000"),
                            "refund_amount": item["net_amount"],
                            "reason_code": "CUSTOMER_RETURN",
                        }
                    )
        yield OrderBatch(orders, items, payments, refunds, refund_items)

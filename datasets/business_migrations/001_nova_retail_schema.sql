SET lock_timeout = '10s';

SET statement_timeout = '5min';

CREATE TABLE public."dim_region" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "region_code" varchar(16) NOT NULL,
  "region_name" varchar(64) NOT NULL,
  "country_code" char(2) NOT NULL,
  "manager_employee_no" varchar(32) NOT NULL,
  "status" varchar(16) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("status" IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE public."dim_city" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "city_code" varchar(16) NOT NULL,
  "city_name" varchar(64) NOT NULL,
  "province_name" varchar(64) NOT NULL,
  "region_id" bigint NOT NULL,
  "timezone" varchar(48) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_store" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "store_code" varchar(24) NOT NULL,
  "store_name" varchar(128) NOT NULL,
  "city_id" bigint NOT NULL,
  "store_type" varchar(24) NOT NULL,
  "opened_on" date NOT NULL,
  "closed_on" date,
  PRIMARY KEY ("id"),
  CHECK ("store_type" IN ('FLAGSHIP', 'STANDARD', 'OUTLET'))
);

CREATE TABLE public."dim_warehouse" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "warehouse_code" varchar(24) NOT NULL,
  "warehouse_name" varchar(128) NOT NULL,
  "city_id" bigint NOT NULL,
  "warehouse_type" varchar(24) NOT NULL,
  "capacity_units" integer NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."bridge_store_region_history" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "store_id" bigint NOT NULL,
  "region_id" bigint NOT NULL,
  "valid_from_date" date NOT NULL,
  "valid_to_date" date,
  "change_reason" varchar(128),
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_sales_channel" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "channel_code" varchar(16) NOT NULL,
  "channel_name" varchar(64) NOT NULL,
  "channel_group" varchar(32) NOT NULL,
  "is_online" boolean NOT NULL,
  "status" varchar(16) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("status" IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE public."store_operating_calendar" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "store_id" bigint NOT NULL,
  "calendar_date" date NOT NULL,
  "is_open" boolean NOT NULL,
  "open_time" time,
  "close_time" time,
  "holiday_name" varchar(64),
  PRIMARY KEY ("id")
);

CREATE TABLE public."store_target" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "store_id" bigint NOT NULL,
  "target_month" date NOT NULL,
  "metric_code" varchar(32) NOT NULL,
  "target_value" numeric(18,2) NOT NULL,
  "approved_version" integer NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_brand" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "brand_code" varchar(24) NOT NULL,
  "brand_name" varchar(128) NOT NULL,
  "brand_name_zh" varchar(128),
  "country_code" char(2) NOT NULL,
  "status" varchar(16) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("status" IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE public."dim_category" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "category_code" varchar(24) NOT NULL,
  "category_name" varchar(128) NOT NULL,
  "parent_category_id" bigint,
  "category_level" smallint NOT NULL,
  "path_code" varchar(256) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_product" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "product_code" varchar(32) NOT NULL,
  "product_name" varchar(256) NOT NULL,
  "brand_id" bigint NOT NULL,
  "primary_category_id" bigint NOT NULL,
  "product_status" varchar(16) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("product_status" IN ('DRAFT', 'ACTIVE', 'DISCONTINUED'))
);

CREATE TABLE public."dim_sku" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "sku_code" varchar(32) NOT NULL,
  "product_id" bigint NOT NULL,
  "barcode" varchar(32),
  "color_name" varchar(64),
  "size_name" varchar(64),
  "list_price" numeric(18,2) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."product_category_history" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "product_id" bigint NOT NULL,
  "category_id" bigint NOT NULL,
  "valid_from_date" date NOT NULL,
  "valid_to_date" date,
  "is_primary" boolean NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."product_price_history" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "sku_id" bigint NOT NULL,
  "price_list_code" varchar(24) NOT NULL,
  "currency_code" char(3) NOT NULL,
  "unit_price" numeric(18,2) NOT NULL,
  "valid_from_at" timestamptz NOT NULL,
  "valid_to_at" timestamptz,
  PRIMARY KEY ("id")
);

CREATE TABLE public."product_supplier_bridge" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "sku_id" bigint NOT NULL,
  "supplier_code" varchar(32) NOT NULL,
  "is_primary_supplier" boolean NOT NULL,
  "lead_time_days" integer NOT NULL,
  "purchase_unit_cost" numeric(18,2) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."product_attribute_value" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "product_id" bigint NOT NULL,
  "attribute_code" varchar(32) NOT NULL,
  "attribute_name" varchar(64) NOT NULL,
  "attribute_value" varchar(256) NOT NULL,
  "value_unit" varchar(24),
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_customer" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "customer_code" varchar(32) NOT NULL,
  "customer_name" varchar(128) NOT NULL,
  "mobile_hash" char(64) NOT NULL,
  "email_hash" char(64),
  "registered_at" timestamptz NOT NULL,
  "status" varchar(16) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("status" IN ('ACTIVE', 'FROZEN', 'DELETED'))
);

CREATE TABLE public."dim_membership_tier" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "tier_code" varchar(16) NOT NULL,
  "tier_name" varchar(64) NOT NULL,
  "minimum_points" integer NOT NULL,
  "discount_rate" numeric(8,4) NOT NULL,
  "rank_order" smallint NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."customer_membership_history" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "customer_id" bigint NOT NULL,
  "tier_id" bigint NOT NULL,
  "valid_from_at" timestamptz NOT NULL,
  "valid_to_at" timestamptz,
  "change_reason" varchar(64) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_customer_tag" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "tag_code" varchar(24) NOT NULL,
  "tag_name" varchar(64) NOT NULL,
  "tag_group" varchar(32) NOT NULL,
  "value_type" varchar(16) NOT NULL,
  "status" varchar(16) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("status" IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE public."bridge_customer_tag" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "customer_id" bigint NOT NULL,
  "tag_id" bigint NOT NULL,
  "tag_value" varchar(256) NOT NULL,
  "assigned_at" timestamptz NOT NULL,
  "expired_at" timestamptz,
  PRIMARY KEY ("id")
);

CREATE TABLE public."customer_address" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "customer_id" bigint NOT NULL,
  "city_id" bigint NOT NULL,
  "address_type" varchar(16) NOT NULL,
  "address_text" varchar(512) NOT NULL,
  "postal_code" varchar(16),
  PRIMARY KEY ("id"),
  CHECK ("address_type" IN ('HOME', 'WORK', 'SHIPPING'))
);

CREATE TABLE public."customer_consent" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "customer_id" bigint NOT NULL,
  "purpose_code" varchar(32) NOT NULL,
  "consent_status" varchar(16) NOT NULL,
  "consented_at" timestamptz NOT NULL,
  "withdrawn_at" timestamptz,
  PRIMARY KEY ("id"),
  CHECK ("consent_status" IN ('GRANTED', 'DENIED', 'WITHDRAWN'))
);

CREATE TABLE public."customer_identity_map" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "customer_id" bigint NOT NULL,
  "identity_type" varchar(24) NOT NULL,
  "identity_hash" char(64) NOT NULL,
  "linked_at" timestamptz NOT NULL,
  "confidence" numeric(5,4) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_order" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_no" varchar(32) NOT NULL,
  "customer_id" bigint,
  "store_id" bigint,
  "channel_id" bigint NOT NULL,
  "ordered_at" timestamptz NOT NULL,
  "paid_at" timestamptz,
  "order_status" varchar(20) NOT NULL,
  "is_test" boolean NOT NULL,
  "order_amount" numeric(18,2) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("order_status" IN ('CREATED', 'PAID', 'CANCELLED', 'COMPLETED'))
);

CREATE TABLE public."fact_order_item" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_id" bigint NOT NULL,
  "line_no" integer NOT NULL,
  "sku_id" bigint NOT NULL,
  "quantity" numeric(18,3) NOT NULL,
  "gross_amount" numeric(18,2) NOT NULL,
  "discount_amount" numeric(18,2) NOT NULL,
  "net_amount" numeric(18,2) NOT NULL,
  "tax_amount" numeric(18,2) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_payment" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_id" bigint NOT NULL,
  "payment_no" varchar(40) NOT NULL,
  "payment_method" varchar(24) NOT NULL,
  "payment_status" varchar(16) NOT NULL,
  "paid_amount" numeric(18,2) NOT NULL,
  "paid_at" timestamptz,
  PRIMARY KEY ("id"),
  CHECK ("payment_status" IN ('PENDING', 'SUCCEEDED', 'FAILED', 'REVERSED'))
);

CREATE TABLE public."fact_refund" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_id" bigint NOT NULL,
  "refund_no" varchar(40) NOT NULL,
  "refund_status" varchar(16) NOT NULL,
  "requested_at" timestamptz NOT NULL,
  "refunded_at" timestamptz,
  "refund_amount" numeric(18,2) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("refund_status" IN ('REQUESTED', 'APPROVED', 'REFUNDED', 'REJECTED'))
);

CREATE TABLE public."fact_refund_item" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "refund_id" bigint NOT NULL,
  "order_item_id" bigint NOT NULL,
  "refund_quantity" numeric(18,3) NOT NULL,
  "refund_amount" numeric(18,2) NOT NULL,
  "reason_code" varchar(24) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."order_status_history" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_id" bigint NOT NULL,
  "from_status" varchar(20),
  "to_status" varchar(20) NOT NULL,
  "changed_at" timestamptz NOT NULL,
  "operator_type" varchar(16) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."order_coupon_bridge" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_id" bigint NOT NULL,
  "coupon_id" bigint NOT NULL,
  "redemption_id" bigint,
  "allocated_discount" numeric(18,2) NOT NULL,
  "applied_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."sales_daily_aggregate" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "sales_date" date NOT NULL,
  "store_id" bigint NOT NULL,
  "sku_id" bigint NOT NULL,
  "paid_order_count" integer NOT NULL,
  "sales_quantity" numeric(18,3) NOT NULL,
  "net_sales_amount" numeric(18,2) NOT NULL,
  "refund_amount" numeric(18,2) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_inventory_movement" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "warehouse_id" bigint NOT NULL,
  "sku_id" bigint NOT NULL,
  "movement_type" varchar(24) NOT NULL,
  "quantity_delta" numeric(18,3) NOT NULL,
  "occurred_at" timestamptz NOT NULL,
  "reference_no" varchar(40) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("movement_type" IN ('RECEIPT', 'SALE', 'RETURN', 'TRANSFER', 'ADJUSTMENT'))
);

CREATE TABLE public."fact_inventory_snapshot" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "snapshot_date" date NOT NULL,
  "warehouse_id" bigint NOT NULL,
  "sku_id" bigint NOT NULL,
  "on_hand_quantity" numeric(18,3) NOT NULL,
  "reserved_quantity" numeric(18,3) NOT NULL,
  "available_quantity" numeric(18,3) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_stocktake" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "stocktake_no" varchar(32) NOT NULL,
  "warehouse_id" bigint NOT NULL,
  "stocktake_status" varchar(16) NOT NULL,
  "started_at" timestamptz NOT NULL,
  "counted_at" timestamptz,
  PRIMARY KEY ("id"),
  CHECK ("stocktake_status" IN ('PLANNED', 'COUNTING', 'COMPLETED', 'CANCELLED'))
);

CREATE TABLE public."fact_stocktake_item" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "stocktake_id" bigint NOT NULL,
  "sku_id" bigint NOT NULL,
  "system_quantity" numeric(18,3) NOT NULL,
  "counted_quantity" numeric(18,3) NOT NULL,
  "variance_quantity" numeric(18,3) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."inventory_reservation" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_item_id" bigint NOT NULL,
  "warehouse_id" bigint NOT NULL,
  "sku_id" bigint NOT NULL,
  "reserved_quantity" numeric(18,3) NOT NULL,
  "reservation_status" varchar(16) NOT NULL,
  "reserved_at" timestamptz NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("reservation_status" IN ('HELD', 'RELEASED', 'CONSUMED', 'EXPIRED'))
);

CREATE TABLE public."inventory_transfer" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "transfer_no" varchar(32) NOT NULL,
  "from_warehouse_id" bigint NOT NULL,
  "to_warehouse_id" bigint NOT NULL,
  "transfer_status" varchar(16) NOT NULL,
  "shipped_at" timestamptz,
  "received_at" timestamptz,
  PRIMARY KEY ("id"),
  CHECK ("transfer_status" IN ('CREATED', 'SHIPPED', 'RECEIVED', 'CANCELLED'))
);

CREATE TABLE public."inventory_transfer_item" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "transfer_id" bigint NOT NULL,
  "sku_id" bigint NOT NULL,
  "requested_quantity" numeric(18,3) NOT NULL,
  "shipped_quantity" numeric(18,3) NOT NULL,
  "received_quantity" numeric(18,3) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."inventory_reorder_policy" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "warehouse_id" bigint NOT NULL,
  "sku_id" bigint NOT NULL,
  "reorder_point" numeric(18,3) NOT NULL,
  "target_stock" numeric(18,3) NOT NULL,
  "lead_time_days" integer NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_revenue_ledger" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_id" bigint,
  "account_id" bigint NOT NULL,
  "cost_center_id" bigint NOT NULL,
  "currency_code" char(3) NOT NULL,
  "amount" numeric(18,2) NOT NULL,
  "posted_at" timestamptz NOT NULL,
  "fiscal_period" varchar(7) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_cost_ledger" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "order_item_id" bigint,
  "sku_id" bigint,
  "account_id" bigint NOT NULL,
  "cost_center_id" bigint NOT NULL,
  "amount" numeric(18,2) NOT NULL,
  "posted_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_expense_ledger" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "account_id" bigint NOT NULL,
  "cost_center_id" bigint NOT NULL,
  "campaign_id" bigint,
  "expense_type" varchar(24) NOT NULL,
  "amount" numeric(18,2) NOT NULL,
  "posted_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_account" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "account_code" varchar(24) NOT NULL,
  "account_name" varchar(128) NOT NULL,
  "account_type" varchar(24) NOT NULL,
  "parent_account_id" bigint,
  "normal_balance" varchar(8) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("normal_balance" IN ('DEBIT', 'CREDIT'))
);

CREATE TABLE public."dim_cost_center" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "cost_center_code" varchar(24) NOT NULL,
  "cost_center_name" varchar(128) NOT NULL,
  "region_id" bigint,
  "store_id" bigint,
  "manager_employee_no" varchar(32) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."currency_rate_daily" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "rate_date" date NOT NULL,
  "base_currency" char(3) NOT NULL,
  "quote_currency" char(3) NOT NULL,
  "exchange_rate" numeric(20,8) NOT NULL,
  "rate_source" varchar(32) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."settlement_batch" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "settlement_no" varchar(40) NOT NULL,
  "channel_id" bigint NOT NULL,
  "settlement_status" varchar(16) NOT NULL,
  "period_start" date NOT NULL,
  "period_end" date NOT NULL,
  "settled_at" timestamptz,
  PRIMARY KEY ("id"),
  CHECK ("settlement_status" IN ('OPEN', 'MATCHED', 'SETTLED', 'DISPUTED'))
);

CREATE TABLE public."settlement_item" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "settlement_batch_id" bigint NOT NULL,
  "payment_id" bigint,
  "refund_id" bigint,
  "gross_amount" numeric(18,2) NOT NULL,
  "fee_amount" numeric(18,2) NOT NULL,
  "net_amount" numeric(18,2) NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."dim_campaign" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "campaign_code" varchar(24) NOT NULL,
  "campaign_name" varchar(128) NOT NULL,
  "channel_id" bigint NOT NULL,
  "campaign_status" varchar(16) NOT NULL,
  "start_at" timestamptz NOT NULL,
  "end_at" timestamptz NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("campaign_status" IN ('DRAFT', 'ACTIVE', 'ENDED', 'CANCELLED'))
);

CREATE TABLE public."dim_marketing_channel" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "channel_code" varchar(24) NOT NULL,
  "channel_name" varchar(64) NOT NULL,
  "channel_type" varchar(24) NOT NULL,
  "vendor_name" varchar(128),
  "status" varchar(16) NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("status" IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE public."dim_coupon" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "coupon_code" varchar(32) NOT NULL,
  "coupon_name" varchar(128) NOT NULL,
  "discount_type" varchar(16) NOT NULL,
  "discount_value" numeric(18,2) NOT NULL,
  "valid_from_at" timestamptz NOT NULL,
  "valid_to_at" timestamptz NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("discount_type" IN ('AMOUNT', 'PERCENT', 'FREE_SHIPPING'))
);

CREATE TABLE public."campaign_product_bridge" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "campaign_id" bigint NOT NULL,
  "product_id" bigint,
  "category_id" bigint,
  "inclusion_type" varchar(16) NOT NULL,
  "priority" integer NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("inclusion_type" IN ('INCLUDE', 'EXCLUDE'))
);

CREATE TABLE public."campaign_customer_segment" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "campaign_id" bigint NOT NULL,
  "segment_code" varchar(32) NOT NULL,
  "segment_name" varchar(128) NOT NULL,
  "rule_json" jsonb NOT NULL,
  "generated_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);

CREATE TABLE public."fact_campaign_touch" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "campaign_id" bigint NOT NULL,
  "customer_id" bigint NOT NULL,
  "marketing_channel_id" bigint NOT NULL,
  "touch_type" varchar(24) NOT NULL,
  "touch_status" varchar(16) NOT NULL,
  "touched_at" timestamptz NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("touch_status" IN ('SENT', 'DELIVERED', 'OPENED', 'FAILED'))
);

CREATE TABLE public."fact_coupon_redemption" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "coupon_id" bigint NOT NULL,
  "customer_id" bigint,
  "order_id" bigint,
  "redemption_status" varchar(16) NOT NULL,
  "discount_amount" numeric(18,2) NOT NULL,
  "redeemed_at" timestamptz NOT NULL,
  PRIMARY KEY ("id"),
  CHECK ("redemption_status" IN ('RESERVED', 'REDEEMED', 'REVERSED'))
);

CREATE TABLE public."fact_marketing_spend" (
  "id" bigint NOT NULL,
  "tenant_id" bigint NOT NULL,
  "source_system" varchar(32) NOT NULL,
  "source_record_id" varchar(64) NOT NULL,
  "effective_from" date NOT NULL,
  "effective_to" date,
  "is_current" boolean NOT NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  "campaign_id" bigint NOT NULL,
  "marketing_channel_id" bigint NOT NULL,
  "spend_date" date NOT NULL,
  "impressions" bigint NOT NULL,
  "clicks" bigint NOT NULL,
  "spend_amount" numeric(18,2) NOT NULL,
  "currency_code" char(3) NOT NULL,
  PRIMARY KEY ("id")
);

ALTER TABLE public."dim_city" ADD CONSTRAINT "fk_dim_city_region_id" FOREIGN KEY ("region_id") REFERENCES public."dim_region" ("id");

CREATE INDEX "idx_dim_city_region_id" ON public."dim_city" ("region_id");

ALTER TABLE public."dim_store" ADD CONSTRAINT "fk_dim_store_city_id" FOREIGN KEY ("city_id") REFERENCES public."dim_city" ("id");

CREATE INDEX "idx_dim_store_city_id" ON public."dim_store" ("city_id");

ALTER TABLE public."dim_warehouse" ADD CONSTRAINT "fk_dim_warehouse_city_id" FOREIGN KEY ("city_id") REFERENCES public."dim_city" ("id");

CREATE INDEX "idx_dim_warehouse_city_id" ON public."dim_warehouse" ("city_id");

ALTER TABLE public."bridge_store_region_history" ADD CONSTRAINT "fk_bridge_store_region_history_store_id" FOREIGN KEY ("store_id") REFERENCES public."dim_store" ("id");

CREATE INDEX "idx_bridge_store_region_history_store_id" ON public."bridge_store_region_history" ("store_id");

ALTER TABLE public."bridge_store_region_history" ADD CONSTRAINT "fk_bridge_store_region_history_region_id" FOREIGN KEY ("region_id") REFERENCES public."dim_region" ("id");

CREATE INDEX "idx_bridge_store_region_history_region_id" ON public."bridge_store_region_history" ("region_id");

ALTER TABLE public."store_operating_calendar" ADD CONSTRAINT "fk_store_operating_calendar_store_id" FOREIGN KEY ("store_id") REFERENCES public."dim_store" ("id");

CREATE INDEX "idx_store_operating_calendar_store_id" ON public."store_operating_calendar" ("store_id");

ALTER TABLE public."store_target" ADD CONSTRAINT "fk_store_target_store_id" FOREIGN KEY ("store_id") REFERENCES public."dim_store" ("id");

CREATE INDEX "idx_store_target_store_id" ON public."store_target" ("store_id");

ALTER TABLE public."dim_category" ADD CONSTRAINT "fk_dim_category_parent_category_id" FOREIGN KEY ("parent_category_id") REFERENCES public."dim_category" ("id");

CREATE INDEX "idx_dim_category_parent_category_id" ON public."dim_category" ("parent_category_id");

ALTER TABLE public."dim_product" ADD CONSTRAINT "fk_dim_product_brand_id" FOREIGN KEY ("brand_id") REFERENCES public."dim_brand" ("id");

CREATE INDEX "idx_dim_product_brand_id" ON public."dim_product" ("brand_id");

ALTER TABLE public."dim_product" ADD CONSTRAINT "fk_dim_product_primary_category_id" FOREIGN KEY ("primary_category_id") REFERENCES public."dim_category" ("id");

CREATE INDEX "idx_dim_product_primary_category_id" ON public."dim_product" ("primary_category_id");

ALTER TABLE public."dim_sku" ADD CONSTRAINT "fk_dim_sku_product_id" FOREIGN KEY ("product_id") REFERENCES public."dim_product" ("id");

CREATE INDEX "idx_dim_sku_product_id" ON public."dim_sku" ("product_id");

ALTER TABLE public."product_category_history" ADD CONSTRAINT "fk_product_category_history_product_id" FOREIGN KEY ("product_id") REFERENCES public."dim_product" ("id");

CREATE INDEX "idx_product_category_history_product_id" ON public."product_category_history" ("product_id");

ALTER TABLE public."product_category_history" ADD CONSTRAINT "fk_product_category_history_category_id" FOREIGN KEY ("category_id") REFERENCES public."dim_category" ("id");

CREATE INDEX "idx_product_category_history_category_id" ON public."product_category_history" ("category_id");

ALTER TABLE public."product_price_history" ADD CONSTRAINT "fk_product_price_history_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_product_price_history_sku_id" ON public."product_price_history" ("sku_id");

ALTER TABLE public."product_supplier_bridge" ADD CONSTRAINT "fk_product_supplier_bridge_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_product_supplier_bridge_sku_id" ON public."product_supplier_bridge" ("sku_id");

ALTER TABLE public."product_attribute_value" ADD CONSTRAINT "fk_product_attribute_value_product_id" FOREIGN KEY ("product_id") REFERENCES public."dim_product" ("id");

CREATE INDEX "idx_product_attribute_value_product_id" ON public."product_attribute_value" ("product_id");

ALTER TABLE public."customer_membership_history" ADD CONSTRAINT "fk_customer_membership_history_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_customer_membership_history_customer_id" ON public."customer_membership_history" ("customer_id");

ALTER TABLE public."customer_membership_history" ADD CONSTRAINT "fk_customer_membership_history_tier_id" FOREIGN KEY ("tier_id") REFERENCES public."dim_membership_tier" ("id");

CREATE INDEX "idx_customer_membership_history_tier_id" ON public."customer_membership_history" ("tier_id");

ALTER TABLE public."bridge_customer_tag" ADD CONSTRAINT "fk_bridge_customer_tag_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_bridge_customer_tag_customer_id" ON public."bridge_customer_tag" ("customer_id");

ALTER TABLE public."bridge_customer_tag" ADD CONSTRAINT "fk_bridge_customer_tag_tag_id" FOREIGN KEY ("tag_id") REFERENCES public."dim_customer_tag" ("id");

CREATE INDEX "idx_bridge_customer_tag_tag_id" ON public."bridge_customer_tag" ("tag_id");

ALTER TABLE public."customer_address" ADD CONSTRAINT "fk_customer_address_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_customer_address_customer_id" ON public."customer_address" ("customer_id");

ALTER TABLE public."customer_address" ADD CONSTRAINT "fk_customer_address_city_id" FOREIGN KEY ("city_id") REFERENCES public."dim_city" ("id");

CREATE INDEX "idx_customer_address_city_id" ON public."customer_address" ("city_id");

ALTER TABLE public."customer_consent" ADD CONSTRAINT "fk_customer_consent_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_customer_consent_customer_id" ON public."customer_consent" ("customer_id");

ALTER TABLE public."customer_identity_map" ADD CONSTRAINT "fk_customer_identity_map_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_customer_identity_map_customer_id" ON public."customer_identity_map" ("customer_id");

ALTER TABLE public."fact_order" ADD CONSTRAINT "fk_fact_order_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_fact_order_customer_id" ON public."fact_order" ("customer_id");

ALTER TABLE public."fact_order" ADD CONSTRAINT "fk_fact_order_store_id" FOREIGN KEY ("store_id") REFERENCES public."dim_store" ("id");

CREATE INDEX "idx_fact_order_store_id" ON public."fact_order" ("store_id");

ALTER TABLE public."fact_order" ADD CONSTRAINT "fk_fact_order_channel_id" FOREIGN KEY ("channel_id") REFERENCES public."dim_sales_channel" ("id");

CREATE INDEX "idx_fact_order_channel_id" ON public."fact_order" ("channel_id");

ALTER TABLE public."fact_order_item" ADD CONSTRAINT "fk_fact_order_item_order_id" FOREIGN KEY ("order_id") REFERENCES public."fact_order" ("id");

CREATE INDEX "idx_fact_order_item_order_id" ON public."fact_order_item" ("order_id");

ALTER TABLE public."fact_order_item" ADD CONSTRAINT "fk_fact_order_item_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_fact_order_item_sku_id" ON public."fact_order_item" ("sku_id");

ALTER TABLE public."fact_payment" ADD CONSTRAINT "fk_fact_payment_order_id" FOREIGN KEY ("order_id") REFERENCES public."fact_order" ("id");

CREATE INDEX "idx_fact_payment_order_id" ON public."fact_payment" ("order_id");

ALTER TABLE public."fact_refund" ADD CONSTRAINT "fk_fact_refund_order_id" FOREIGN KEY ("order_id") REFERENCES public."fact_order" ("id");

CREATE INDEX "idx_fact_refund_order_id" ON public."fact_refund" ("order_id");

ALTER TABLE public."fact_refund_item" ADD CONSTRAINT "fk_fact_refund_item_refund_id" FOREIGN KEY ("refund_id") REFERENCES public."fact_refund" ("id");

CREATE INDEX "idx_fact_refund_item_refund_id" ON public."fact_refund_item" ("refund_id");

ALTER TABLE public."fact_refund_item" ADD CONSTRAINT "fk_fact_refund_item_order_item_id" FOREIGN KEY ("order_item_id") REFERENCES public."fact_order_item" ("id");

CREATE INDEX "idx_fact_refund_item_order_item_id" ON public."fact_refund_item" ("order_item_id");

ALTER TABLE public."order_status_history" ADD CONSTRAINT "fk_order_status_history_order_id" FOREIGN KEY ("order_id") REFERENCES public."fact_order" ("id");

CREATE INDEX "idx_order_status_history_order_id" ON public."order_status_history" ("order_id");

ALTER TABLE public."order_coupon_bridge" ADD CONSTRAINT "fk_order_coupon_bridge_order_id" FOREIGN KEY ("order_id") REFERENCES public."fact_order" ("id");

CREATE INDEX "idx_order_coupon_bridge_order_id" ON public."order_coupon_bridge" ("order_id");

ALTER TABLE public."order_coupon_bridge" ADD CONSTRAINT "fk_order_coupon_bridge_coupon_id" FOREIGN KEY ("coupon_id") REFERENCES public."dim_coupon" ("id");

CREATE INDEX "idx_order_coupon_bridge_coupon_id" ON public."order_coupon_bridge" ("coupon_id");

ALTER TABLE public."order_coupon_bridge" ADD CONSTRAINT "fk_order_coupon_bridge_redemption_id" FOREIGN KEY ("redemption_id") REFERENCES public."fact_coupon_redemption" ("id");

CREATE INDEX "idx_order_coupon_bridge_redemption_id" ON public."order_coupon_bridge" ("redemption_id");

ALTER TABLE public."sales_daily_aggregate" ADD CONSTRAINT "fk_sales_daily_aggregate_store_id" FOREIGN KEY ("store_id") REFERENCES public."dim_store" ("id");

CREATE INDEX "idx_sales_daily_aggregate_store_id" ON public."sales_daily_aggregate" ("store_id");

ALTER TABLE public."sales_daily_aggregate" ADD CONSTRAINT "fk_sales_daily_aggregate_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_sales_daily_aggregate_sku_id" ON public."sales_daily_aggregate" ("sku_id");

ALTER TABLE public."fact_inventory_movement" ADD CONSTRAINT "fk_fact_inventory_movement_warehouse_id" FOREIGN KEY ("warehouse_id") REFERENCES public."dim_warehouse" ("id");

CREATE INDEX "idx_fact_inventory_movement_warehouse_id" ON public."fact_inventory_movement" ("warehouse_id");

ALTER TABLE public."fact_inventory_movement" ADD CONSTRAINT "fk_fact_inventory_movement_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_fact_inventory_movement_sku_id" ON public."fact_inventory_movement" ("sku_id");

ALTER TABLE public."fact_inventory_snapshot" ADD CONSTRAINT "fk_fact_inventory_snapshot_warehouse_id" FOREIGN KEY ("warehouse_id") REFERENCES public."dim_warehouse" ("id");

CREATE INDEX "idx_fact_inventory_snapshot_warehouse_id" ON public."fact_inventory_snapshot" ("warehouse_id");

ALTER TABLE public."fact_inventory_snapshot" ADD CONSTRAINT "fk_fact_inventory_snapshot_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_fact_inventory_snapshot_sku_id" ON public."fact_inventory_snapshot" ("sku_id");

ALTER TABLE public."fact_stocktake" ADD CONSTRAINT "fk_fact_stocktake_warehouse_id" FOREIGN KEY ("warehouse_id") REFERENCES public."dim_warehouse" ("id");

CREATE INDEX "idx_fact_stocktake_warehouse_id" ON public."fact_stocktake" ("warehouse_id");

ALTER TABLE public."fact_stocktake_item" ADD CONSTRAINT "fk_fact_stocktake_item_stocktake_id" FOREIGN KEY ("stocktake_id") REFERENCES public."fact_stocktake" ("id");

CREATE INDEX "idx_fact_stocktake_item_stocktake_id" ON public."fact_stocktake_item" ("stocktake_id");

ALTER TABLE public."fact_stocktake_item" ADD CONSTRAINT "fk_fact_stocktake_item_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_fact_stocktake_item_sku_id" ON public."fact_stocktake_item" ("sku_id");

ALTER TABLE public."inventory_reservation" ADD CONSTRAINT "fk_inventory_reservation_order_item_id" FOREIGN KEY ("order_item_id") REFERENCES public."fact_order_item" ("id");

CREATE INDEX "idx_inventory_reservation_order_item_id" ON public."inventory_reservation" ("order_item_id");

ALTER TABLE public."inventory_reservation" ADD CONSTRAINT "fk_inventory_reservation_warehouse_id" FOREIGN KEY ("warehouse_id") REFERENCES public."dim_warehouse" ("id");

CREATE INDEX "idx_inventory_reservation_warehouse_id" ON public."inventory_reservation" ("warehouse_id");

ALTER TABLE public."inventory_reservation" ADD CONSTRAINT "fk_inventory_reservation_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_inventory_reservation_sku_id" ON public."inventory_reservation" ("sku_id");

ALTER TABLE public."inventory_transfer" ADD CONSTRAINT "fk_inventory_transfer_from_warehouse_id" FOREIGN KEY ("from_warehouse_id") REFERENCES public."dim_warehouse" ("id");

CREATE INDEX "idx_inventory_transfer_from_warehouse_id" ON public."inventory_transfer" ("from_warehouse_id");

ALTER TABLE public."inventory_transfer" ADD CONSTRAINT "fk_inventory_transfer_to_warehouse_id" FOREIGN KEY ("to_warehouse_id") REFERENCES public."dim_warehouse" ("id");

CREATE INDEX "idx_inventory_transfer_to_warehouse_id" ON public."inventory_transfer" ("to_warehouse_id");

ALTER TABLE public."inventory_transfer_item" ADD CONSTRAINT "fk_inventory_transfer_item_transfer_id" FOREIGN KEY ("transfer_id") REFERENCES public."inventory_transfer" ("id");

CREATE INDEX "idx_inventory_transfer_item_transfer_id" ON public."inventory_transfer_item" ("transfer_id");

ALTER TABLE public."inventory_transfer_item" ADD CONSTRAINT "fk_inventory_transfer_item_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_inventory_transfer_item_sku_id" ON public."inventory_transfer_item" ("sku_id");

ALTER TABLE public."inventory_reorder_policy" ADD CONSTRAINT "fk_inventory_reorder_policy_warehouse_id" FOREIGN KEY ("warehouse_id") REFERENCES public."dim_warehouse" ("id");

CREATE INDEX "idx_inventory_reorder_policy_warehouse_id" ON public."inventory_reorder_policy" ("warehouse_id");

ALTER TABLE public."inventory_reorder_policy" ADD CONSTRAINT "fk_inventory_reorder_policy_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_inventory_reorder_policy_sku_id" ON public."inventory_reorder_policy" ("sku_id");

ALTER TABLE public."fact_revenue_ledger" ADD CONSTRAINT "fk_fact_revenue_ledger_order_id" FOREIGN KEY ("order_id") REFERENCES public."fact_order" ("id");

CREATE INDEX "idx_fact_revenue_ledger_order_id" ON public."fact_revenue_ledger" ("order_id");

ALTER TABLE public."fact_revenue_ledger" ADD CONSTRAINT "fk_fact_revenue_ledger_account_id" FOREIGN KEY ("account_id") REFERENCES public."dim_account" ("id");

CREATE INDEX "idx_fact_revenue_ledger_account_id" ON public."fact_revenue_ledger" ("account_id");

ALTER TABLE public."fact_revenue_ledger" ADD CONSTRAINT "fk_fact_revenue_ledger_cost_center_id" FOREIGN KEY ("cost_center_id") REFERENCES public."dim_cost_center" ("id");

CREATE INDEX "idx_fact_revenue_ledger_cost_center_id" ON public."fact_revenue_ledger" ("cost_center_id");

ALTER TABLE public."fact_cost_ledger" ADD CONSTRAINT "fk_fact_cost_ledger_order_item_id" FOREIGN KEY ("order_item_id") REFERENCES public."fact_order_item" ("id");

CREATE INDEX "idx_fact_cost_ledger_order_item_id" ON public."fact_cost_ledger" ("order_item_id");

ALTER TABLE public."fact_cost_ledger" ADD CONSTRAINT "fk_fact_cost_ledger_sku_id" FOREIGN KEY ("sku_id") REFERENCES public."dim_sku" ("id");

CREATE INDEX "idx_fact_cost_ledger_sku_id" ON public."fact_cost_ledger" ("sku_id");

ALTER TABLE public."fact_cost_ledger" ADD CONSTRAINT "fk_fact_cost_ledger_account_id" FOREIGN KEY ("account_id") REFERENCES public."dim_account" ("id");

CREATE INDEX "idx_fact_cost_ledger_account_id" ON public."fact_cost_ledger" ("account_id");

ALTER TABLE public."fact_cost_ledger" ADD CONSTRAINT "fk_fact_cost_ledger_cost_center_id" FOREIGN KEY ("cost_center_id") REFERENCES public."dim_cost_center" ("id");

CREATE INDEX "idx_fact_cost_ledger_cost_center_id" ON public."fact_cost_ledger" ("cost_center_id");

ALTER TABLE public."fact_expense_ledger" ADD CONSTRAINT "fk_fact_expense_ledger_account_id" FOREIGN KEY ("account_id") REFERENCES public."dim_account" ("id");

CREATE INDEX "idx_fact_expense_ledger_account_id" ON public."fact_expense_ledger" ("account_id");

ALTER TABLE public."fact_expense_ledger" ADD CONSTRAINT "fk_fact_expense_ledger_cost_center_id" FOREIGN KEY ("cost_center_id") REFERENCES public."dim_cost_center" ("id");

CREATE INDEX "idx_fact_expense_ledger_cost_center_id" ON public."fact_expense_ledger" ("cost_center_id");

ALTER TABLE public."fact_expense_ledger" ADD CONSTRAINT "fk_fact_expense_ledger_campaign_id" FOREIGN KEY ("campaign_id") REFERENCES public."dim_campaign" ("id");

CREATE INDEX "idx_fact_expense_ledger_campaign_id" ON public."fact_expense_ledger" ("campaign_id");

ALTER TABLE public."dim_account" ADD CONSTRAINT "fk_dim_account_parent_account_id" FOREIGN KEY ("parent_account_id") REFERENCES public."dim_account" ("id");

CREATE INDEX "idx_dim_account_parent_account_id" ON public."dim_account" ("parent_account_id");

ALTER TABLE public."dim_cost_center" ADD CONSTRAINT "fk_dim_cost_center_region_id" FOREIGN KEY ("region_id") REFERENCES public."dim_region" ("id");

CREATE INDEX "idx_dim_cost_center_region_id" ON public."dim_cost_center" ("region_id");

ALTER TABLE public."dim_cost_center" ADD CONSTRAINT "fk_dim_cost_center_store_id" FOREIGN KEY ("store_id") REFERENCES public."dim_store" ("id");

CREATE INDEX "idx_dim_cost_center_store_id" ON public."dim_cost_center" ("store_id");

ALTER TABLE public."settlement_batch" ADD CONSTRAINT "fk_settlement_batch_channel_id" FOREIGN KEY ("channel_id") REFERENCES public."dim_sales_channel" ("id");

CREATE INDEX "idx_settlement_batch_channel_id" ON public."settlement_batch" ("channel_id");

ALTER TABLE public."settlement_item" ADD CONSTRAINT "fk_settlement_item_settlement_batch_id" FOREIGN KEY ("settlement_batch_id") REFERENCES public."settlement_batch" ("id");

CREATE INDEX "idx_settlement_item_settlement_batch_id" ON public."settlement_item" ("settlement_batch_id");

ALTER TABLE public."settlement_item" ADD CONSTRAINT "fk_settlement_item_payment_id" FOREIGN KEY ("payment_id") REFERENCES public."fact_payment" ("id");

CREATE INDEX "idx_settlement_item_payment_id" ON public."settlement_item" ("payment_id");

ALTER TABLE public."settlement_item" ADD CONSTRAINT "fk_settlement_item_refund_id" FOREIGN KEY ("refund_id") REFERENCES public."fact_refund" ("id");

CREATE INDEX "idx_settlement_item_refund_id" ON public."settlement_item" ("refund_id");

ALTER TABLE public."dim_campaign" ADD CONSTRAINT "fk_dim_campaign_channel_id" FOREIGN KEY ("channel_id") REFERENCES public."dim_marketing_channel" ("id");

CREATE INDEX "idx_dim_campaign_channel_id" ON public."dim_campaign" ("channel_id");

ALTER TABLE public."campaign_product_bridge" ADD CONSTRAINT "fk_campaign_product_bridge_campaign_id" FOREIGN KEY ("campaign_id") REFERENCES public."dim_campaign" ("id");

CREATE INDEX "idx_campaign_product_bridge_campaign_id" ON public."campaign_product_bridge" ("campaign_id");

ALTER TABLE public."campaign_product_bridge" ADD CONSTRAINT "fk_campaign_product_bridge_product_id" FOREIGN KEY ("product_id") REFERENCES public."dim_product" ("id");

CREATE INDEX "idx_campaign_product_bridge_product_id" ON public."campaign_product_bridge" ("product_id");

ALTER TABLE public."campaign_product_bridge" ADD CONSTRAINT "fk_campaign_product_bridge_category_id" FOREIGN KEY ("category_id") REFERENCES public."dim_category" ("id");

CREATE INDEX "idx_campaign_product_bridge_category_id" ON public."campaign_product_bridge" ("category_id");

ALTER TABLE public."campaign_customer_segment" ADD CONSTRAINT "fk_campaign_customer_segment_campaign_id" FOREIGN KEY ("campaign_id") REFERENCES public."dim_campaign" ("id");

CREATE INDEX "idx_campaign_customer_segment_campaign_id" ON public."campaign_customer_segment" ("campaign_id");

ALTER TABLE public."fact_campaign_touch" ADD CONSTRAINT "fk_fact_campaign_touch_campaign_id" FOREIGN KEY ("campaign_id") REFERENCES public."dim_campaign" ("id");

CREATE INDEX "idx_fact_campaign_touch_campaign_id" ON public."fact_campaign_touch" ("campaign_id");

ALTER TABLE public."fact_campaign_touch" ADD CONSTRAINT "fk_fact_campaign_touch_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_fact_campaign_touch_customer_id" ON public."fact_campaign_touch" ("customer_id");

ALTER TABLE public."fact_campaign_touch" ADD CONSTRAINT "fk_fact_campaign_touch_marketing_channel_id" FOREIGN KEY ("marketing_channel_id") REFERENCES public."dim_marketing_channel" ("id");

CREATE INDEX "idx_fact_campaign_touch_marketing_channel_id" ON public."fact_campaign_touch" ("marketing_channel_id");

ALTER TABLE public."fact_coupon_redemption" ADD CONSTRAINT "fk_fact_coupon_redemption_coupon_id" FOREIGN KEY ("coupon_id") REFERENCES public."dim_coupon" ("id");

CREATE INDEX "idx_fact_coupon_redemption_coupon_id" ON public."fact_coupon_redemption" ("coupon_id");

ALTER TABLE public."fact_coupon_redemption" ADD CONSTRAINT "fk_fact_coupon_redemption_customer_id" FOREIGN KEY ("customer_id") REFERENCES public."dim_customer" ("id");

CREATE INDEX "idx_fact_coupon_redemption_customer_id" ON public."fact_coupon_redemption" ("customer_id");

ALTER TABLE public."fact_coupon_redemption" ADD CONSTRAINT "fk_fact_coupon_redemption_order_id" FOREIGN KEY ("order_id") REFERENCES public."fact_order" ("id");

CREATE INDEX "idx_fact_coupon_redemption_order_id" ON public."fact_coupon_redemption" ("order_id");

ALTER TABLE public."fact_marketing_spend" ADD CONSTRAINT "fk_fact_marketing_spend_campaign_id" FOREIGN KEY ("campaign_id") REFERENCES public."dim_campaign" ("id");

CREATE INDEX "idx_fact_marketing_spend_campaign_id" ON public."fact_marketing_spend" ("campaign_id");

ALTER TABLE public."fact_marketing_spend" ADD CONSTRAINT "fk_fact_marketing_spend_marketing_channel_id" FOREIGN KEY ("marketing_channel_id") REFERENCES public."dim_marketing_channel" ("id");

CREATE INDEX "idx_fact_marketing_spend_marketing_channel_id" ON public."fact_marketing_spend" ("marketing_channel_id");

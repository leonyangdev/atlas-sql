# Verified Query Repository

可信查询样例库。每条样例经过语法校验和人工审核后，进入 `VERIFIED` 状态，
可被 SQL 生成阶段动态召回作为 few-shot 示例。

## 文件结构

```
benchmarks/verified/
├── README.md
├── sales.yaml          # Sales 域样例（~80 条）
├── customer.yaml       # Customer 域样例（~40 条）
├── finance.yaml        # Finance 域（~20 条，含敏感指标）
├── inventory.yaml      # Inventory 域（~20 条）
├── marketing.yaml      # Marketing 域（~20 条）
├── store.yaml          # Store 域（~20 条）
└── test_locked.yaml    # 锁定测试集（不可被 few-shot 召回）
```

## 隔离规则

1. `is_test_locked: true` 的样例属于锁定测试集，**不可被 few-shot 召回**，防止题库污染。
2. 近似重复问题（trigram 相似度 ≥ 0.85）在导入时会触发警告，由审核人决定是否保留。
3. 锁定测试集与 `test_locked.yaml` 中的 Benchmark 黄金集使用相同问题，确保评测可复现。

## 样例格式

```yaml
queries:
  - question: "2026 年上半年销售额是多少？"
    sql: |
      SELECT SUM(foi.net_amount) - COALESCE(SUM(fri.refund_amount), 0) AS net_sales
      FROM fact_order_item foi
      JOIN fact_order fo ON fo.id = foi.order_id
      LEFT JOIN fact_refund_item fri ON fri.order_item_id = foi.id
      LEFT JOIN fact_refund fr ON fr.id = fri.refund_id
        AND fr.refund_status = 'REFUNDED'
      WHERE fo.order_status IN ('PAID', 'COMPLETED')
        AND fo.is_test = false
        AND fo.paid_at >= TIMESTAMPTZ '2026-01-01 00:00:00+08:00'
        AND fo.paid_at < TIMESTAMPTZ '2026-07-01 00:00:00+08:00'
    domain: sales
    tags: [net_sales, 时间过滤, 半年]
    dependent_metric_ids: [net_sales]
    is_test_locked: false
```

# 贯穿案例：华东销售额同比

> 这是 V4 目标流程的教学走查，不是当前可运行接口。数值、字段和版本仅用于说明；真实实现与 Gold SQL 在各期开发时补齐。

用户问题：**“2026 年上半年华东区销售额同比增长多少？”** 用户是一位华东区域经理。

## 1. 先固定业务假设

教学假设：`net_amount` 已按经过审核的上半年净销售规则准备；不再额外连接退款表重复扣减。收入单位为人民币，日期按已确认的 `order_date` 口径，业务时区为 Asia/Shanghai。有效订单为 PAID 且非测试。真实生产口径必须由 V0/V3 的指标定义替换这些假设。

两段时间采用左闭右开：2026-01-01 至 2026-07-01，2025-01-01 至 2025-07-01。若业务要求退款按退款发生日计，则需要重做指标与计划，不能只替换字段名。

## 2. 理解与链接的输出

```json
{
  "intent": "analytical_query",
  "domain_ids": ["sales", "store"],
  "metric_ids": ["net_sales"],
  "dimension_ids": [],
  "filters": [{"dimension_id": "region", "value": "华东"}],
  "current": ["2026-01-01", "2026-07-01"],
  "comparison": ["2025-01-01", "2025-07-01"],
  "operation": "year_over_year",
  "unresolved": []
}
```

Retrieval 先找可能相关的表列。Linking 再确认“销售额 → metric.net_sales”“华东 → region 字段和值”。Join Graph 补齐明细 → 订单 → 门店 → 城市 → 区域；这些中间表可能在文字召回中并不靠前。

授权先限制候选范围，计划中还要包含服务端确认的行权限。若用户改问华南，不能只把用户问题过滤改回华东后伪装成回答华南；应明确拒绝或说明范围。

## 3. 语义和计划

SemanticContext 带上已发布指标版本、表达式、强制过滤、日期角色和允许维度。IR 表达“分别算两期净销售额，再求差值比例”，不是把任意 SQL 当作计划。

```text
period_sales(current) ─┐
                      ├─ delta = current - previous
period_sales(previous)┘  yoy = delta / previous（previous 非 0）
```

空值与零是不同状态：没有上年记录意味着没有比较基线；上年销售额恰好零意味着增长率分母为零。系统都应说明不可计算原因，而不是输出 0%。

## 4. SQL 形态示例

下面只是教学示例。`:current_start` 等是参数占位；业务实现应使用驱动参数绑定，禁止拼接用户值。已假设各维度键唯一，SCD2 需使用正确历史键。

```sql
WITH period_sales AS (
  SELECT
    SUM(CASE
      WHEN o.order_date >= :current_start
       AND o.order_date < :current_end
      THEN i.net_amount END) AS current_sales,
    SUM(CASE
      WHEN o.order_date >= :previous_start
       AND o.order_date < :previous_end
      THEN i.net_amount END) AS previous_sales
  FROM fact_order_item i
  JOIN fact_order o ON o.id = i.order_id
  JOIN dim_store s ON s.id = o.store_id
  JOIN dim_city c ON c.id = s.city_id
  JOIN dim_region r ON r.id = c.region_id
  WHERE o.status = 'PAID'
    AND o.is_test = false
    AND r.id = :authorized_region_id
    AND (
      (o.order_date >= :current_start AND o.order_date < :current_end)
      OR
      (o.order_date >= :previous_start AND o.order_date < :previous_end)
    )
)
SELECT current_sales, previous_sales,
       (current_sales - previous_sales)
       / NULLIF(previous_sales, 0) AS yoy
FROM period_sales;
```

`authorized_region_id` 必须由服务端策略绑定；示例中的一个 WHERE 条件不能代替完整权限引擎、AST 血缘分析和数据库防线。金额采用 decimal 类型，避免整数除法和浮点金额误差。

## 5. 先校验，再执行，再验证结果

| 检查点 | 检查内容 | 失败出口 |
| --- | --- | --- |
| IR | 指标、时间角色、维度是否一致 | 澄清或计划失败 |
| AST | 单条只读、已知表列、安全函数、正确 Join | 拒绝 |
| Policy | 区域范围、列血缘、权限版本 | 拒绝，禁止修复 |
| EXPLAIN | 估算成本、计划风险 | 拒绝或要求缩小范围 |
| Executor | 只读事务、超时、并发、行数 | 分类错误或取消 |
| Result Validator | 指标规则、粒度、NULL、重复 | 警告或失败 |
| Answer | 数值和结论是否有结果证据 | 不输出无根据断言 |

普通语法/类型错误可以最多修复 2 次，每次重新过全链路；权限与安全错误不能修复。

## 6. 用最小夹具手算

假设华东有效明细 2026 上半年为 120、180 元，2025 上半年为 100、100 元；另有一笔华南 999 元、一笔测试单 500 元和一笔取消单 400 元。

期望：本期 300、上期 200、同比 50%。三个额外记录全部排除。再将上期改为 0，增长率应为空并说明不可计算；删除上期记录，则说明无比较数据。加入一条重复桥表关联时，必须由粒度校验或 Gold 对比发现翻倍。

## 7. 学会定位错误

| 症状 | 先检查 | 对应阶段 |
| --- | --- | --- |
| 查到了库存表 | 域与表召回 | V2 |
| 品牌 Apple 没过滤 | Value Linking 与字段绑定 | V2 |
| 金额翻倍 | 关系基数与预聚合 | V2 / V4 |
| 取消单进入销售额 | 指标强制规则 | V3 / V4 |
| 看见华南数据 | 授权上下文、AST 与缓存 key | V4 |
| SQL 正确但摘要胡说 | 结果到文字的证据绑定 | V4 |
| 升级后此题退化 | 逐题差异、版本与回归 | V6 |

这条案例对应多个模块，是阅读真实代码的主路线。下一步看 [模块与契约](../architecture/contracts)。

# AtlasSQL｜企业级 NL2SQL 数据智能分析平台

## 1. 项目概述

### 1.1 项目名称

**AtlasSQL**

Enterprise NL2SQL & Data Intelligence Agent

中文定位：

**企业级自然语言数据分析与智能问数平台**

---

## 2. 项目背景

大型企业的数据通常分散在 ERP、CRM、OMS、WMS、财务、会员、营销等多个业务系统中。

业务人员需要进行数据分析时，通常需要经历：

```text
业务人员提出需求
        ↓
数据分析师理解需求
        ↓
寻找数据表
        ↓
确认指标口径
        ↓
编写 SQL
        ↓
执行查询
        ↓
生成结果
        ↓
业务人员再次确认
```

存在几个典型问题：

1. 企业数据库表数量多、字段复杂，普通业务人员无法直接使用。
2. 同一个业务概念可能跨越多张事实表、维度表。
3. “销售额”“有效客户”“毛利率”等业务指标并不等价于某一个数据库字段。
4. 不同部门对相同指标可能存在不同业务口径。
5. SQL 编写依赖数据分析师和研发人员，人力成本高。
6. 直接让大模型面对完整数据库 Schema，准确率和稳定性不足。
7. LLM 生成 SQL 存在错误查询、越权查询和高成本查询风险。
8. 模型、Prompt、Schema、指标发生变化后，系统可能出现不可感知的准确率回退。

因此 AtlasSQL 的目标不是简单实现：

```text
Natural Language → SQL
```

而是构建：

```text
Natural Language
        ↓
Business Semantics
        ↓
Schema Linking
        ↓
Query Planning
        ↓
Governed SQL
        ↓
Validated Result
```

即：

> **Text → Semantics → SQL → Validated Result**

---

# 3. 项目业务场景

为了覆盖真实企业 NL2SQL 的主要复杂问题，AtlasSQL 模拟一家中大型零售集团：

**NovaRetail Group**

集团同时经营线上商城、线下门店和会员体系。

一期建设以下七个业务域：

| 业务域          | 核心数据          |
| ------------ | ------------- |
| Sales 销售     | 订单、订单明细、付款、退款 |
| Product 商品   | 商品、SKU、品牌、品类  |
| Customer 客户  | 客户、会员等级、客户标签  |
| Store 门店     | 门店、城市、区域      |
| Inventory 库存 | 仓库、库存流水、库存快照  |
| Finance 财务   | 收入、成本、毛利      |
| Marketing 营销 | 活动、渠道、优惠券     |

最终目标数据规模：

```text
7 个业务域

50～80 张核心业务表

600～1000 个字段

数百万～千万级模拟业务数据

30～50 个核心业务指标

500+ NL2SQL Benchmark 问题

200+ Verified Queries
```

该业务模型必须包含：

* 事实表
* 维度表
* 一对一关系
* 一对多关系
* 多对多关系
* 多事实表
* 历史快照表
* 状态字段
* 编码字段
* 枚举字段
* 多时间字段
* 多业务口径
* 敏感字段
* 行级权限
* 列级权限

从数据模型层主动制造真实企业 NL2SQL 难题，而不是建立一个为了让 LLM 容易回答而设计的数据库。

---

# 4. 项目目标

AtlasSQL 最终需要实现六类核心能力。

## 4.1 自然语言问数

用户能够直接输入：

> 2026 年上半年华东区销售额同比增长多少？

> 找出销售额下降超过 10%，但是毛利率提升的城市。

> 苹果手机上个月在哪些城市卖得最好？

> 华南区域本季度新客户数量环比怎么样？

系统自动完成：

```text
问题理解
→ 数据域定位
→ Schema 召回
→ Schema Linking
→ 指标解析
→ Value Linking
→ SQL 生成
→ SQL 校验
→ 权限判断
→ 查询执行
→ 结果校验
→ 自然语言解释
```

---

# 5. 产品形态

AtlasSQL 不仅提供 Chat 页面，同时提供完整管理后台。

系统包括两个主要应用：

```text
AtlasSQL
│
├── Data Analyst
│   └── 面向普通业务用户
│
└── Admin Console
    └── 面向数据管理员 / 数据分析师 / 平台管理员
```

---

# 6. 用户端功能

用户端包括：

### AI 问数

支持自然语言数据查询。

### 多轮分析

例如：

```text
用户：
今年销售额最高的五个城市？

AtlasSQL：
上海、杭州……

用户：
只看华东呢？

用户：
再和去年比较。

用户：
杭州下降主要是什么品类导致的？
```

系统需要正确继承上下文。

### SQL 展示

允许用户查看：

* Generated SQL
* 使用的数据表
* 使用字段
* Join Path
* Metric Definition
* 查询条件

### 数据解释

返回：

```text
销售额：12.8 亿

同比：
+8.4%

主要增长区域：
上海
杭州
苏州
```

### 可视化

根据查询结果自动选择：

* Table
* Bar
* Line
* Pie
* KPI
* Ranking

---

# 7. 管理后台

管理后台必须包括：

```text
DataSource Management
Metadata Management
Business Domain Management
Semantic Model Management
Metric Management
Dimension Management
Business Glossary
Relationship Management
Verified Query Repository
Permission Management
Benchmark Management
Prompt Management
Model Management
Query Trace
Evaluation Dashboard
Failure Analysis
```

这一部分是 AtlasSQL 与普通 NL2SQL Demo 的重要区别。

---

# 8. 企业级总体架构

AtlasSQL 从第一版开始采用完整企业级基础设施：

```text
                        ┌───────────────┐
                        │    Web UI     │
                        │   Next.js     │
                        └───────┬───────┘
                                │
                                ▼
                       ┌────────────────┐
                       │    FastAPI     │
                       │  API Gateway   │
                       └───────┬────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
        Query Orchestrator              Admin Service
                │
                ▼
        Query Understanding
                │
                ▼
           Domain Router
                │
                ▼
        Retrieval Engine
                │
       ┌────────┴─────────┐
       │                  │
       ▼                  ▼
  OpenSearch            Milvus
 BM25 / Keyword       Dense Vector
       │                  │
       └────────┬─────────┘
                ▼
           RRF Fusion
                │
                ▼
            Reranker
                │
                ▼
         Schema Linking
                │
       ┌────────┼────────┐
       ▼        ▼        ▼
    Schema   Semantic  Verified
    Context   Context   Queries
       │        │        │
       └────────┼────────┘
                ▼
         Query Planner
                │
                ▼
               IR
                │
                ▼
          SQL Generator
                │
                ▼
          SQL Validator
             SQLGlot
                │
                ▼
          Policy Engine
                │
                ▼
           SQL Executor
                │
         ┌──────┴──────┐
         │             │
       Error          Result
         │             │
         ▼             ▼
    SQL Repair   Result Validator
                       │
                       ▼
                 Answer Generator
```

---

# 9. 三类核心数据基础设施

这是 AtlasSQL 最重要的基础架构设计之一。

## 9.1 PostgreSQL：Control Plane

PostgreSQL 不承担主要向量搜索。

它负责保存结构化、强一致、需要治理的数据。

包括：

```text
datasource

database

schema

table_metadata

column_metadata

relationships

business_domain

semantic_model

metric_definition

dimension_definition

business_terms

permissions

verified_query

benchmark

evaluation_result

query_history

prompt_version

model_config
```

PostgreSQL 是整个 AtlasSQL 的：

> **Metadata & Governance Control Plane**

---

# 10. Milvus：Semantic Retrieval Engine

Milvus 专门负责 Dense Vector Retrieval。

主要 Collection：

```text
schema_embeddings

semantic_embeddings

verified_query_embeddings

business_term_embeddings

value_embeddings
```

例如：

```text
用户：
“最近卖得最好的苹果手机”
```

Embedding 可以召回：

```text
product.brand_name

product.product_name

sales_order_item

metric.sales_quantity
```

Milvus主要解决：

> **语义相似性召回。**

---

# 11. OpenSearch：Lexical Retrieval Engine

OpenSearch 负责：

```text
BM25

Keyword Retrieval

Field Name Search

Business Term Search

Alias Search

Value Search

Fuzzy Search
```

例如用户输入：

```text
SKU

GMV

VIP

Apple

WH-001

SKU000392
```

这种明确关键词、编码和数据库真实值，Lexical Search 往往比纯 Embedding 更可靠。

因此 AtlasSQL 不采用：

```text
Vector Search Only
```

而采用：

```text
Dense Retrieval
        +
Lexical Retrieval
```

---

# 12. SearchRepository

业务层不能直接：

```python
milvus.search()

opensearch.search()
```

而是统一依赖：

```text
SearchRepository
```

例如：

```python
class SearchRepository:

    async def search_schema(...):
        ...

    async def search_values(...):
        ...

    async def search_semantics(...):
        ...

    async def search_verified_queries(...):
        ...
```

内部实现：

```text
SearchRepository
       │
       ├── MilvusRetriever
       │
       ├── OpenSearchRetriever
       │
       ├── RRFFusion
       │
       └── Reranker
```

这样基础设施实现不会污染业务层。

---

# 13. Hybrid Retrieval

AtlasSQL 默认检索链路：

```text
Question
   │
   ├────────────────────┐
   ▼                    ▼
OpenSearch            Milvus
BM25                  Dense
   │                    │
   ▼                    ▼
Top K                 Top K
   │                    │
   └──────────┬─────────┘
              ▼
             RRF
              │
              ▼
          Top Candidates
              │
              ▼
           Reranker
              │
              ▼
         Final Context
```

采用：

**Hybrid Search + RRF + Reranker**

而不是纯 Vector Search。

---

# 14. Redis

Redis 主要负责：

```text
Query Cache

Schema Cache

Semantic Context Cache

Value Cache

Session Context

Rate Limit

Distributed Lock
```

例如一个数据源的 Schema 不需要每次查询 PostgreSQL。

可以：

```text
PostgreSQL
    ↓
Redis
    ↓
Query Pipeline
```

---

# 15. Metadata Center

Metadata Center 自动从业务数据库采集：

```text
Database

Schema

Table

Column

Primary Key

Foreign Key

Index

Type

Nullable

Comment

Statistics

Sample Value
```

除此之外，还允许人工补充：

```text
Business Name

Business Description

Domain

Grain

Authoritative Source

Sensitivity

Alias
```

例如：

```text
fact_order_item

技术描述：
订单商品明细

Business Grain：
一行代表一个订单中的一个 SKU

Business Domain：
Sales

Authoritative：
销售商品级分析权威事实表
```

Microsoft Fabric 2026 年的数据 Agent 最佳实践同样明确强调 Schema 范围、对象描述、表 Grain、关系、业务术语以及 Example Queries，因为仅凭表名和字段名不足以支撑可靠的企业问数。

---

# 16. Query Understanding

自然语言首先转换成结构化 Query Intent。

例如：

> 找出今年华东地区销售额同比下降超过 10% 的城市。

转换：

```json
{
  "intent": "analytical_query",
  "domain": "sales",
  "metrics": [
    "net_sales"
  ],
  "dimensions": [
    "city"
  ],
  "filters": [
    {
      "field": "region",
      "value": "华东"
    }
  ],
  "time": {
    "period": "2026",
    "comparison": "year_over_year"
  },
  "conditions": [
    {
      "metric": "growth_rate",
      "operator": "<",
      "value": -0.1
    }
  ]
}
```

主要识别：

```text
Intent

Domain

Metric

Dimension

Entity

Filter

Time

Comparison

Aggregation

Ranking

Limit
```

---

# 17. Domain Routing

第一层不直接找表，而是确定问题属于哪个业务域。

例如：

```text
Question
   ↓
Domain Router
   │
   ├── sales       0.96
   ├── finance     0.51
   ├── marketing   0.21
   └── inventory   0.08
```

确定：

```text
domain = sales
```

随后 Schema Retrieval 只允许在：

```text
Sales Domain
+
必要关联 Domain
```

范围内工作。

---

# 18. Schema Retrieval

Schema Retrieval 分为两级。

## Table Retrieval

首先召回相关表。

```text
Question
   ↓
OpenSearch
+
Milvus
   ↓
RRF
   ↓
Top 20
   ↓
Reranker
   ↓
Top 5～10
```

---

## Column Retrieval

随后在候选表内部进一步检索字段。

避免把：

```text
10 张表 × 80 个字段
```

全部交给模型。

最终可能只保留：

```text
5 张表
+
20～40 个关键字段
```

---

# 19. Schema Linking

Schema Retrieval 解决：

> 哪些 Schema 可能相关？

Schema Linking 进一步解决：

> 用户问题里的每一个业务概念到底对应哪个字段？

例如：

```text
“销售额”
    ↓
metric.net_sales

“华东”
    ↓
dim_region.region_name

“城市”
    ↓
dim_city.city_name

“今年”
    ↓
fact_order.order_date
```

输出：

```text
Question Concept
      ↕
Physical Schema
```

---

# 20. Join Graph

仅检索到正确字段仍然不够。

例如：

```text
fact_order_item.net_amount
```

和：

```text
dim_region.region_name
```

之间可能没有直接关联。

关系图：

```text
fact_order_item
      │
      │ order_id
      ▼
fact_order
      │
      │ store_id
      ▼
dim_store
      │
      │ city_id
      ▼
dim_city
      │
      │ region_id
      ▼
dim_region
```

系统维护：

```text
Join Graph
```

如果 Schema Linking 只选中了起点和终点：

```text
fact_order_item
dim_region
```

系统自动通过 Join Graph 找到合法路径并补齐：

```text
fact_order

dim_store

dim_city
```

Join Graph 第一阶段不引入 Neo4j。

关系定义仍然存 PostgreSQL。

查询服务加载为内存 Graph，通过图算法完成：

```text
Shortest Path

Path Validation

Cardinality Check
```

避免为了“用了图”额外引入没有必要的基础设施。

---

# 21. Value Linking

用户表达的实体并不一定等于数据库真实值。

例如：

```text
苹果手机
```

数据库：

```text
brand_name = Apple

category_name = Smartphone
```

系统需要完成：

```text
苹果
 ↓
Apple
 ↓
dim_product.brand_name
```

Value Linking 使用：

```text
OpenSearch Exact Search

BM25

Fuzzy Search

Milvus Semantic Search

Alias Dictionary

Sample Values
```

最终确认：

```text
Value
+
Column
```

Databricks 2026 年的 Genie Agent 配置同样已经显式支持 example values、value dictionary、join、measures、filters 和 expressions 等知识信息，说明数据库值与业务语义本身已经成为现代 NL2SQL/Data Agent 的核心上下文。

---

# 22. Semantic Layer

Semantic Layer 是 AtlasSQL 最核心的业务知识层。

数据库可能不存在：

```text
销售额
活跃客户
客单价
毛利率
复购率
```

这些字段。

例如：

```yaml
metric:
  name: net_sales
  label: 销售额

  synonyms:
    - 营收
    - 净销售额
    - 销售收入

  expression:
    SUM(fact_order_item.net_amount)

  filters:
    - fact_order.status = 'PAID'
    - fact_order.is_test = false

  dimensions:
    - date
    - city
    - region
    - product
```

Semantic Layer 管理：

```text
Metric

Measure

Dimension

Entity

Relationship

Filter

Synonym

Business Term

Fiscal Calendar

Time Definition
```

---

# 23. Semantic Model 生命周期

Semantic Model 必须版本化。

状态：

```text
Draft

Testing

Published

Deprecated
```

例如：

```text
net_sales v1
       ↓
net_sales v2
       ↓
net_sales v3
```

如果财务部门调整销售额计算规则：

```text
修改 Metric
      ↓
生成 Semantic Model v4
      ↓
Benchmark Regression
      ↓
审核
      ↓
Publish
      ↓
Cache Invalidation
```

不能直接修改线上定义。

---

# 24. Verified Query Repository

维护经过人工或自动审核的：

```text
Natural Language
        +
Verified SQL
```

例如：

```text
Question:

华东地区今年销售额是多少？
```

对应：

```sql
SELECT ...
```

保存：

```text
question

sql

domain

semantic_model_version

description

tags

verified_by

verified_at

version
```

Question 和 SQL 的语义向量进入 Milvus。

文本信息进入 OpenSearch。

查询时：

```text
Current Question
       ↓
Hybrid Retrieval
       ↓
Similar Verified Queries
       ↓
Top K
       ↓
SQL Generator Context
```

这不是把 Few-shot 固定写在 Prompt 中，而是动态选择真正相关的 Example SQL。

Snowflake 当前的 Verified Query Repository 就采用“问题 + 已验证 SQL”的方式，为相似问题提供可信参考；Databricks Genie Agent 也把 Example SQL 和 Trusted Assets 作为提升可靠性的重要配置。

---

# 25. Query Planner

复杂问题禁止直接：

```text
Question → SQL
```

采用：

```text
Question
   ↓
Query Planner
   ↓
Intermediate Representation
   ↓
SQL Generator
```

例如：

```json
{
  "metrics": [
    "net_sales",
    "gross_margin_rate"
  ],
  "dimensions": [
    "city"
  ],
  "time_ranges": {
    "current": "2026",
    "comparison": "2025"
  },
  "filters": {
    "region": "East China"
  },
  "operations": [
    "year_over_year",
    "filter",
    "ranking"
  ]
}
```

IR 可以独立进行：

```text
Validation

Evaluation

Logging

Debugging
```

同时将：

```text
业务理解
```

与：

```text
SQL Dialect
```

解耦。

---

# 26. SQL Generation

SQL Generator 的 Context 不再是：

```text
Question + 全部 Schema
```

而是：

```text
System Policy

Question

Query Plan

Selected Schema

Join Path

Semantic Definitions

Business Rules

Value Mapping

Verified Queries

SQL Dialect
```

最终：

```text
Context Builder
      ↓
LLM
      ↓
SQL Candidate
```

---

# 27. SQL Validator

生成 SQL 禁止直接进入数据库。

首先使用：

**SQLGlot**

解析：

```text
SQL
 ↓
AST
```

检查：

```text
Statement Type

Tables

Columns

Functions

JOIN

Subquery

CTE

Limit

Aggregation
```

拦截：

```text
INSERT

UPDATE

DELETE

DROP

ALTER

TRUNCATE

CREATE
```

同时检查：

```text
Unknown Table

Unknown Column

Forbidden Table

Sensitive Column

Cartesian Join

Unsafe Function
```

---

# 28. Policy Engine

SQL 安全不能依赖 Prompt。

权限分三层：

```text
User
 ↓
Application Policy
 ↓
Authorized Metadata
 ↓
SQL Validation
 ↓
Database Native Permission
```

例如：

```text
CEO
→ 全国

华东区域经理
→ 华东数据

上海门店经理
→ 上海门店

Finance
→ 成本字段

Sales
→ 无薪资字段权限
```

权限必须同时作用于：

```text
Schema Retrieval

Semantic Retrieval

SQL Validation

Database Execution
```

未经授权的 Schema 最好根本不进入模型 Context。

---

# 29. SQL Execution

SQL Validator 通过以后：

```text
SQL
 ↓
EXPLAIN
 ↓
Cost Estimation
 ↓
Execution
```

执行账户必须：

```text
Read Only
```

配置：

```text
Statement Timeout

Maximum Rows

Maximum Scan

Maximum Cost

Maximum Concurrent Queries
```

避免模型产生：

```text
全表扫描

巨型 Join

超大结果集
```

---

# 30. SQL Repair

SQL 执行失败后允许自动修复。

例如：

```text
column net_sale does not exist
```

链路：

```text
SQL
 ↓
Database Error
 ↓
Error Classifier
 ↓
Repair Context
 ↓
LLM
 ↓
SQL v2
```

错误分类：

```text
SyntaxError

SchemaError

TypeError

FunctionError

TimeoutError

PermissionError

CostError
```

其中：

```text
PermissionError

SecurityViolation
```

禁止进入 Repair。

默认：

```text
MAX_REPAIR_ATTEMPTS = 2
```

---

# 31. Result Validator

SQL 可以执行不意味着业务答案正确。

系统需要继续校验：

```text
Result Empty?

Abnormal Value?

Unexpected NULL?

Duplicate Amplification?

Aggregation Grain Correct?

Metric Rule Applied?

Required Filter Applied?
```

例如：

```text
Metric = net_sales
```

要求：

```text
status = PAID

is_test = false
```

Result Validator 可以结合 AST 和 Semantic Definition 检查这些规则是否真正进入 SQL。

---

# 32. Clarification

对于信息不足的问题：

> 看一下今年表现怎么样。

系统不能自己猜：

```text
销售额？
订单量？
毛利率？
客户数？
```

而应该返回：

> 你希望查看销售额、订单量、毛利率还是客户增长？

因此系统需要：

```text
Confidence
```

达到阈值：

```text
High
→ Execute

Medium
→ Additional Retrieval

Low
→ Clarification
```

---

# 33. LLM Gateway

系统不绑定某一个模型厂商。

统一接口：

```text
LLMGateway
```

底层实现：

```text
OpenAI Compatible

Claude

Gemini

Qwen

DeepSeek

Local Model
```

支持：

```text
不同任务使用不同模型
```

例如：

```text
Domain Routing
→ Fast Model

Query Understanding
→ Fast Model

SQL Generation
→ Strong Model

SQL Judge
→ Strong Model

Answer Summary
→ Fast Model
```

后续可根据：

```text
Accuracy

Latency

Token Cost
```

动态选择模型。

---

# 34. 技术栈

## 前端

```text
Next.js
React
TypeScript
Tailwind CSS
Apache ECharts
```

主要负责：

```text
AI Chat

Query Result

SQL Explain

Trace

Admin Console

Evaluation Dashboard
```

---

## 后端

```text
Python 3.12+
FastAPI
Pydantic
SQLAlchemy
Alembic
```

---

## 元数据与控制数据

```text
PostgreSQL
```

---

## Dense Retrieval

```text
Milvus
```

主要：

```text
Schema Embedding

Semantic Embedding

Verified Query Embedding

Business Term Embedding

Value Embedding
```

---

## Lexical Retrieval

```text
OpenSearch
```

主要：

```text
BM25

Keyword

Fuzzy

Alias

Field Name

Business Value
```

---

## Ranking

```text
RRF
+
BGE Reranker
```

---

## Embedding

默认：

```text
BGE-M3
```

Embedding 层同样抽象 Provider，便于模型对比。

---

## Cache

```text
Redis
```

---

## SQL Parser

```text
SQLGlot
```

---

## 后台任务

```text
Celery
+
Redis
```

主要执行：

```text
Metadata Sync

Embedding

Index Building

Benchmark

Batch Evaluation
```

---

## Observability

```text
OpenTelemetry

Prometheus

Grafana

Langfuse
```

---

## Deployment

```text
Docker

Docker Compose

Kubernetes
```

开发环境使用：

```text
Docker Compose
```

生产部署方案：

```text
Kubernetes
```

---

# 35. AtlasSQL V0 —— Enterprise Data Foundation

## 目标

先建立真正能把 NL2SQL 做难的数据环境。

这一阶段不追求聊天功能。

---

## 实现内容

建立：

```text
7 Business Domains

50～80 Tables

600～1000 Columns

Millions of Rows
```

设计：

```text
Fact Table

Dimension Table

Snapshot Table

Bridge Table

Multi Fact

Complex Join
```

同时加入：

```text
Bad Column Names

Abbreviations

Multiple Date Columns

Similar Tables

Historical Tables

Status Code

Internal Code

Sensitive Fields
```

---

## V0 同时搭建全部基础设施

从第一天启动：

```text
PostgreSQL

Milvus

OpenSearch

Redis
```

不设计 pgvector 过渡阶段。

---

## V0 建立 Benchmark

首批：

```text
100～150 Questions
```

覆盖：

```text
Single Table

Join

Aggregation

Group By

Top N

Time Filter

同比

环比

Value Mapping

Business Metric

Complex Join

Ambiguity

Permission
```

保存：

```text
Question

Gold SQL

Expected Result

Required Domain

Required Tables

Required Columns

Required Metrics

Difficulty
```

### V0 交付结果

```text
企业数据模型

数据生成器

Metadata Crawler

PostgreSQL Metadata Center

Milvus

OpenSearch

Redis

Benchmark v1
```

---

# 36. AtlasSQL V1 —— Baseline NL2SQL

## 目的

建立一个最基础 Baseline。

故意保持简单，以便后续可以量化架构优化带来的提升。

---

## Pipeline

```text
Question
 ↓
Domain
 ↓
Schema
 ↓
Prompt
 ↓
LLM
 ↓
SQL
 ↓
SQLGlot
 ↓
Execute
 ↓
Result
```

只开放：

```text
Sales Domain
```

约：

```text
10～15 Tables
```

---

## V1 重点

实现：

```text
LLM Gateway

Prompt Builder

Basic SQL Generator

SQLGlot Parser

Read-only Executor

Result Renderer

Query Trace
```

---

## V1 必须形成 Failure Taxonomy

例如：

```text
Wrong Table

Wrong Column

Wrong Join

Wrong Value

Wrong Metric

Wrong Time

Wrong Aggregation

Syntax Error
```

统计：

```text
Schema Error        31%

Business Metric     24%

Join Error          18%

Value Error         10%

Time Error           9%

Other                8%
```

V2 的设计必须针对 V1 的真实 Failure 演进。

---

# 37. AtlasSQL V2 —— Enterprise Schema Linking

这一版解决：

> 大 Schema 场景下，LLM 无法可靠找到正确数据。

---

## 增加

```text
Domain Router

SearchRepository

OpenSearch Retrieval

Milvus Retrieval

RRF

Reranker

Table Retrieval

Column Retrieval

Schema Linking

Value Linking

Join Graph
```

Pipeline：

```text
Question
 ↓
Domain Router
 ↓
Hybrid Table Retrieval
 ↓
Reranker
 ↓
Column Retrieval
 ↓
Schema Linking
 ↓
Value Linking
 ↓
Join Graph Completion
 ↓
SQL Generation
```

---

## V2 独立评测

增加：

```text
Domain Accuracy

Table Recall@K

Table Precision@K

Column Recall@K

Column Precision@K

Value Linking Accuracy

Join Path Accuracy
```

例如项目目标：

```text
Domain Accuracy
≥ 98%

Table Recall@10
≥ 97%

Column Recall
≥ 95%
```

这些是 AtlasSQL 项目目标，不作为通用行业标准。

---

# 38. AtlasSQL V3 —— Semantic NL2SQL

V3 是整个项目最关键的一次演进。

V2 可以找到：

```text
Table
Column
Value
```

但是仍然不知道：

> 企业里的“销售额”到底怎么算。

因此 V3 建立：

```text
Semantic Layer

Metric Registry

Dimension Registry

Business Glossary

Synonym

Business Rule

Semantic Relationship
```

同时建设：

```text
Verified Query Repository
```

Pipeline：

```text
Question
       │
       ├──────────────────┐
       ▼                  ▼
Schema Retrieval     Semantic Retrieval
       │                  │
       └────────┬─────────┘
                ▼
       Verified Query Retrieval
                ↓
          Context Builder
                ↓
           SQL Generation
```

V3 开始真正从：

```text
Text-to-SQL
```

演进为：

```text
Text-to-Semantics-to-SQL
```

Databricks 当前 Genie Agent 已经把 measures、filters、dimensions、join relationships、example SQL 和 Trusted Assets 都作为独立知识内容管理；这与 AtlasSQL V3 的设计方向是一致的。

---

# 39. AtlasSQL V4 —— Production NL2SQL

V4 开始把系统从：

```text
高准确率实验系统
```

提升为：

```text
Production Ready NL2SQL
```

增加：

```text
Query Planner

Intermediate Representation

SQL AST Validation

Policy Engine

RBAC / ABAC

Row Permission

Column Permission

EXPLAIN

Cost Control

Timeout

SQL Repair

Result Validation

Audit Log
```

完整 Pipeline：

```text
Question
 ↓
Understanding
 ↓
Retrieval
 ↓
Semantic Linking
 ↓
Query Plan
 ↓
IR
 ↓
SQL
 ↓
AST Validator
 ↓
Policy Engine
 ↓
EXPLAIN
 ↓
Execute
 ↓
Result Validator
 ↓
Answer
```

**V4 定义为 AtlasSQL Enterprise NL2SQL 1.0。**

也就是说：

> 做到 V4，这个项目已经可以完整地作为企业级 NL2SQL 项目进行面试讲解。

---

# 40. AtlasSQL V5 —— Agentic Data Analyst

V5 不再只是：

```text
NL → SQL
```

而开始解决复杂数据分析任务。

此阶段再引入：

```text
LangGraph
```

而不是项目第一天使用 Agent Framework。

增加 Tool：

```text
SchemaSearchTool

SemanticSearchTool

ValueSearchTool

VerifiedQueryTool

SQLGenerateTool

SQLExecuteTool

SQLRepairTool

ChartTool
```

---

## Complex Query Decomposition

例如：

> 找出今年销售额下降但是毛利率提高的城市，并分析主要原因。

Planner 可以拆：

```text
Task
 │
 ├── 当前销售额
 │
 ├── 去年销售额
 │
 ├── 当前毛利率
 │
 ├── 去年毛利率
 │
 ├── 产品结构
 │
 └── 客户结构
 │
 ▼
Synthesis
```

---

## Multi-Candidate SQL

仅：

```text
Complexity = HIGH
```

或：

```text
Confidence = LOW
```

时：

```text
SQL A

SQL B

SQL C
```

然后通过：

```text
Syntax

Schema

Semantic

Execution

Result

Cost
```

综合选择最终 SQL。

---

# 41. AtlasSQL V6 —— NL2SQL Ops

最后一个版本解决：

> 系统上线以后，怎么知道它有没有越来越差？

建立：

```text
Evaluation Platform

Prompt Version

Model Version

Semantic Version

Retriever Version

Benchmark Version

Trace

Feedback

Failure Mining

Regression Test

Canary Release

Cost Analysis
```

---

## CI Evaluation

每次修改：

```text
Prompt

Model

Embedding

Reranker

Semantic Model

Retrieval Strategy
```

自动运行：

```text
Benchmark
```

输出：

```text
Execution Accuracy

Semantic Accuracy

Schema Recall

First Pass Success

Repair Rate

Latency

Token Cost
```

例如：

```text
AtlasSQL 4.3

Execution Accuracy
88.7% → 91.2%

Table Recall@10
96.4% → 98.1%

First Pass Success
82.1% → 86.7%

P95
5.4s → 4.8s

Token Cost
-13%

Regression
3 cases
```

如果关键指标低于阈值：

```text
CI FAILED
```

Microsoft Fabric 当前也明确建议从 Benchmark 开始，通过持续测试、修改 Schema Context、Instructions 和 Example Queries 形成迭代闭环。

---

# 42. 最终版本路线

AtlasSQL 的整体演进：

```text
V0
Enterprise Data Foundation
       │
       ▼
V1
Baseline NL2SQL
       │
       ▼
V2
Schema Retrieval & Linking
       │
       ▼
V3
Semantic NL2SQL
       │
       ▼
V4
Production NL2SQL
       │
       ▼
V5
Agentic Data Analyst
       │
       ▼
V6
NL2SQL Ops
```

每一次演进都回答一个明确问题：

```text
V1

LLM 面对 Schema
为什么经常选错表？
        ↓
V2 Schema Retrieval
```

```text
V2

表字段都找对了，
为什么销售额还是算错？
        ↓
V3 Semantic Layer
```

```text
V3

准确率已经不错，
为什么还不能直接上生产？
        ↓
V4 Guardrail & Governance
```

```text
V4

单条 SQL 可以解决，
复杂分析任务怎么办？
        ↓
V5 Agentic Data Analyst
```

```text
V5

系统已经很强，
升级模型之后怎么知道有没有退化？
        ↓
V6 NL2SQL Ops
```

这条演进路线也是 AtlasSQL 最重要的面试叙事主线。

---

# 43. 最终工程结构

```text
AtlasSQL
│
├── apps
│   ├── web
│   └── admin
│
├── server
│   │
│   ├── api
│   ├── auth
│   ├── datasource
│   ├── metadata
│   ├── domain
│   ├── semantic
│   ├── search
│   │   ├── milvus
│   │   ├── opensearch
│   │   ├── fusion
│   │   └── reranker
│   ├── linking
│   ├── planner
│   ├── generation
│   ├── validation
│   ├── policy
│   ├── execution
│   ├── repair
│   ├── evaluation
│   ├── observability
│   └── llm
│
├── semantic_models
│
├── datasets
│
├── benchmarks
│
├── migrations
│
├── scripts
│
├── tests
│
├── deploy
│
└── docs
```

---

# 44. 核心评测指标

最终 AtlasSQL 不能只说：

> SQL 准确率 90%。

必须建立多维指标。

## Retrieval

```text
Domain Accuracy

Table Recall@K

Table Precision@K

Column Recall@K

Value Linking Accuracy

Join Path Accuracy
```

## Generation

```text
Syntax Valid Rate

Schema Valid Rate

First Pass Success Rate

Execution Accuracy

Semantic Accuracy
```

## Runtime

```text
Execution Success Rate

Repair Rate

Timeout Rate

Clarification Rate
```

## Security

```text
Unauthorized Query Block Rate

Sensitive Column Violation

Unsafe SQL Block Rate
```

## Engineering

```text
P50 Latency

P95 Latency

Average Token

Average Cost

Cache Hit Rate
```

---

# 45. 项目最终定位

AtlasSQL 不是：

```text
ChatGPT
+
Database
```

也不是：

```text
Prompt
+
SQL Generator
```

最终系统应该具备六层核心能力：

```text
① Metadata Intelligence

② Retrieval & Schema Linking

③ Business Semantic Layer

④ Query Planning & SQL Generation

⑤ Security & Execution Governance

⑥ Evaluation & NL2SQL Ops
```

其真正核心问题不是：

> LLM 会不会写 SQL？

而是：

> **系统能否把业务人员的自然语言，可靠地映射到企业真实的数据模型、指标定义和权限体系，并生成可以安全执行且业务语义正确的 SQL。**

因此 AtlasSQL 最终要证明的并不是“模型很聪明”，而是：

> **即使底层 LLM 存在不确定性，AtlasSQL 仍然能够通过 Metadata、Retrieval、Schema Linking、Semantic Layer、Verified Query、Query Planning、Guardrail、Execution Feedback 和 Evaluation，将这种不确定性约束在企业可以接受的范围内。**

这就是 AtlasSQL 的企业级设计目标。

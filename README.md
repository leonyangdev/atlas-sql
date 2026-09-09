<div align="center">

<h1>AtlasSQL</h1>

<p><strong>企业级 NL2SQL 数据智能分析平台</strong></p>

<p>
  让业务人员用自然语言提问，经过语义理解、Schema 召回、指标口径解析与权限治理，<br>
  生成有依据、可审计的 SQL，返回经过验证的数据答案。
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)](https://nextjs.org/)
[![CI](https://github.com/leonyangdev/atlas-sql/actions/workflows/ci.yml/badge.svg)](https://github.com/leonyangdev/atlas-sql/actions/workflows/ci.yml)

[📖 学习站](https://leonyangdev.github.io/atlas-sql/) · [🇬🇧 English](README.en.md) · [🚀 Releases](https://github.com/leonyangdev/atlas-sql/releases) · [📋 开发计划](#开发进度)

</div>

---

## 这是什么项目

AtlasSQL 是一个**企业级 NL2SQL 平台**，同时被设计为三种用途：

| 定位 | 说明 |
|------|------|
| 🏢 **企业级工程实践** | 从第一天起就引入真实约束：权限分层、成本限制、Schema 版本化、幂等同步、可审计的查询链路 |
| 📚 **系统性学习项目** | 每个架构决策都由上一版本的真实失败驱动。每个阶段有明确的学习目标、验收标准和失败案例 |
| 🎯 **面试复盘素材** | 每期产出可复现的证据——Benchmark 数据、失败分类、设计取舍——可以在面试中用两分钟完整叙述 |

> **为什么不直接 `自然语言 → SQL`？**
>
> 因为企业数据是复杂的。"销售额"在财务和销售部门可能是不同的口径。`fact_order_item` 和 `fact_refund_item` 不加处理的 Join 会产生重复行。北区经理不应该看到南区数据——不是因为 Prompt 里说了，而是因为权限层强制执行。AtlasSQL 从一开始就认真对待这些约束。

---

## 核心能力

- 🔍 **混合检索** — BM25（OpenSearch）+ 密集向量（Milvus / BGE-M3）+ RRF 融合 + Reranker
- 🗺️ **Schema 与值链接** — 把自然语言映射到物理字段，解析别名，遍历 Join Graph
- 📐 **语义层** — 版本化指标定义（净销售额、毛利率…）、可信查询仓库（Verified Query Repository）
- 🛡️ **四层治理** — 用户身份 → 应用策略 → 授权元数据 → 数据库原生权限
- 🔒 **安全执行** — SQLGlot AST 校验、只读执行、成本与超时限制、自动修复
- 📊 **Benchmark 驱动** — 120 道 Gold SQL 题（train / tune / 锁定 test），跨快照可复现
- 🏪 **真实数据集** — NovaRetail 零售集团：7 个业务域、56 张表、百万级数据、故意复杂

---

## 系统架构

```
┌──────────── 用户端 (Next.js Web) ────────────┐
│             管理后台 (Next.js Admin)          │
└──────────────────────┬───────────────────────┘
                       │
              FastAPI API Gateway
                       │
         ┌─────────────┴──────────────┐
         │                            │
   问数链路 (Query Orchestrator)    管理服务 (Admin Service)
         │                            │
   意图理解                    ┌──────▼──────────┐
         │                    │  PostgreSQL      │
   域路由                     │  控制库           │
         │                    │  元数据 / 语义    │
   ┌─────▼──────┐             │  指标 / 权限      │
   │   检索引擎  │             └──────┬──────────┘
   │ OpenSearch │                    │
   │   BM25     │          Celery + Redis
   │  ＋Milvus  │       （元数据同步 / 索引构建 / 评测）
   │  密集向量  │
   │ RRF + 重排 │
   └─────┬──────┘
         │
   Schema & Value Linking
   Join Graph 路径寻找
         │
   语义层（指标 / 可信查询）
         │
   查询计划 → 中间表示（IR）
         │
   SQL 生成（LLM）
         │
   SQLGlot 语法与安全校验
         │
   权限引擎（行列级过滤）
         │
   只读执行（超时 / 成本限制）
         │
   结果验证 → 自然语言解释
```

**三类核心存储：**

| 存储 | 职责 |
|------|------|
| PostgreSQL（控制库）| 元数据、语义模型、指标定义、权限、可信查询、评测结果 |
| OpenSearch | 词法检索：字段名、业务名、别名、枚举值的 BM25 搜索 |
| Milvus | 语义检索：表 / 列 / 指标 / 可信查询的密集向量检索 |
| Redis | Schema 缓存、Session 上下文、速率限制、分布式锁 |

---

## 业务数据集 — NovaRetail Group

模拟一家同时经营线上商城、线下门店和会员体系的中大型零售集团。数据集故意设计了真实企业 NL2SQL 的主要难题：

| 业务域 | 核心表 | 设计的难题 |
|--------|--------|-----------|
| Sales 销售 | 订单、明细、支付、退款 | 跨期退款、Join 放大 |
| Product 商品 | SKU、品牌、品类 | SCD2 历史表、同名商品 |
| Customer 客户 | 会员、等级、标签 | 多对多桥表、双时态历史 |
| Store 门店 | 门店、城市、区域 | 区域归属变更、行级权限 |
| Inventory 库存 | 快照、流水 | 快照语义、禁止跨日求和 |
| Finance 财务 | 收入、成本、毛利 | 受限字段、多指标 Join |
| Marketing 营销 | 活动、渠道、优惠券 | 桥表多对多、归因窗口 |

**当前规模：** 56 张表 · 100 万条订单明细 · 120 道 Gold SQL 问题

---

## 技术栈

| 层 | 技术选型 |
|----|---------|
| 后端 API | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| 前端 | Next.js 16, React 19, TypeScript |
| 元数据控制库 | PostgreSQL |
| 向量检索 | Milvus + BGE-M3（1024 维，HNSW + IP） |
| 词法检索 | OpenSearch |
| 缓存与任务队列 | Redis, Celery |
| SQL 解析校验 | SQLGlot |
| Embedding | BGE-M3（FlagEmbedding），通过 `EmbeddingProvider` 协议抽象 |
| 可观测性 | OpenTelemetry, Langfuse |
| 代码质量 | ruff, mypy（strict 模式）, pytest |

---

## 开发进度

项目按七个阶段演进，每个阶段有明确的失败起点、验收标准和学习目标：

| 阶段 | 目标 | 状态 |
|------|------|------|
| **V0** 企业数据与工程基础 | 可复现数据集、元数据中心、索引基础、Benchmark v1 | ✅ 已完成 |
| **V1** 可测量的问数基线 | Sales 子集跑通最小安全链路，建立 Baseline 并分类真实失败 | 🔜 进行中 |
| **V2** 混合检索与 Schema Linking | 大 Schema 下正确召回表、字段、值和关联路径 | 📋 规划中 |
| **V3** 业务语义与可信查询 | 版本化指标口径，累计 200+ 可信查询 | 📋 规划中 |
| **V4** 企业级安全问数 1.0 | 查询计划、全链路治理、生产候选系统 | 📋 规划中 |
| **V5** Agentic 数据分析师 | 多步分析、多轮上下文、有预算的工具编排 | 📋 规划中 |
| **V6** 评测运营与持续演进 | 500+ Benchmark、CI 门禁、版本比较与灰度回滚 | 📋 规划中 |

完整任务台账与验收标准见 [`plan/`](plan/)，每期学习路线见[学习站](https://leonyangdev.github.io/atlas-sql/)。

---

## 快速开始

**环境依赖：** Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 22+、Docker Compose

```bash
# 克隆并配置环境变量
git clone https://github.com/leonyangdev/atlas-sql.git
cd atlas-sql
cp .env.example .env.atlas

# 安装依赖
uv sync --locked --all-groups
npm ci

# 启动基础设施
# PostgreSQL × 2、Redis、OpenSearch、Milvus
# 可视化工具：OpenSearch Dashboards（:5601）、Attu / Milvus（:8080）
docker compose --env-file .env.atlas up -d

# 初始化数据库
uv run alembic upgrade head
uv run python scripts/migrate_business.py

# 生成模拟数据（tiny 用于开发，scale 用于验收）
uv run python scripts/seed_data.py --profile tiny --reset --confirm-database nova_retail

# 启动后端 API
uv run uvicorn server.api.app:create_app --factory --reload --port 8000

# 启动前端（用户端 :3000，管理后台 :3001）
npm run dev:web
npm run dev:admin
```

验证所有依赖就绪：

```bash
curl http://127.0.0.1:8000/health/ready
```

各服务访问地址：

| 服务 | 地址 | 说明 |
|------|------|------|
| 后端 API | http://127.0.0.1:8000 | FastAPI，含 `/docs` Swagger UI |
| 用户端 | http://127.0.0.1:3000 | 自然语言问数页面 |
| 管理后台 | http://127.0.0.1:3001 | 数据治理控制台 |
| OpenSearch Dashboards | http://127.0.0.1:5601 | 元数据索引可视化 |
| Attu（Milvus GUI） | http://127.0.0.1:8080 | 向量集合可视化，连接地址填 `localhost:19530` |
| MinIO 控制台 | http://127.0.0.1:9001 | 对象存储，账号 `minioadmin` / `minioadmin` |

**本地质量检查：**

```bash
uv run ruff check . && uv run mypy
uv run pytest --cov=server --cov-fail-under=85
npm run typecheck && npm run build
```

---

## 仓库结构

```
atlas-sql/
├── server/                  # FastAPI 后端
│   ├── api/                 # 路由与应用工厂
│   ├── datasource/          # 数据源登记与元数据采集
│   ├── metadata/            # 元数据查询与人工注释接口
│   ├── search/              # 索引 Schema、文档 ID、缓存约定
│   ├── llm/                 # EmbeddingProvider 抽象层
│   ├── tasks/               # Celery 后台任务
│   └── evaluation/          # Benchmark 加载与结果比较器
├── apps/
│   ├── web/                 # 用户端 Next.js（问数与结果展示）
│   └── admin/               # 管理后台 Next.js（数据治理控制台）
├── datasets/
│   ├── schema/              # 声明式表目录（单一事实来源）
│   ├── generator/           # 确定性数据生成器（固定 seed）
│   └── business_migrations/ # NovaRetail DDL
├── benchmarks/v1/           # Gold SQL 题库（train / tune / test）
├── migrations/              # Alembic 控制库迁移
├── scripts/                 # 数据生成、迁移、索引重建等 CLI 工具
├── semantic_models/         # 指标草案与语义模型定义
├── plan/                    # 任务台账与各期验收证据
└── altassql-book/           # VitePress 学习站
```

---

## 学习与面试

项目结构让每个工程决策都可以追溯：

- **每个阶段都有一个明确要修复的上期失败** — 不是为了加功能而加功能
- **Benchmark 数字可复现** — 相同 seed、相同快照、相同结果
- **证据文件** [`plan/evidence/`](plan/evidence/) 记录了实际运行的命令、产物路径和已知限制
- **学习站** 涵盖架构决策、模块契约和两分钟面试叙事框架

如果你在用这个项目准备数据工程或 AI 平台方向的面试，建议从[学习站](https://leonyangdev.github.io/atlas-sql/)入手，完整跟完一个阶段再进入下一阶段。

---

## License

MIT — 详见 [LICENSE](LICENSE)。

> 原始项目总纲位于 [`docs/PROJECT.md`](<docs/PROJECT.md>)（目录名含前导空格，保留未改动）。

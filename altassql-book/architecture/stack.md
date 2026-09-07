# 技术栈与职责

> 下表主要依据原始总纲第 34 节。它描述目标选型，不代表依赖已安装。当前可运行的只有本学习站 VitePress 1.6.4；版本见 package-lock.json。

| 技术 | 项目中的用途 | 引入期 | 要学会解释的取舍 |
| --- | --- | --- | --- |
| Python 3.12+ / FastAPI | 类型化 HTTP API 与编排服务 | V0 | async 需要配合非阻塞驱动，CPU/批量任务另行处理 |
| Pydantic | 请求、意图、候选、IR 的结构校验 | V0 起 | 结构合法不代表业务语义正确 |
| SQLAlchemy / Alembic | 控制面持久化与 schema 迁移 | V0 | ORM 适合控制数据，不替代生成 SQL 的 AST 检查 |
| Next.js / React / TypeScript | Data Analyst 与 Admin Console | V0 骨架，逐期完善 | 用户状态与管理工作流需要清晰契约 |
| Tailwind CSS / Apache ECharts | 业务 UI 与数据图表 | 前端逐期 | 图表类型受数据形状约束 |
| PostgreSQL | Control Plane；首个业务库也选 PostgreSQL | V0 | 同产品不同职责与账户 |
| OpenSearch | BM25、编码、字段名、别名和值检索 | V0 基础，V2 查询 | 精确术语可解释，但需要 mapping 与分词治理 |
| Milvus | schema、语义、样例和值向量召回 | V0 基础，V2 查询 | 语义泛化有价值，但需要模型/维度/索引版本 |
| BGE-M3 / BGE Reranker | 默认 embedding 与候选重排 | V0 / V2 | 性能成本需本机实测，Provider 隔离模型替换 |
| RRF | 按排名融合 lexical 与 dense | V2 | 不直接相加不可比分数，仍需调 K 和常数 |
| Redis | 缓存、会话、限流、锁与任务 broker | V0 起 | TTL 不等于版本一致性，授权参与缓存键 |
| Celery | 元数据同步、索引、Benchmark 批处理 | V0 起 | 重试可能重复投递，需要幂等与版本校验 |
| SQLGlot | AST 解析、对象检查、规则校验 | V1 起 | SQL parser 不是完整权限系统 |
| LangGraph | 有状态的多步分析编排 | V5 | 先证明单步能力可靠，再让 Agent 调用 |
| OpenTelemetry / Prometheus / Grafana / Langfuse | 链路、运行指标、仪表盘、模型观测 | V1 最小 trace，V4 完整 | 分清技术追踪、审计和质量评测 |
| Docker / Compose / Kubernetes | 本地基础设施与部署方案 | V0 / V4 | Compose 本地复现，K8s 需部署和恢复验收 |
| VitePress / Vue | 学习文档、计划导航和进度 | 本轮已实现 | 静态站不直接写仓库任务状态 |

## 如何学习选型而非背清单

以 hybrid retrieval 为例，应能说明一个真实失败：SKU000392 这种精确编码适合 lexical；“卖得最好”这类表达需要语义召回。再说明两路排名怎样融合、权限怎样过滤、重排引入多少延迟，最后给出消融评测。这比记住 Milvus 和 OpenSearch 的名字更有说服力。

依赖版本、驱动兼容性、资源需求在相应开发任务里锁定并验证；不把总纲里的技术名当作无条件可兼容的版本矩阵。

学习站的路由、构建和主题扩展使用 [VitePress 官方文档](https://vuejs.github.io/vitepress/v1/guide/getting-started) 所述机制。其他技术首先读本项目职责与任务，再按具体实现查询对应官方文档。

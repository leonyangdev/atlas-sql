# 总体架构与依赖方向

> 状态：目标设计；当前没有业务服务。模块命名来自项目总纲，边界与契约由本次计划细化。

## 三条不同的工作流

```text
在线问数
Next.js Web → FastAPI → QueryOrchestrator → 业务模块 → 受控业务库查询

资产治理
Next.js Admin → Admin Service → PostgreSQL 控制库
                                   ↓ 同步/索引/评测任务
                               Celery + Redis → 派生索引

质量反馈
Query Trace + Benchmark + 人工反馈 → Evaluation → 配置发布或回滚
```

先采用模块化单体，让清晰的 Python 调用关系承载业务。Celery worker 负责长任务。模块之间通过类型化契约交互，但不必为每个模块部署独立微服务；服务拆分需要负载、团队或隔离要求支撑。

## 六个核心边界

| 边界 | 包含 | 不承担 |
| --- | --- | --- |
| API 与身份 | 参数校验、可信身份、请求状态 | SQL 生成细节 |
| 编排 | 顺序、预算、状态、trace | 直接调用 Milvus/数据库驱动 |
| 业务知识 | 元数据、域、语义、关系、可信样例 | 随意执行 SQL |
| 检索链接 | 召回、排序、字段值映射、路径 | 决定最终访问授权 |
| 计划与执行治理 | IR、生成、AST、Policy、执行、修复、结果 | 依赖 Prompt 代替安全检查 |
| 评测运营 | 版本、回归、失败分析、反馈与发布 | 用主观评分替代可信结果 |

## 完整问数链路

```text
QueryRequest + AuthorizationContext
  → Understanding → Domain Routing
  → SearchRepository（OpenSearch + Milvus → RRF → Reranker）
  → Schema / Value Linking → Join Graph
  → SemanticContext + Verified Queries
  → QueryPlanner → Validated IR → SQLGenerator
  → AST Validator → Policy → EXPLAIN → Read-only Executor
  → Result Validator → Answer

Executor 可恢复失败 → Repair（≤2）→ AST Validator 起重新走完整检查
权限或安全失败 → 终止
```

权限也在检索之前过滤元数据、语义与样例；图中的 Policy 节点是执行前复核，不是权限第一次出现的位置。

## 控制库与业务库分离

PostgreSQL Control Plane 保存元数据、指标、权限、配置、历史、评测。业务库保存订单与库存等业务事实。它们可以使用同一种数据库产品，但不同逻辑数据库、账户与连接配置；控制库写权限不能被 SQL Executor 使用。

OpenSearch 和 Milvus 保存派生检索资产，Redis 保存临时状态与缓存。控制库负责治理事实，索引可重建，缓存可失效。

## 错误传播

底层 SDK 错误在 adapter 变成类型化错误，例如 SearchUnavailable、ModelTimeout、QueryRejected。编排依据类型选择降级、澄清、终止或允许修复；前端只展示可理解的错误码与 trace_id。原始数据库错误先脱敏才进入修复上下文。

## 扩展的顺序

V1 使用显式 Pipeline；V2 增加检索和链接；V3 增加语义；V4 增加 IR 与完整治理；V5 的 LangGraph 包装已有受控能力。这样能够分别测量“业务理解变好”还是“工具编排变复杂”，避免把收益归给一个难以解释的黑箱。

查看 [模块数据契约](./contracts)、[存储与一致性](./storage) 和 [架构决策](./decisions)。

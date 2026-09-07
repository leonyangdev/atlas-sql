# 模块之间传递什么

> 以下是建议契约，字段名和错误码在开发时通过真实代码确定。教学示例不代表已有 API。所有在线对象都应关联 trace_id，并固定本次查询使用的版本。

## 从请求到答案

| 生产者 → 消费者 | 对象 | 关键字段 | 不变量 |
| --- | --- | --- | --- |
| API → Orchestrator | QueryRequest | question、session_id、now | 身份来自服务端会话 |
| Auth → 全链路 | AuthorizationContext | principal_id、role/attributes、allowed_scope、policy_version、fingerprint | 模型和用户文本不能修改 |
| Understanding → Router/Linking | QueryIntent | 指标提及、维度提及、过滤、时间、比较、unresolved | 未确认项显式保留 |
| SearchRepository → Linking | Candidate | object_id、kind、datasource_id、version、score/rank、evidence | 已过滤授权与版本 |
| Linking → Planner | LinkedSchema | 字段映射、类型化值、Join Path、confidence | 字段必须存在，路径必须有业务含义 |
| Semantic → Planner/Generator | SemanticContext | metric_id、expression、grain、rules、time_role、version | Published 且版本固定 |
| Planner → Generator | QueryPlan / IR | 度量、聚合、维度、时间、过滤、操作、来源 | 校验通过后才进入生成 |
| Generator → Validator | SQLCandidate | SQL、parameters、dialect、plan_id、attempt | 不直接执行 |
| Validator/Policy → Executor | ExecutionDecision | allow/reject、reason、validated_sql_hash、policy_version、budget | 与真正执行的 SQL 一致 |
| Executor → Result Validator | QueryResult | typed_columns、rows、row_count、truncated、duration | 不超过权限与资源边界 |
| Result Validator → Answer | ValidatedResult | state、warnings、evidence、units | warning 与 success 区分 |
| 全链路 → Evaluation | QueryTrace | stages、versions、errors、latency、usage | 脱敏、可关联、可重放 |

## 三种引用不要混用

`metric_id` 是业务指标引用，`column_id` 是物理字段引用，`document_id` 是索引文档引用。一个指标可依赖多列；同一对象在两个搜索系统都有文档。RRF 必须按稳定业务对象 ID 合并，不能按不同系统的随机文档 ID 计成两个候选。

## 一个小型接口示例

```python
# 设计示例；完整类型由对应阶段实现。
from typing import Protocol

class SearchRepository(Protocol):
    async def search_schema(
        self,
        query: "SchemaSearchQuery",
        auth: "AuthorizationContext",
    ) -> list["Candidate"]:
        ...
```

这个接口表达“在授权范围内查 schema”。Milvus collection、OpenSearch DSL、RRF 常数和重排模型属于实现细节。可先使用简单模块和函数；接口只在隔离存储、模型或外部服务时建立，不要求每个函数都套一层类。

## 成功以外的契约

| 状态 | 谁决定 | 下一步 |
| --- | --- | --- |
| needs_clarification | 理解、链接、语义冲突 | 向用户补槽位 |
| degraded | 一路检索或可选依赖失效 | 使用允许回退并标记证据缺口 |
| rejected | 安全、权限、成本策略 | 结束，提供可理解原因 |
| failed | 模型、存储或不可恢复执行错误 | 提供 trace_id；可恢复类别允许有限重试 |
| cancelled | 用户或 deadline | 停止工具、模型等待与数据库执行 |
| succeeded_with_warning | 有效结果但异常/截断 | 展示限制，避免过度解释 |

不能用空列表同时表达“没有匹配”和“搜索服务宕机”；不能让 Generator 捕获所有异常后仍返回一条猜测 SQL。

## 防止校验与执行对象错位

ExecutionDecision 应绑定最终 SQL 内容、参数、身份和策略版本。若修复改变 SQL，旧决定失效；若权限撤销或版本改变，应按定义重新验证。实现时不一定需要复杂签名机制，但调用链必须保证校验后到执行前不能替换查询。

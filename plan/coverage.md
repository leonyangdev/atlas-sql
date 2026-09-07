# 需求覆盖与交付映射

此表将原始总纲功能映射到阶段故事。故事里的任务是执行单元；代码位置是设计建议，业务代码当前不存在。

| 原文需求 | 负责故事 | 预期产物 / 验收入口 |
| --- | --- | --- |
| 7 域、50～80 表、600～1000 字段 | V0-S02、V0-S03 | 数据字典、迁移、规模报告 |
| 多事实、多对多、快照、敏感字段 | V0-S02、V0-S03 | 关系图、扇出与权限夹具 |
| 全量基础设施与资源说明 | V0-S01、V0-S05 | Compose、健康检查、资源实测 |
| 数据源管理 | V0-S04、V0-S07 | 连接测试、凭据引用、管理界面 |
| 元数据管理与自动采集 | V0-S04、V0-S07 | 增量同步、人工注释、任务状态 |
| Business Domain Management | V0-S02、V0-S07、V2-S01 | 域定义、管理页与域路由 |
| Embedding Provider / Celery | V0-S04、V0-S05 | 批量索引、重试和版本 |
| Redis 缓存 / 会话 / 限流 / 锁 | V0-S05、V4-S02、V4-S03、V5-S03 | key 约定、失效、授权隔离、预算 |
| LLM Gateway / Prompt Builder | V1-S02、V6-S04 | 适配层、版本与配置管理 |
| AI 问数 / SQL 展示 / 基础摘要 | V1-S01～V1-S04 | 问数 API、结果页、错误状态 |
| Query Understanding / Clarification | V2-S01、V4-S05 | 意图结构、时间解析、阈值与澄清 |
| SearchRepository / 混合检索 | V2-S02、V2-S03 | 两路召回、RRF、BGE 重排 |
| 表 / 列两级召回 | V2-S03 | 上下文裁剪、独立指标 |
| Schema / Value Linking | V2-S04 | 概念和值的映射证据 |
| Join Graph / Relationship Management | V0-S02、V2-S05、V3-S01 | 关系元数据、内存图、基数校验 |
| Semantic Model / Metric / Dimension | V3-S01、V3-S02 | 30～50 指标、状态机、差异与发布 |
| Glossary / Synonym / Business Rule | V3-S03 | 术语管理、冲突与规则链接 |
| Verified Query Repository | V3-S04 | 200+ 审核样例、版本兼容、隔离测试集 |
| Context Builder | V3-S05 | 来源引用、规则保护、注入边界 |
| Planner / IR | V4-S01 | 类型化计划、复杂时间与聚合验证 |
| SQLGlot / AST Validator | V1-S03、V4-S03 | 只读与完整嵌套检查 |
| RBAC / ABAC / 行列权限 | V4-S02 | 权限工作台、授权上下文、数据库防线 |
| EXPLAIN / 配额 / 超时 | V4-S03 | 成本决策、取消、连接恢复 |
| SQL Repair（最多 2 次） | V4-S04 | 状态机、修复再校验、安全错误终止 |
| Result Validator / 解释 | V4-S05 | 规则、粒度、异常与证据关联 |
| Table / Bar / Line / Pie / KPI / Ranking | V4-S05 | 类型匹配、空值与截断提示 |
| Audit / OTel / Prometheus / Grafana / Langfuse | V1-S05、V4-S06 | 阶段 Trace、审计、指标、脱敏 |
| Docker / Compose / Kubernetes | V0-S01、V4-S06 | 开发环境、部署手册、恢复演练 |
| LangGraph / 分解 / Tools | V5-S01、V5-S02 | 受控工具、状态图、预算 |
| 多轮分析 | V5-S03 | 结构化槽位继承与隔离 |
| Multi-Candidate SQL | V5-S04 | 条件触发、候选比较与成本实测 |
| 分析综合与图表 | V5-S05 | 子任务证据、部分失败与因果边界 |
| Benchmark Management / 500+ 问题 | V0-S06、V6-S01 | 初始题库、冻结版本、逐题比较 |
| Evaluation Dashboard / Failure Analysis | V1-S05、V2-S06、V6-S02 | 基线、消融、运营指标 |
| Feedback / Failure Mining | V6-S03 | 人工审核、脱敏、回流 |
| Prompt / Model Management | V1-S02、V6-S04 | 初始版本记录、管理 UI、发布与回滚 |
| CI Evaluation / Canary / Cost | V6-S04、V6-S05 | 自动门禁、稳定分组、预算与回滚 |
| 教学、学习和面试 | 各期最后一个故事 | 真实代码导读、失败实验、复述与证据 |

## 验收规则

覆盖代表“已经规划”，不代表“已经实现”。原文给出的准确率、时延和收益例子都不作为历史成绩；只有带环境、题集、版本和原始输出的报告才能支持面试中的数字。

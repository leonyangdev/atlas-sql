# 安全、执行、修复与结果验证

> 状态：规划中的业务模块。关联任务：V1-S03、V4-S02～V4-S06；[查看实施计划](/plan/v4-production)。真实函数和测试路径由阶段开发完成后补入。

## 业务问题

生成 SQL 具有不确定性。系统必须在模型外部强制执行权限、只读、成本与结果规则。

## 输入、输出与上下游

- **输入**：SQLCandidate、可信 AuthorizationContext、IR、语义/schema 版本与资源预算。
- **输出**：ExecutionDecision、受限 QueryResult、ValidatedResult 或拒绝原因。

```text
AST → Policy → EXPLAIN → Read-only Executor → Result Validator → Answer
```

## 核心机制

只检查字符串是否以 SELECT 开头不够：写 CTE、多语句、SELECT INTO、危险函数、子查询越权都需要完整 AST 和血缘处理。应用策略之外仍用只读账户与数据库原生权限兜底。

EXPLAIN 是估算，不等于实际成本；不能为获得计划执行 EXPLAIN ANALYZE，让昂贵 SQL 在检查前先跑一遍。LIMIT 限制返回行数，也不保证聚合或 Join 扫描很小。执行层仍需超时、并发、字节数与取消机制。

修复最多 2 次，每次重新走 AST、Policy、EXPLAIN。权限与安全错误立即停止。结果验证再检查粒度、必需过滤、NULL、异常值和重复放大；这些检查可以发现问题，但不能数学上证明所有业务答案正确。

## 失败与边界

查询被授权拒绝：不调用修复；取消请求：数据库查询真正停止；去年为零：增长率不定义；空结果：不等于零销售；校验后 SQL 改变：重新审核。

## 学习实验

使用固定攻击集合验证写 CTE、危险函数、UNION 越权、缓存撤权；运行慢查询后取消，再证明连接池可服务下一次请求。

先写预测结果，再执行；把实际输出、数据版本和代码入口放进 [验收证据](/plan/evidence/)。现在尚无业务实现，此处实验需要对应阶段完成后运行。

## 读代码与面试复述

Prompt 安全提示为什么不够？行权限 WHERE 注入为何难？结果校验与 Gold 评测为什么都需要？

阅读时先看契约，再跟一条正常链路和一条失败链路，最后读 adapter 与测试。使用 [代码地图](/architecture/code-map) 定位模块；不要只背技术名称。

# 计划、生成与模型网关

> 状态：规划中的业务模块。关联任务：V1-S02、V3-S05、V4-S01；[查看实施计划](/plan/v4-production)。真实函数和测试路径由阶段开发完成后补入。

## 业务问题

复杂分析需要先决定计算顺序，再表达为某种 SQL 方言。模型网关隔离供应商变化，IR 隔离业务理解与 SQL 生成。

## 输入、输出与上下游

- **输入**：QueryIntent、LinkedSchema、SemanticContext、verified examples、方言与预算。
- **输出**：已验证 QueryPlan/IR、SQLCandidate、使用版本及模型用量。

```text
Context → Planner → IR Validation → Context Builder → LLMGateway → SQLCandidate
```

## 核心机制

IR 要明确哪些是明细过滤、哪些是聚合后条件。例如“同比下降 10% 的城市”要先求两期城市指标，再比较并筛选，不能把同比条件直接放在原始订单 WHERE 中。

LLMGateway 统一生成请求、结构化输出、错误分类与 token 用量；模型响应不满足 schema 时返回明确错误。fake Provider 用于流程与异常测试，真实模型用于质量评测，两者不可混报。

Context Builder 保护强制规则和必要字段，按来源 ID 记录引用。SQLCandidate 只是候选，任何模型自称“安全”或“高置信度”都不构成执行授权。

## 失败与边界

IR 缺失维度或日期角色：澄清；模型超时：受总 deadline 限制；结构化输出无 SQL：失败；token 预算不足：缩小上下文或拒绝，不能丢强制权限规则。

## 学习实验

为两期销售与毛利率写手工 IR，对照生成 SQL 的聚合层级；用 fake Provider 返回格式错误，观察 API 是否保持类型化错误。

先写预测结果，再执行；把实际输出、数据版本和代码入口放进 [验收证据](/plan/evidence/)。现在尚无业务实现，此处实验需要对应阶段完成后运行。

## 读代码与面试复述

IR 比 JSON 格式化提示多了什么价值？模型切换哪些部分应不变？LLM 重试与业务 SQL 修复有何区别？

阅读时先看契约，再跟一条正常链路和一条失败链路，最后读 adapter 与测试。使用 [代码地图](/architecture/code-map) 定位模块；不要只背技术名称。

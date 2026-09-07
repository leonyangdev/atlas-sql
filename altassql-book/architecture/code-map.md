# 代码地图与阅读顺序

## 仓库现状

截至本次文档交付，真实存在的是以下内容。业务模块目录尚未建立。

```text
atlas-sql/
├── AGENT.md                     简洁可读的代码约定
├── README.md                    仓库入口与文档站命令
├── " docs"/PROJECT.md           原始总纲（目录名前有空格）
├── plan/                        唯一任务台账与验收记录
└── altassql-book/
    ├── .vitepress/config.mts    站点路由、搜索、计划监听
    ├── .vitepress/theme/        主题、样式、阶段进度组件
    ├── scripts/                 同步、元数据与内容校验
    ├── guide/                   背景、业务与贯穿案例
    ├── architecture/            架构、契约、存储与决策
    ├── modules/                 模块阅读手册
    ├── stages/                  V0～V6 学习章节
    └── interview/               复盘与面试练习
```

## 目标业务目录

| 规划目录 | 职责 | 首次建设 | 读代码时先找什么 |
| --- | --- | --- | --- |
| apps/web | 业务问数、多轮、结果、图表 | V0 骨架 / V1 功能 | 请求状态与 API 契约 |
| apps/admin | 资产治理、评测和运行管理 | V0 起 | 页面对应哪个业务服务 |
| server/api、auth | HTTP 边界、可信身份 | V0 / V4 完整 | Request 校验与 auth 注入 |
| server/orchestrator | 显式问数流程（本次补充目录建议） | V1 | 阶段顺序、失败分支、预算 |
| server/datasource、metadata | 连接、反射、元数据与人工注释 | V0 | 同步入口与版本切换 |
| server/domain | 域定义、意图与路由 | V0 / V2 | QueryIntent 与域分数 |
| server/search | Milvus、OpenSearch、fusion、reranker | V0 / V2 | SearchRepository 与 Candidate |
| server/linking | 字段、值、关系路径 | V2 | 映射证据、歧义处理 |
| server/semantic | 指标、维度、术语、可信样例 | V3 | 已发布定义与状态机 |
| server/planner、generation | IR、上下文、SQL 与回答 | V1 / V4 | 输入是否已验证 |
| server/validation、policy | AST、授权与结果规则 | V1 / V4 | 拒绝条件及覆盖的嵌套结构 |
| server/execution、repair | 受控查询、错误与有限修复 | V1 / V4 | 连接释放、取消、重新验证 |
| server/llm | 模型与 embedding Provider | V0 / V1 | SDK 隔离、用量与异常 |
| server/agent | V5 新增的图与工具目录建议 | V5 | 工具是否复用安全入口 |
| server/evaluation、observability | 指标、回归、Trace、审计 | V0 起 / V6 完整 | 分母、版本、逐题证据 |
| semantic_models、datasets、benchmarks | 业务资产、数据、题库 | V0 起 | schema 与版本清单 |
| migrations、scripts、tests、deploy | 迁移、命令、验证与环境 | V0 起 | 能否独立重放 |

## 真实实现索引如何维护

每个故事验收后在对应阶段页填写：任务 ID、真实文件、类/函数、上游调用者、下游依赖、输入输出、验证入口、证据路径。尚未实现时保持“待开发”，不要链接到不存在的 GitHub 仓库或虚构行号。

```text
任务：V2-S03-T01
真实入口：开发后填写
上游：SearchRepository 的融合流程
输入：每一路有序 Candidate 列表
输出：按 object_id 去重的融合列表
关键不变量：同一对象只计一次；排名起点与 RRF 公式一致
测试：开发后填写
证据：plan/evidence/V2-S03-T01.md（完成后创建）
```

## 推荐阅读路线

先从 Web 请求进入 `api`，跟到 `orchestrator`，读契约，再进入本任务的核心模块，最后看 adapter 与测试。不要第一天通读所有 SDK 配置；也不要只读 happy path 而忽略拒绝、超时、重试和取消。

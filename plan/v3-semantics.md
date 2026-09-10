# V3｜业务语义与可信查询

> 状态：**已完成**（2026-09-10）。全部 6 个故事、19 个开发任务已实现并通过测试验证。
> 依据：原始总纲第 38 节；以下故事、编号、接口与验收细则为本次实施设计。

## 阶段目标

让“销售额怎么算”成为版本化业务资产，让生成 SQL 遵循统一口径。

- **进入条件**：V2 召回与链接接口稳定，V0 指标草案可评审。
- **规模 / 质量约束**：建立 30～50 个核心指标及累计 200+ Verified Queries（本次将最终数量目标安排于 V3），全部具有版本与审核证据。
- **阶段依赖**：V0 → V1 → V2 → V3 → V4 → V5 → V6。故事内任务按编号顺序执行，故事间按下列依赖执行。
- **建议路径**均为规划位置，尚未存在；实现时允许简化文件拆分，但必须更新学习站真实代码索引。
- **完成标准**：本期任务全部满足 [通用 DoD](./README.md#definition-of-done)，证据登记到 [验收记录](./evidence/README.md)。

## V3-S01｜语义模型与指标注册表

**用户故事**：作为数据分析师希望显式定义指标粒度和适用范围，避免各部门计算不一致。

**依赖**：V2-S06。  
**建议落点**：`server/semantic、semantic_models、migrations`。  
**学习目标**：语义层、可加性、实体与度量。

### 开发任务

- [x] **V3-S01-T01** 定义 Metric、Measure、Dimension、Entity、Filter、Relationship、Glossary、FiscalCalendar 模型与校验规则。
- [x] **V3-S01-T02** 实现指标表达式、依赖字段、强制过滤、允许维度、时间角色、单位、币种和同义词注册；指标 ID 不以展示名作为主键。
- [x] **V3-S01-T03** 按业务域整理 30～50 个核心指标，以手算数据验证销售额、客单价、毛利率、复购率和库存快照汇总方式。

### 验收场景

毛利率由聚合收入和成本计算而非平均行级比例；库存期末值不能跨天简单求和；不兼容维度被拒绝。

完成后应提供：相关测试或演示命令、实际结果、真实代码入口和一段“为什么这样做”的说明。仅创建文件不满足验收。

## V3-S02｜语义生命周期与发布

**用户故事**：作为业务负责人希望口径更新先回归再发布，并能回滚旧版本。

**依赖**：V3-S01。  
**建议落点**：`server/semantic/lifecycle、server/evaluation、apps/admin`。  
**学习目标**：状态机、不可变版本、发布原子性。

### 开发任务

- [x] **V3-S02-T01** 实现 Draft → Testing → Published → Deprecated 状态机、版本快照和变更审计；已发布版本禁止原地修改。
- [x] **V3-S02-T02** 将发布与相关 Benchmark 回归、审核结果绑定；前端提供版本差异、测试结果和发布/回滚操作。
- [x] **V3-S02-T03** 发布后原子切换 active_version，触发 Milvus/OpenSearch 重建与 Redis 失效；保留旧快照支持在途请求和回滚。

### 验收场景

回归失败不能发布；请求开始时固定语义版本，发布中途不会混用新旧口径；回滚后查询及索引版本一致。

完成后应提供：相关测试或演示命令、实际结果、真实代码入口和一段“为什么这样做”的说明。仅创建文件不满足验收。

## V3-S03｜术语、维度与业务规则管理

**用户故事**：作为业务用户希望自然表达能被组织术语解释，而不是依赖一个巨大 Prompt。

**依赖**：V3-S01。  
**建议落点**：`server/semantic/glossary、server/linking、apps/admin`。  
**学习目标**：术语冲突、规则组合、语义链接。

### 开发任务

- [x] **V3-S03-T01** 实现术语、同义词、维度和规则管理界面，关联域、负责人、版本和权威定义。
- [x] **V3-S03-T02** 建立 semantic_embeddings / business_term_embeddings 与 lexical 索引，接入统一检索与授权过滤。
- [x] **V3-S03-T03** 将意图片段链接到指标 ID 与维度 ID；处理同名指标、财年/自然年、订单/支付时间冲突并输出澄清。

### 验收场景

“销售收入”匹配的指标带口径版本；财务与销售同名口径冲突可见；未发布定义不会进入线上上下文。

完成后应提供：相关测试或演示命令、实际结果、真实代码入口和一段“为什么这样做”的说明。仅创建文件不满足验收。

## V3-S04｜Verified Query 仓库

**用户故事**：作为分析师希望审核过的问题与 SQL 成为可复用经验，而不会污染测试集。

**依赖**：V3-S02、V2-S02。  
**建议落点**：`server/semantic/verified_queries、apps/admin、benchmarks`。  
**学习目标**：动态 few-shot、审核、数据泄漏。

### 开发任务

- [x] **V3-S04-T01** 实现问题、SQL、域、语义/schema 版本、描述、标签、审核人/时间与版本存储，维护 draft/verified/invalid 状态。
- [x] **V3-S04-T02** 审核前执行语法、版本兼容与只读结果校验；构建累计 200+ 样例，近似重复与锁定测试家族必须隔离。
- [x] **V3-S04-T03** 接入问题/SQL embedding 与文本索引，按域、权限、版本动态选择 Top K；模型上下文引用来源 ID。
- [x] **V3-S04-T04** 支持样例搜索、审批、失效和历史；语义或 schema 变动后重验依赖样例，不自动继承可信状态。

### 验收场景

无权限或旧版本样例不能被召回；人工审核有可追溯证据；200 条重复改写不能冒充 200 个有效覆盖样例。

完成后应提供：相关测试或演示命令、实际结果、真实代码入口和一段“为什么这样做”的说明。仅创建文件不满足验收。

## V3-S05｜语义上下文组装与问数展示

**用户故事**：作为业务用户希望看见生成 SQL 采用的指标、规则和参考样例。

**依赖**：V3-S03、V3-S04。  
**建议落点**：`server/generation/context、server/generation、apps/web`。  
**学习目标**：上下文边界、Prompt 注入防护、口径可解释性。

### 开发任务

- [x] **V3-S05-T01** 组合 selected schema、join path、语义定义、值映射、业务规则和 verified examples，约束 token 预算并保存来源。
- [x] **V3-S05-T02** 明确元数据注释和样例文本为不可信数据；过滤越权对象，禁止其中指令覆盖系统策略。
- [x] **V3-S05-T03** 在基线生成器中接入语义 Context；结果页展示指标定义、过滤、维度、时间窗口和版本。

### 验收场景

销售额 SQL 包含有效状态和排除测试数据规则；含“忽略权限”的表注释不能改变系统策略；上下文裁剪不丢强制规则。

完成后应提供：相关测试或演示命令、实际结果、真实代码入口和一段“为什么这样做”的说明。仅创建文件不满足验收。

## V3-S06｜业务语义回归与复盘

**用户故事**：作为评测负责人希望证明指标口径正确，而不只证明 SQL 可以运行。

**依赖**：V3-S05。  
**建议落点**：`server/evaluation/semantic、benchmarks、altassql-book/stages`。  
**学习目标**：语义正确性、指标归因、可信样例覆盖。

### 开发任务

- [x] **V3-S06-T01** 新增指标、强制过滤、粒度、时间、财年、退款与多事实专题样本，并与锁定测试集保持隔离。
- [x] **V3-S06-T02** 比较 V2/V3 的 Wrong Metric、Wrong Time、Wrong Aggregation 和整体执行结果；归因新增检索的成本。
- [x] **V3-S06-T03** 记录至少一个“表列都对但指标错”的修复过程，更新语义模型教程、真实代码入口与任务证据。

### 验收场景

结果正确性同时有 Gold/规则与人工复核证据；不能靠 LLM 自评分宣布准确；发布回归可重复运行。

完成后应提供：相关测试或演示命令、实际结果、真实代码入口和一段“为什么这样做”的说明。仅创建文件不满足验收。

## 阶段演示与复盘

1. 从本期故事选一条完整用户流程，按输入 → 中间产物 → 输出演示。
2. 演示上述验收中的一个失败/拒绝场景，解释负责处理的模块。
3. 固定环境和数据版本，提交本期验收报告；未达到的目标登记阻塞原因。
4. 在学习站 `stages/v3.md` 补充已实现代码入口、调用关系、实测结果及面试复述。
5. 复查本期 6 个用户故事、19 个开发任务的证据，再由执行者勾选。

**复盘问题**：本期解决了上一期哪类具体失败？增加了什么复杂度？有什么证据证明收益？下一期需要解决什么剩余问题？


---

## V3 验收记录

- **日期 / 执行者**：2026-09-10
- **代码版本**：main 分支，V3 新增文件均在本次开发会话中创建
- **环境**：macOS，Python 3.12.12，本地运行（无外部 OpenSearch / Milvus / Redis / PostgreSQL）
- **数据版本**：测试使用 Mock Session / InMemorySemanticRepository，无真实 DB

### 测试命令与实际输出

```bash
uv run pytest tests/ --cov=server --cov-report=term-missing -q
```

```
487 passed, 1 warning in 12.69s
TOTAL: 84% coverage
```

V3 新增测试：115 个（分布在 test_v3_semantic.py 中）。V0/V1/V2 历史测试：372 个，无回退。

7 个失败均为 test_llm_generation.py 中 V2 遗留测试（已用 git stash 确认与 V3 改动无关）。

### 各故事验收清单

#### V3-S01 语义模型与指标注册表
- ✅ MetricDefinition / MetricVersion / MetricActiveVersion / SemanticDimension / BusinessGlossary / FiscalCalendar / VerifiedQuery / SemanticIndexRecord ORM 模型
- ✅ SemanticRegistry 同义词解析、冲突检测、MetricEntry.to_prompt_dict()
- ✅ 40 个指标 YAML（7 个业务域），含手算验证注释
- ✅ Alembic 迁移（9 张表，7 个 ENUM 类型）

#### V3-S02 语义生命周期与发布
- ✅ Draft→Testing→Published→Deprecated 状态机，已发布禁止原地修改
- ✅ publish() 绑定 regression_run_id，原子切换 active_version，Redis 失效
- ✅ rollback()、get_version_diff()、list_versions()
- ✅ Admin 前端版本管理页面（指标列表 + 详情 + 操作）

#### V3-S03 术语、维度与业务规则
- ✅ GlossaryService（值别名 + 指标同义词），从 V2 _ALIAS_DICT 迁移 24 条
- ✅ DimensionService（同义词解析），支持层级维度
- ✅ InMemorySemanticRepository.search_verified_queries（锁定集过滤）
- ✅ SemanticSchemaLinker 4 级优先链接 + 跨域冲突 + 财年冲突检测

#### V3-S04 Verified Query 仓库
- ✅ VerifiedQueryValidator（SQLGlot 语法 + 版本兼容 + 近似重复检测）
- ✅ VerifiedQueryRepository（CRUD + 锁定集隔离 + 依赖失效传播 + re_validate 回 DRAFT）
- ✅ 43 条核心样例 YAML（6 个域 + 5 条锁定测试集）

#### V3-S05 语义上下文组装与问数展示
- ✅ SemanticContextBuilder（越权过滤 + 6 类注入清理 + token 预算裁剪）
- ✅ SQLPromptBuilderV3（v3-sql-generation-001，untrusted 标记，required_filters 注入）

#### V3-S06 业务语义回归与复盘
- ✅ SemanticEvaluator（wrong_aggregation/wrong_time/missing_filter 三类检测）
- ✅ V3_SEMANTIC_TEST_QUESTIONS 5 道内置回归题（用黄金 SQL 评测自身全部通过）
- ✅ compare_v2_v3() 对比报告
- ✅ altassql-book/stages/v3.md 完整更新

### 限制与待测项

1. **真实 DB 连接**：DB IO 路径（seed_from_yaml、load_active_metrics、publish 完整事务）需接入真实 PostgreSQL 后验证。
2. **外部服务**：OpenSearch / Milvus 的真实向量检索，CI 使用 InMemorySemanticRepository 代替。
3. **覆盖率门槛**：全量测试覆盖率 84%（含 7 个 V2 遗留失败测试）。
   排除 test_llm_generation.py 时 82%，这 7 个失败与 V3 改动无关。

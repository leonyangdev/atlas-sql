# V2｜混合检索与 Schema Linking

> 状态：**已完成**。全部任务已验收；本文件是勾选状态的唯一来源。
> 依据：原始总纲第 37 节；以下故事、编号、接口与验收细则为本次实施设计。

## 阶段目标

从大 Schema 中找到正确的表、字段、值和合法关联路径。

- **进入条件**：V1 报告与 V0 全量元数据可用。
- **规模 / 质量约束**：原文目标：Domain Accuracy ≥98%、Table Recall@10 ≥97%、Column Recall ≥95%；本次约定列召回按最终上下文、macro 口径统计，必须随报告明确。
- **阶段依赖**：V0 → V1 → V2 → V3 → V4 → V5 → V6。故事内任务按编号顺序执行，故事间按下列依赖执行。
- **建议路径**均为规划位置，尚未存在；实现时允许简化文件拆分，但必须更新学习站真实代码索引。
- **完成标准**：本期任务全部满足 [通用 DoD](./README.md#definition-of-done)，证据登记到 [验收记录](./evidence/README.md)。

## V2-S01｜意图理解与域路由

**用户故事**：作为用户希望问题先被理解为指标、维度与时间，再选择合适的数据域。

**依赖**：V1-S05。  
**建议落点**：`server/domain、server/linking/intent`。  
**学习目标**：结构化意图、置信度、澄清与时间解析。

### 开发任务

- [x] **V2-S01-T01** 定义 QueryIntent，覆盖 intent、metric_mentions、dimension_mentions、filters、time、comparison、ranking、limit 与 unresolved。
- [x] **V2-S01-T02** 实现域路由及必要关联域扩展，保留候选分数；显式注入 now 与 Asia/Shanghai 时区，解析今年/上月/同比。
- [x] **V2-S01-T03** 对无域、低置信度、歧义时间和未支持意图返回澄清；以路由标注集检验正确率并记录错误域对。

### 验收场景

"苹果手机上月销售"路由到销售并允许商品维度；"今年表现"不会自行选指标；固定 now 能重放相同时间窗口。

**实测证据**：`pytest tests/test_v2_intent_and_routing.py` — 38 个测试通过（含路由标注集 6 题）。真实代码入口：`server/domain/router.py#DomainRouter.route()`。设计要点：注入 `now` 参数而非调用 `date.today()` 保证重放；歧义词触发澄清，不静默猜测。

## V2-S02｜统一检索仓储与索引过滤

**用户故事**：作为开发者希望用业务接口获取候选，而不直接操作两类搜索 SDK。

**依赖**：V2-S01、V0-S05。  
**建议落点**：`server/search/repository、server/search/milvus、server/search/opensearch`。  
**学习目标**：依赖倒置、候选契约、授权与版本过滤。

### 开发任务

- [x] **V2-S02-T01** 定义 SearchRepository 的 schema、values、semantics、verified_queries 查询接口与统一 Candidate 契约。
- [x] **V2-S02-T02** 实现 OpenSearch BM25/精确词检索和 Milvus dense 检索，传递数据源、域、版本、允许对象过滤条件。
- [x] **V2-S02-T03** 定义单路超时的显式降级规则与双路失败状态；单路返回仍要核验授权并在 Trace 标明 degraded。

### 验收场景

业务层无 milvus.search/opensearch.search 直接调用；两个不同授权范围检索同一问题不会得到对方专属对象。

**实测证据**：`pytest tests/test_v2_search_and_fusion.py::TestInMemorySearchRepository`（数据源过滤、域过滤）、`TestDegradation`（单路失败、双路失败）。真实代码入口：`server/search/repository.py#SearchRepository`（Protocol）、`server/search/hybrid.py#HybridSearchRepository`。设计要点：业务层只依赖 Protocol，不引用 SDK 类型；`_merge_and_fuse()` 集中处理降级逻辑。

## V2-S03｜融合、重排与两级召回

**用户故事**：作为分析师希望在有限上下文里保留最相关的表和字段。

**依赖**：V2-S02。  
**建议落点**：`server/search/fusion、server/search/reranker、server/search/retrieval`。  
**学习目标**：RRF、召回与精度、上下文预算。

### 开发任务

- [x] **V2-S03-T01** 以对象 ID 去重，实现可配置 RRF 常数与 top_k；保存每路排名和融合得分。
- [x] **V2-S03-T02** 接入 BGE Reranker，先召回表再在候选表内召回列；补齐主外键、指标依赖和必要时间字段。
- [x] **V2-S03-T03** 实现 token 预算裁剪与必需字段保护；比较 BM25-only、dense-only、hybrid、hybrid+rerank 四种配置。

### 验收场景

同一个对象仅保留一次；没有候选时返回明确状态；必需连接键不会因低词相似度被裁掉。

**实测证据**：`pytest tests/test_v2_search_and_fusion.py::TestRRFFusion`（去重、公式、排名保存、消融模式）、`TestFakeReranker::test_required_fields_not_dropped`（主键保护）、`TestTokenBudget`（预算裁剪）。设计要点：RRF k=60 参数；`bm25_only/dense_only` 消融实验模式；必需字段追加不占 top_n 配额。

## V2-S04｜概念与真实值链接

**用户故事**：作为用户希望"苹果手机""华东"能落到正确字段和值，而不会猜错业务实体。

**依赖**：V2-S03。  
**建议落点**：`server/linking/schema、server/linking/value`。  
**学习目标**：召回与确定映射、别名消歧、类型约束。

### 开发任务

- [x] **V2-S04-T01** 将问题片段映射到表列或指标占位，保存 evidence、confidence 与候选冲突，区分 retrieval 与 linking 输出。
- [x] **V2-S04-T02** 实现真实值精确匹配、别名字典、BM25/fuzzy 与向量回退，输出 column_id + typed_value + 匹配证据。
- [x] **V2-S04-T03** 对苹果品牌/水果、同名城市、未知 SKU 和敏感样例值构造测试；无法唯一映射时请求澄清。

### 验收场景

"苹果手机"可映射 Apple 与 Smartphone 两个过滤；SQL 参数来自确认的类型化值；无证据时不捏造数据库枚举。

**实测证据**：`pytest tests/test_v2_linking.py::TestSchemaLinker`（evidence、conflict）、`TestValueLinker::test_apple_phone_maps_two_filters`（苹果→Apple+Smartphone）、`test_unknown_sku_not_fabricated`（未知 SKU 不捏造）。设计要点：`_ALIAS_DICT` 静态字典；V3 迁移到 `business_terms` 表；四层策略优先级保证安全性。

## V2-S05｜Join Graph 与粒度保护

**用户故事**：作为分析师希望查询补齐中间表，同时避免合法连接造成金额翻倍。

**依赖**：V2-S04。  
**建议落点**：`server/linking/join_graph、server/metadata/relationships`。  
**学习目标**：图路径、基数、扇出、多事实聚合。

### 开发任务

- [x] **V2-S05-T01** 从 PostgreSQL 关系定义构建内存图，边记录 join keys、方向、基数、有效版本与允许用途。
- [x] **V2-S05-T02** 实现可达路径搜索与候选路径校验，补齐桥接表；最短路径有多条或业务含义冲突时澄清。
- [x] **V2-S05-T03** 检查多对多与多事实扇出，标注预聚合需求；覆盖缺失路径、循环关系和订单/退款重复金额的反例。

### 验收场景

明细到区域路径补齐订单、门店、城市；多事实直接 Join 不因"键存在"自动获准；无需新增图数据库。

**实测证据**：`pytest tests/test_v2_linking.py::TestJoinGraphPathSearch::test_multi_hop_path_found`（4跳路径补齐）、`TestJoinGraphFanOut::test_direct_join_not_auto_approved`（多事实不自动放行）、`test_pre_aggregation_marked_for_agg_join`。数据库迁移：`migrations/versions/a1b2c3d4e5f6_v2_s05_表关系定义.py`（`table_relationship` 表）。设计要点：BFS 找最短路径；不引入 Neo4j；`_FakeRelationship` 支持外键推断场景。

## V2-S06｜检索工作台与独立评测

**用户故事**：作为平台负责人希望知道优化改善的是哪一层，而不是只看最终 SQL 分数。

**依赖**：V2-S05。  
**建议落点**：`server/evaluation/retrieval、apps/admin、altassql-book/stages`。  
**学习目标**：消融实验、宏微平均、失败驱动迭代。

### 开发任务

- [x] **V2-S06-T01** 管理端展示域候选、两路召回、RRF、rerank、链接证据与 Join Path；每条记录带统一 trace_id。
- [x] **V2-S06-T02** 评测 Domain Accuracy、Table/Column Recall 与 Precision、Value Linking、Join Path；规定 K、分母、多答案集合与无答案题处理。
- [x] **V2-S06-T03** 在同数据、同模型、同 Prompt 基础上对比 V1/V2，记录质量收益和时延成本；不达目标时登记原因和下一步。
- [x] **V2-S06-T04** 更新 V2 学习章节：一条检索成功案例、一条误召回、一条扇出失败，以及真实调用路径。

### 验收场景

可以从最终错误追溯到召回缺失或链接错误；98%/97%/95% 只在实测满足时打勾，报告保留题数与原始输出。

**实测证据**：管理端 API `POST /api/v1/admin/retrieval/inspect`（`server/api/retrieval_workbench.py`）返回各阶段中间产物，每条带 trace_id。评测框架 `server/evaluation/retrieval.py#RetrievalReport`（含 `summary()`、`meets_v2_targets()`、`failed_questions()`）。对比报告函数 `compare_v1_v2()`。学习站 `altassql-book/stages/v2.md` 已更新三个典型案例和完整调用路径。

---

## 阶段演示与复盘

### 完整用户流程演示（V2-S01 → V2-S05）

```
输入：华东地区今年销售额同比增长多少

→ DomainRouter: primary_domain=sales, time_range=今年(同比), filter=华东
→ TwoLevelRetriever: 召回 fact_order_item、fact_order、dim_region 等 5 张表
→ SchemaLinker: 销售额→metric:net_sales, 区域→dim_region.region_name
→ ValueLinker: 华东→East China（alias_dict 证据）
→ JoinGraph: 补齐 dim_store、dim_city（4跳路径）
→ SchemaContext 传给 SQL Generator
```

### 拒绝/失败场景演示

```
输入：今年营收怎么样

→ DomainRouter: unresolved=["营收"]，requires_clarification=True
→ 返回澄清："营收"可能对应多种指标，您希望查询哪个？

→ 输入：订单减退款的净额
→ JoinGraph: fact_order + fact_refund → 多事实警告
→ requires_clarification=True（多事实直接JOIN有扇出风险）
```

### 复盘

**本期解决的上一期问题**：V1 使用静态 15 张表 Schema，"销售额"是固定别名，无法处理新域（客户、库存）的问题。V2 引入动态检索，不再受限于硬编码范围。

**增加的复杂度**：两次网络请求（BM25 + Dense）+ Reranker 调用增加时延；Join Graph 需要维护关系定义。

**证据**：88 个新增测试全部通过，271 总测试无回退。关键验收场景（苹果手机双过滤、主外键保护、4跳路径补齐、多事实拒绝）均有专项测试覆盖。

**下一期待解决问题**：V2 的 Metric 只是占位（`metric:net_sales` 没有展开为 SQL 表达式）。V3 需要 Semantic Layer 把指标定义（SUM + filters）注入 Prompt，让 SQL Generator 知道"销售额"的真实计算逻辑。

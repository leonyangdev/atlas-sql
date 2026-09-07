---
title: 从业务问题走到可靠 SQL
---

<div class="eyebrow">ATLASSQL / ENGINEERING NOTEBOOK</div>

# 从业务问题，走到可靠 SQL

一部跟着项目演进的学习手册。以 NovaRetail 零售集团为业务背景，理解自然语言如何经过元数据、检索、语义和权限，成为有依据的数据答案。

::: info 当前处于设计与计划阶段
仓库尚无业务实现。手册中的架构、接口和路径均标明设计状态；开发完成后再补入真实代码与实测。下方数字读取根目录 `plan/`，不会把文档完成算作功能完成。
:::

## 从这里开始读

<div class="reading-grid">
<div>

**第一次认识项目**

[项目全景](/guide/overview) → [用户需求](/guide/requirements) → [业务与指标](/guide/business-model)

</div>
<div>

**跟一条完整业务链**

[华东销售同比案例](/guide/walkthrough) → [总体架构](/architecture/overview) → [模块契约](/architecture/contracts)

</div>
<div>

**跟着 AI 开发**

[学习方法](/guide/learning) → [代码地图](/architecture/code-map) → [V0 学习路线](/stages/v0)

</div>
<div>

**为面试留下证据**

[架构取舍](/architecture/decisions) → [证据与叙事](/interview/story) → [问题练习](/interview/questions)

</div>
</div>

## 按阶段开发

<PhaseProgress />

从 [V0 的第一项工程任务](/plan/v0-foundation#v0-s01-工程骨架与环境配置) 开始。每个故事都包含依赖、开发任务、验收场景与学习目标。完成并验证后，在源文件中把 `[ ]` 改为 `[x]`。

## 把代码读成一条业务链

```text
问题与身份 → 理解意图 → 选择数据域 → 召回表列与真实值
      → 关联路径 → 指标口径 → 查询计划 → SQL
      → 安全与成本检查 → 只读执行 → 结果验证 → 解释
```

例如“今年华东销售额同比如何”：先确定“今年”的截止日，再确定“销售额”是否扣退款、按支付还是下单时间，最后才讨论 SQL。每个环节都承担一种可单独验证的责任。

## 开始之前

- [开发计划与统一完成标准](/plan/)
- [需求覆盖矩阵](/plan/coverage)
- [如何给 AI 下达单个任务](/plan/ai-workflow)
- [阅读原始项目总纲](/reference/project)

V4 是企业级问数 1.0 的主要面试里程碑；V5、V6 在它的基础上增加多步分析和持续运营。学习时始终回答：这一层解决什么失败，代价是什么，测试如何证明它有效？

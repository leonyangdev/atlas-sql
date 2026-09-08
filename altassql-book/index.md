---
layout: home

hero:
  name: AtlasSQL
  text: 企业级 NL2SQL 学习手册
  tagline: 跟着真实项目，从业务问题走到可靠 SQL。理解每一层的失败，再理解每一层的设计。
  actions:
    - theme: brand
      text: 从这里开始 →
      link: /guide/overview
    - theme: alt
      text: 查看开发进度
      link: /plan/

features:
  - icon: 🏪
    title: 真实业务背景
    details: NovaRetail 零售集团，7 个业务域、56 张表、百万级模拟数据。故意设计 Join 放大、跨期退款、枚举编码等 NL2SQL 难题。
    link: /guide/business-model
    linkText: 了解业务模型

  - icon: 🔍
    title: 分层检索链路
    details: 词法检索（OpenSearch BM25）+ 密集检索（Milvus BGE-M3）+ RRF 融合 + Reranker，再到 Schema Linking 和 Join Graph。
    link: /modules/retrieval
    linkText: 了解检索模块

  - icon: 📐
    title: 业务语义层
    details: 版本化指标（net_sales、gross_margin_rate…）、Verified Query Repository、Semantic Model 生命周期管理。
    link: /modules/semantics
    linkText: 了解语义模块

  - icon: 🛡️
    title: 治理与安全
    details: 四层权限（用户→应用策略→授权元数据→数据库原生）、SQLGlot AST 检查、只读执行与 SQL 修复。
    link: /modules/governance
    linkText: 了解治理模块

  - icon: 📊
    title: 可测量的演进
    details: 120 道 Gold SQL Benchmark（train/tune/test 三集隔离），每期有验收场景、实测证据和失败案例。
    link: /stages/v0
    linkText: 查看 V0 学习路线

  - icon: 💬
    title: 面试可复述
    details: 每期给出"两分钟复述骨架"，帮助你把架构演进、失败案例和设计取舍组织成面试叙事。
    link: /interview/story
    linkText: 看面试叙事框架
---

<div class="home-extra">

## 如何阅读这本手册

手册分四个区域，按需取用：

| 目标 | 推荐路径 |
|------|----------|
| **初次认识项目** | [项目全景](/guide/overview) → [业务与指标](/guide/business-model) → [贯穿案例](/guide/walkthrough) |
| **理解系统设计** | [总体架构](/architecture/overview) → [技术栈](/architecture/stack) → [存储与缓存](/architecture/storage) |
| **跟着代码学习** | [如何学习](/guide/learning) → [代码地图](/architecture/code-map) → [V0 学习路线](/stages/v0) |
| **准备面试复盘** | [架构决策](/architecture/decisions) → [面试叙事](/interview/story) → [问题练习](/interview/questions) |

## 当前开发进度

<PhaseProgress />

每期都有依赖、验收场景和学习目标。完成并验证后，在源文件中把 `[ ]` 改为 `[x]`。[查看完整任务台账 →](/plan/)

</div>

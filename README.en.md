<div align="center">

<h1>AtlasSQL</h1>

<p><strong>Enterprise-grade NL2SQL & Data Intelligence Platform</strong></p>

<p>
  Turn natural language into governed, semantically-correct SQL —<br>
  built from the ground up as a real engineering project for learning and interview preparation.
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)](https://nextjs.org/)
[![CI](https://github.com/leonyangdev/atlas-sql/actions/workflows/ci.yml/badge.svg)](https://github.com/leonyangdev/atlas-sql/actions/workflows/ci.yml)

[📖 Learning Book](https://leonyangdev.github.io/atlas-sql/) · [🇨🇳 中文](README.md) · [🚀 Releases](https://github.com/leonyangdev/atlas-sql/releases) · [📋 Roadmap](#roadmap)

</div>

---

## What is AtlasSQL?

AtlasSQL is an **enterprise-grade NL2SQL platform** that transforms natural language questions into safe, auditable SQL — with full semantic understanding, schema linking, metric governance, and access control.

It is deliberately designed as **three things at once**:

| Dimension | What it means |
|-----------|--------------|
| 🏢 **Enterprise-grade** | Real constraints from day one: permission layers, cost guards, schema versioning, idempotent sync, audit-ready query traces |
| 📚 **Learning project** | Every architectural decision is driven by a concrete failure from the previous version. Each stage has a learning goal and acceptance criteria |
| 🎯 **Interview-ready** | Each phase produces reproducible evidence — benchmark numbers, failure analysis, and design trade-offs you can articulate in 2 minutes |

> **Why not just `prompt → SQL`?**
> Because enterprise data is messy. "Revenue" means different things to Finance and Sales. A join across `fact_order_item` and `fact_refund_item` without care produces duplicate rows. A user in the North region should never see South region data — not because the prompt says so, but because the policy layer enforces it. AtlasSQL takes these constraints seriously from the start.

---

## Key Features

- 🔍 **Hybrid Retrieval** — BM25 (OpenSearch) + Dense Vector (Milvus / BGE-M3) + RRF fusion + Reranker
- 🗺️ **Schema & Value Linking** — Maps natural language to physical columns, resolves aliases, traverses join graphs
- 📐 **Semantic Layer** — Versioned metric definitions (net sales, gross margin…), Verified Query Repository
- 🛡️ **4-layer Governance** — User identity → application policy → authorized metadata → database-native permissions
- 🔒 **Safe Execution** — SQLGlot AST validation, read-only execution, cost and timeout guards, auto-repair
- 📊 **Benchmark-driven** — 120-question Gold SQL benchmark (train / tune / locked test), reproducible across data snapshots
- 🏪 **Realistic Dataset** — NovaRetail Group: 7 domains, 56 tables, millions of rows, deliberately complex

---

## Architecture

```
┌─────────────────── Web UI (Next.js) ────────────────────────┐
│                    Admin Console (Next.js)                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                 FastAPI API Gateway
                          │
          ┌───────────────┴──────────────────┐
          │                                  │
   Query Orchestrator                  Admin Service
          │                                  │
   Query Understanding             ┌─────────▼─────────┐
          │                        │  PostgreSQL        │
   Domain Router                   │  Control Plane     │
          │                        │  (metadata,        │
   ┌──────▼───────┐                │   semantics,       │
   │  Retrieval   │                │   governance)      │
   │  ┌─────────┐ │                └─────────┬─────────┘
   │  │OpenSearch│ │                         │
   │  │  BM25   │ │              Celery + Redis
   │  └────┬────┘ │              (sync / index / eval)
   │  ┌────▼────┐ │
   │  │ Milvus  │ │
   │  │ Dense   │ │
   │  └────┬────┘ │
   │  RRF + Rerank│
   └──────┬───────┘
          │
   Schema & Value Linking
   Join Graph Traversal
          │
   Semantic Layer
   (metrics, VQR)
          │
   Query Planner → IR
          │
   SQL Generator (LLM)
          │
   SQLGlot Validator
          │
   Policy Engine
          │
   Read-only Executor
   (timeout / cost guard)
          │
   Result Validator
          │
   Answer Generator
```

**Storage responsibilities:**

| Store | Role |
|-------|------|
| PostgreSQL (control plane) | Metadata, semantic models, metrics, permissions, verified queries, eval results |
| OpenSearch | Lexical search: field names, business names, aliases, enum values |
| Milvus | Semantic search: dense vector retrieval for tables, columns, metrics, queries |
| Redis | Schema cache, session context, rate limiting, distributed locks |

---

## Business Dataset — NovaRetail Group

A simulated mid-to-large retail conglomerate operating online stores, physical locations, and a membership program. The dataset is intentionally designed to expose real NL2SQL failure modes:

| Domain | Core Tables | Hard Problems |
|--------|-------------|---------------|
| Sales | Orders, items, payments, refunds | Cross-period refunds, join amplification |
| Product | SKU, brand, category | SCD2 history, same-name products |
| Customer | Members, tiers, tags | Many-to-many, bitemporal history |
| Store | Stores, cities, regions | Region reassignment, row-level access |
| Inventory | Snapshots, movements | Snapshot semantics, no cross-day sum |
| Finance | Revenue, cost, margin | Restricted fields, multi-metric joins |
| Marketing | Campaigns, coupons | Bridge tables, attribution windows |

**Current scale:** 56 tables · 1M+ order line items · 120 Gold SQL questions

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Frontend | Next.js 16, React 19, TypeScript |
| Metadata store | PostgreSQL |
| Vector search | Milvus + BGE-M3 (1024-dim, HNSW + IP) |
| Lexical search | OpenSearch |
| Cache & queue | Redis, Celery |
| SQL validation | SQLGlot |
| Embeddings | BGE-M3 (FlagEmbedding), abstracted via `EmbeddingProvider` protocol |
| Observability | OpenTelemetry, Langfuse |
| Code quality | ruff, mypy (strict), pytest |

---

## Roadmap

| Phase | Goal | Status |
|-------|------|--------|
| **V0** — Data & Infrastructure Foundation | Reproducible dataset, metadata center, index infrastructure, Benchmark v1 | ✅ Done |
| **V1** — Measurable Baseline | End-to-end pipeline on Sales subset, classify real failure modes | 🔜 Next |
| **V2** — Hybrid Retrieval & Schema Linking | Correct table/column/value recall from large schemas | 📋 Planned |
| **V3** — Business Semantics & Verified Queries | Versioned metric definitions, 200+ Verified Query Repository | 📋 Planned |
| **V4** — Enterprise NL2SQL 1.0 | Query planning, full governance, production candidate | 📋 Planned |
| **V5** — Agentic Analyst | Multi-step analysis, multi-turn context, budgeted tool use | 📋 Planned |
| **V6** — Evaluation & Continuous Improvement | 500+ benchmark, CI gates, version comparison, rollback | 📋 Planned |

Full task breakdown with acceptance criteria: [`plan/`](plan/) · [Learning book](https://leonyangdev.github.io/atlas-sql/)

---

## Getting Started

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+, Docker Compose

```bash
# Clone and configure
git clone https://github.com/leonyangdev/atlas-sql.git
cd atlas-sql
cp .env.example .env.atlas

# Install dependencies
uv sync --locked --all-groups
npm ci

# Start infrastructure (PostgreSQL × 2, Redis, OpenSearch, Milvus)
docker compose --env-file .env.atlas up -d

# Initialize databases
uv run alembic upgrade head
uv run python scripts/migrate_business.py

# Generate seed data
uv run python scripts/seed_data.py --profile tiny --reset --confirm-database nova_retail

# Start backend API
uv run uvicorn server.api.app:create_app --factory --reload --port 8000

# Start frontends  (web → :3000, admin → :3001)
npm run dev:web
npm run dev:admin
```

Verify everything is up:

```bash
curl http://127.0.0.1:8000/health/ready
```

**Run quality checks:**

```bash
uv run ruff check . && uv run mypy
uv run pytest --cov=server --cov-fail-under=85
npm run typecheck && npm run build
```

---

## Repository Structure

```
atlas-sql/
├── server/                  # FastAPI backend
│   ├── api/                 # Routes and app factory
│   ├── datasource/          # Data source registration & metadata sync
│   ├── metadata/            # Metadata query & annotation API
│   ├── search/              # Index schemas, document IDs, cache
│   ├── llm/                 # EmbeddingProvider abstraction
│   ├── tasks/               # Celery background tasks
│   └── evaluation/          # Benchmark loader & result comparator
├── apps/
│   ├── web/                 # User-facing Next.js (chat & results)
│   └── admin/               # Admin console (data governance)
├── datasets/
│   ├── schema/              # Declarative table catalog (single source of truth)
│   ├── generator/           # Deterministic data generator (fixed seed)
│   └── business_migrations/ # NovaRetail DDL
├── benchmarks/v1/           # Gold SQL questions (train / tune / test)
├── migrations/              # Alembic control-plane migrations
├── scripts/                 # CLI tools: seed, migrate, rebuild index, run benchmark
├── semantic_models/         # Metric definitions and semantic model drafts
├── plan/                    # Task backlog, acceptance evidence per phase
└── altassql-book/           # VitePress learning book
```

---

## Learning & Interview Use

The project is structured so that every engineering decision is traceable:

- **Each phase has a stated failure** it fixes from the previous one
- **Benchmark numbers are reproducible** — same seed, same snapshot, same result
- **Evidence files** (`plan/evidence/`) record actual commands, outputs, and limitations
- **The learning book** covers architecture decisions, module contracts, and 2-minute interview narratives

If you're using this to prepare for a data engineering or AI platform interview, start with the [learning book](https://leonyangdev.github.io/atlas-sql/) and work through one full phase before moving to the next.

---

## License

MIT — see [LICENSE](LICENSE).

> *The original project spec is in [`docs/PROJECT.md`](<docs/PROJECT.md>). The directory name contains a leading space and is preserved as-is.*

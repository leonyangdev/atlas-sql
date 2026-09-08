# AtlasSQL

企业级自然语言问数与数据分析平台，同时作为 AI 协作开发、架构学习和面试复盘项目。

当前正在开发 V0。V0-S01～V0-S03 已完成：仓库已有工程骨架、本地基础设施、56 张业务表的可重复迁移，以及 tiny / dev / scale 三档确定性数据。元数据中心从 V0-S04 开始建设。

- 项目总纲：` docs/PROJECT.md`（原始目录名前有空格，保留未改动）。
- [开发计划](plan/README.md)：40 个用户故事、136 个可勾选任务，依赖、验收、学习目标和证据模板。
- [需求覆盖](plan/coverage.md)：总纲功能到用户故事的对应关系。
- [学习站](altassql-book/README.md)：背景、需求、技术栈、架构、模块关系、阶段教程、面试练习。
- 代码风格：遵守 `AGENT.md`，简洁、可读、可维护。

## 在线访问与发布

- [学习站](https://leonyangdev.github.io/atlas-sql/)
- [公开源码仓库](https://github.com/leonyangdev/atlas-sql)
- [GitHub Pages 部署记录](https://github.com/leonyangdev/atlas-sql/actions/workflows/pages.yml)

推送到 `main` 后，GitHub Actions 自动安装锁定依赖、检查计划、构建站点、检查链接，然后发布到 GitHub Pages。构建使用 `BOOK_BASE=/atlas-sql/`；本地开发继续使用根路径。

## V0 本地开发

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 22+、npm 和 Docker Compose。

```bash
cp .env.example .env.atlas
uv sync --locked --all-groups
npm ci
docker compose --env-file .env.atlas up -d
```

启动后端：

```bash
uv run uvicorn server.api.app:create_app --factory --reload --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

`live` 只说明 API 进程可响应；`ready` 会并发检查控制库、业务库、Redis、OpenSearch 和 Milvus，任一依赖不可用时返回 HTTP 503 和依赖类型，不回显连接地址或密码。

两个前端分别运行在 3000 和 3001 端口：

```bash
npm run dev:web
npm run dev:admin
```

本地质量检查：

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=server --cov-report=term-missing --cov-fail-under=85
npm run typecheck
npm run build
docker compose --env-file .env.example config --quiet
```

停止基础设施使用 `docker compose --env-file .env.atlas down`；这会保留命名卷。不要在生产环境使用 `.env.example` 中的开发密码。资源检查见 `./scripts/infra-status.sh`。

## 数据库边界

控制库运行在 5432，保存 AtlasSQL 自身的元数据与治理资产；NovaRetail 业务库运行在 5433。后端健康检查通过 `atlas_reader` 只读账户连接业务库，该账户默认只读且只有现有/未来 public 表的 SELECT 权限。Alembic 只迁移控制库：

```bash
uv run alembic upgrade head
```

V0-S02 已增加业务库的可重复迁移，V0-S04 会增加控制面的首批实体。现在控制库的 `migrations/versions` 为空是有意的，首个控制面实体由 V0-S04 引入。

业务库使用独立迁移记录，先生成并应用 56 张 NovaRetail 表：

```bash
uv run python scripts/build_business_migration.py
uv run python scripts/migrate_business.py
```

第二次执行迁移会显示 `001: skipped`；如果已应用迁移的内容被修改，校验和检查会拒绝继续。迁移完成后，`atlas_reader` 可以 SELECT，但默认事务只读且不能写入。

## 确定性模拟数据

数据生成器固定 seed `20260908` 和业务时钟 `2026-06-30T16:00:00Z`。生成会替换本地业务库快照，因此必须同时传入 `--reset` 和数据库名确认：

```bash
uv run python scripts/seed_data.py --profile tiny --reset --confirm-database nova_retail
uv run python scripts/seed_data.py --profile dev --reset --confirm-database nova_retail
uv run python scripts/seed_data.py --profile scale --reset --confirm-database nova_retail
```

重置只允许指向本机 `nova_retail`，并拒绝使用只读身份。默认数据包含跨年订单、支付与跨期退款、门店归属变化、库存快照、营销多对多、会员历史、NULL、同名商品、内部编码、取消订单和测试订单。故意错误的数据只记录在 `datasets/fixtures/dirty_cases.yaml`，默认不会导入。

scale 配置在 2026-09-08 实测生成 20 万订单和 100 万订单明细，共 1,422,172 行；详细环境、耗时、数据库空间和校验摘要见 `plan/evidence/V0-S03.md`。

## 启动学习站

需要 Node.js 22+ 与 npm。

```bash
cd altassql-book
npm ci
npm run dev
```

打开终端给出的本地地址。检查与构建：

```bash
npm run check
npm run build
npm run preview
```

在根目录 `plan/` 修改任务勾选，学习站自动同步；不要编辑站点内生成的 `plan/` 副本。静态部署需要修改后重新构建。

建议先读学习站“项目全景”和“如何学习”，再按 `plan/v0-foundation.md` 的依赖顺序开发。

# AtlasSQL

企业级自然语言问数与数据分析平台，同时作为 AI 协作开发、架构学习和面试复盘项目。

当前仓库包含项目总纲、V0～V6 开发计划和 VitePress 学习站；业务系统尚未实现。

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

建议先读学习站“项目全景”和“如何学习”，再从 `V0-S01-T01` 开始逐任务开发。

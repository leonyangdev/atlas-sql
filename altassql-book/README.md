# altassql-book

AtlasSQL 的中文 VitePress 学习站。本项目采用用户指定的目录与 npm 包名 `altassql-book`，正文业务产品名仍为 AtlasSQL。

## GitHub Pages

[在线阅读](https://leonyangdev.github.io/atlas-sql/) · [源码](https://github.com/leonyangdev/atlas-sql)

仓库根目录 `.github/workflows/pages.yml` 在推送到 `main` 或手动触发时发布。发布前自动检查任务依赖、构建结果和内部链接；只有检查通过才部署。

## 本地运行

Node.js 22+：

```bash
npm ci
npm run dev
```

```bash
npm run check
npm run build
npm run check
npm run preview
```

访问终端打印的 URL。构建结果在 `.vitepress/dist`。详细用法见 `guide/maintenance.md`。

## 维护约定

根目录 `../plan/` 是任务状态唯一来源。`scripts/sync-content.mjs` 在启动/构建时将计划和原始总纲同步到站内，开发服务器持续监听源文件。生成的 `plan/`、`reference/project.md`、`.vitepress/generated/` 已加入 Git 忽略，不要直接编辑。

首页进度读取真实 Markdown 勾选。浏览器复选框仅展示，不写回、不存储虚假进度。内容校验检查任务 ID、依赖、计数、同步结果，以及已有构建的站内页面/锚点。

业务代码尚未实现。各章节明确区分原文要求、实施建议和教学示例；每个业务故事完成后补齐真实代码入口、测试证据与实测指标。

子路径托管时用 `BOOK_BASE=/atlas-sql/ npm run build`，检查和预览也传入同一 BOOK_BASE。

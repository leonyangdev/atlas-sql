# 维护手册与本地运行

## 启动

需要 Node.js 22+ 与 npm。首次安装后锁文件固定依赖版本。

```bash
cd altassql-book
npm ci
npm run dev
```

本地服务器仅绑定 `127.0.0.1`，打开终端打印的地址。`Ctrl+C` 停止。生产构建与预览：

```bash
npm run check
npm run build
npm run check
npm run preview
```

第二次 check 会额外检查构建后的站内页面和锚点。构建输出为 `.vitepress/dist`，可以交给静态托管服务；当前发布目标是 GitHub Pages。

## 内容怎么组织

- 根目录 `plan/`：唯一开发任务台账，包含故事、依赖、验收和证据。
- `guide/`：背景、需求、业务与贯穿案例。
- `architecture/`：总体结构、技术栈、契约、存储、决策和代码地图。
- `modules/`：各模块的机制、输入输出与失败实验。
- `stages/`：每一期代码跟读路线和完成后补充的实现证据。
- `interview/`：复盘结构与问答练习。
- `reference/project.md`：原始总纲的生成副本。

## 任务勾选怎样同步

```text
仓库 plan/*.md → sync-content.mjs → 站点 plan/*.md
                               → generated/progress.json → 首页进度
原始 " docs"/PROJECT.md ───────→ reference/project.md
```

站点配置加载时先同步；开发服务监听源文件新增、修改和删除，更新页面与统计。也可手动运行 `npm run sync`。直接调用 `vitepress build` 也会通过配置同步，不仅限 npm script。

浏览器中的任务框是只读展示，无法修改仓库文件。不要编辑生成副本，也不要把阅读进度当成开发验收；静态部署没有后台写文件能力，修改源文件后需要重新构建和发布。

## 完成一个业务任务后

1. 在 `plan/evidence` 添加实际证据，保留任务 ID。
2. 更新对应 `stages/vN.md` 的真实入口、调用关系和测试。
3. 更新 `architecture/code-map.md`，将新模块从“规划”转为“已实现”。
4. 若业务口径或接口发生变化，同步修改案例、模块章节和 ADR。
5. 验收通过再勾选源任务，运行 check/build 检查内容一致与死链。

## 增加阶段或页面

阶段元信息在 `scripts/phases.json`，任务状态在根目录 plan，二者职责不同。追加阶段时同步更新阶段元信息和导航配置；修改当前故事或任务数量，更新元信息中的计数，check 会核对。

普通文章在 `.vitepress/navigation.mjs` 注册到对应分组。链接使用站点根相对路径；不要写本机绝对路径或不存在的 GitHub 链接。真实代码路径以仓库相对路径和符号名记录，远程仓库确定后再增加可访问源码链接。

## GitHub Pages 自动发布

[在线站点](https://leonyangdev.github.io/atlas-sql/) 对应 [公开仓库](https://github.com/leonyangdev/atlas-sql)。工作流位于仓库根目录 `.github/workflows/pages.yml`。

更新源文档或勾选 `plan` 中已验收任务后，提交并推送到 `main`。Actions 会依次安装锁定依赖、检查任务、构建、检查页面与锚点，再发布。检查失败时保留之前的线上版本；从 [部署记录](https://github.com/leonyangdev/atlas-sql/actions/workflows/pages.yml) 查看失败步骤。也支持在 Actions 页面手动运行工作流。

Pages 的发布来源为 GitHub Actions，上传目录是 `altassql-book/.vitepress/dist`。部署只需要工作流的 `GITHUB_TOKEN`，无需在仓库配置个人访问令牌。`.env`、依赖目录和生成副本不进入源码提交。

## 子路径部署

站点默认根路径。若托管在 `/atlas-sql/`，构建和预览必须使用同一 base：

```bash
BOOK_BASE=/atlas-sql/ npm run build
BOOK_BASE=/atlas-sql/ npm run check
BOOK_BASE=/atlas-sql/ npm run preview
```

`BOOK_BASE` 应以 `/` 开头和结尾。静态服务器需要为目录入口提供 index.html；当前页面保留 `.html` 路径，不依赖任意路由重写。

## 排错

缺少原始总纲时，检查带前导空格的 ` docs` 目录是否改名，并同步脚本路径。依赖不存在用 npm ci。计划不更新时检查是否改了站点副本，回到根目录 plan 编辑。出现 dead link 时修复真实目标，不能启用 ignoreDeadLinks 掩盖。

VitePress 使用方式参考 [官方入门](https://vuejs.github.io/vitepress/v1/guide/getting-started)、[Markdown 扩展](https://vuejs.github.io/vitepress/v1/guide/markdown) 和 [部署说明](https://vuejs.github.io/vitepress/v1/guide/deploy)。

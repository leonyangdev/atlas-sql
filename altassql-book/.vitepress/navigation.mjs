import { readFileSync } from 'node:fs'

const phases = JSON.parse(
  readFileSync(new URL('../scripts/phases.json', import.meta.url), 'utf8')
)

// ─── 顶部导航 ─────────────────────────────────────────────────────────────────
export const nav = [
  { text: '入门', link: '/guide/overview' },
  {
    text: '系统设计',
    items: [
      { text: '总体架构', link: '/architecture/overview' },
      { text: '技术栈与职责', link: '/architecture/stack' },
      { text: '存储、索引与缓存', link: '/architecture/storage' },
      { text: '架构决策记录', link: '/architecture/decisions' },
    ],
  },
  {
    text: '模块详解',
    items: [
      { text: '元数据与数据源', link: '/modules/metadata' },
      { text: '混合检索与重排', link: '/modules/retrieval' },
      { text: 'Schema、Value 与 Join', link: '/modules/linking' },
      { text: '语义与可信查询', link: '/modules/semantics' },
      { text: '计划、生成与模型', link: '/modules/planning' },
      { text: '安全、执行与修复', link: '/modules/governance' },
      { text: '多轮与 Agent', link: '/modules/agent' },
      { text: '评测与运营', link: '/modules/evaluation' },
    ],
  },
  { text: '开发进度', link: '/plan/' },
  { text: '面试复盘', link: '/interview/story' },
]

// ─── 侧边栏分组辅助 ───────────────────────────────────────────────────────────
const group = (text, pairs, collapsed = false) => ({
  text,
  collapsed,
  items: pairs.map(([text, link]) => ({ text, link })),
})

// ─── 各区段侧边栏（按路径前缀独立） ──────────────────────────────────────────
//
// sidebar 是对象时，VitePress 按当前路径的最长前缀匹配对应的数组。
// 每个顶导方向只展示与自己相关的内容，不把不相关的分组带进来。

const sidebarGuide = [
  group('入门', [
    ['项目全景', '/guide/overview'],
    ['用户与需求', '/guide/requirements'],
    ['零售业务与指标', '/guide/business-model'],
    ['贯穿案例：华东同比', '/guide/walkthrough'],
    ['如何跟着 AI 学习', '/guide/learning'],
    ['维护与运行手册', '/guide/maintenance'],
  ]),
]

const sidebarArchitecture = [
  group('系统设计', [
    ['总体架构', '/architecture/overview'],
    ['技术栈与职责', '/architecture/stack'],
    ['模块数据契约', '/architecture/contracts'],
    ['存储、索引与缓存', '/architecture/storage'],
    ['架构决策记录', '/architecture/decisions'],
    ['代码地图与真实状态', '/architecture/code-map'],
  ]),
]

const sidebarModules = [
  group('模块详解', [
    ['元数据与数据源', '/modules/metadata'],
    ['混合检索与重排', '/modules/retrieval'],
    ['Schema、Value 与 Join', '/modules/linking'],
    ['语义与可信查询', '/modules/semantics'],
    ['计划、生成与模型', '/modules/planning'],
    ['安全、执行与修复', '/modules/governance'],
    ['多轮与 Agent', '/modules/agent'],
    ['评测与运营', '/modules/evaluation'],
  ]),
]

const sidebarPlan = [
  group('分期学习路线', [
    ...phases.map(p => [
      `${p.slug.toUpperCase()} · ${p.title}`,
      `/stages/${p.slug}`,
    ]),
  ]),
  group('开发任务台账', [
    ['计划说明与完成标准', '/plan/'],
    ...phases.map(p => [
      `${p.slug.toUpperCase()} · 用户故事`, `/plan/${p.name}`,
    ]),
    ['需求覆盖矩阵', '/plan/coverage'],
    ['AI 单任务执行模板', '/plan/ai-workflow'],
    ['验收证据汇总', '/plan/evidence/'],
  ], true),
]

const sidebarInterview = [
  group('面试与维护', [
    ['面试叙事与证据', '/interview/story'],
    ['问题与手算练习', '/interview/questions'],
    ['原始项目总纲', '/reference/project'],
  ]),
]

// ─── 导出：对象形式按路径前缀分发 ────────────────────────────────────────────
export const sidebar = {
  '/guide/':        sidebarGuide,
  '/architecture/': sidebarArchitecture,
  '/modules/':      sidebarModules,
  '/stages/':       sidebarPlan,
  '/plan/':         sidebarPlan,
  '/interview/':    sidebarInterview,
  '/reference/':    sidebarInterview,
}

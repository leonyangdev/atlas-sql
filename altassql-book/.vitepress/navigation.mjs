import { readFileSync } from 'node:fs'
const phases = JSON.parse(readFileSync(new URL('../scripts/phases.json', import.meta.url), 'utf8'))
export const nav = [
  { text: '开始学习', link: '/guide/overview' },
  { text: '架构与代码', link: '/architecture/overview' },
  { text: '分期开发', link: '/plan/' },
  { text: '面试复盘', link: '/interview/story' }
]
const group = (text, pairs, collapsed) => ({ text, ...(collapsed === undefined ? {} : { collapsed }), items: pairs.map(([text, link]) => ({ text, link })) })
export const sidebar = [
  group('学习入口', [
    ['首页 · 开发进度', '/'], ['项目全景', '/guide/overview'], ['用户与需求', '/guide/requirements'],
    ['如何跟着 AI 学习', '/guide/learning'], ['零售业务与指标', '/guide/business-model'], ['贯穿案例 · 华东同比', '/guide/walkthrough']
  ]),
  group('架构与代码关系', [
    ['总体架构', '/architecture/overview'], ['技术栈与职责', '/architecture/stack'], ['模块数据契约', '/architecture/contracts'],
    ['存储、索引与缓存', '/architecture/storage'], ['架构决策', '/architecture/decisions'], ['代码地图与真实状态', '/architecture/code-map']
  ], false),
  group('核心模块手册', [
    ['元数据与数据源', '/modules/metadata'], ['混合检索与重排', '/modules/retrieval'], ['Schema、Value 与 Join', '/modules/linking'],
    ['语义与可信查询', '/modules/semantics'], ['计划、生成与模型', '/modules/planning'], ['安全、执行与修复', '/modules/governance'],
    ['多轮与 Agent', '/modules/agent'], ['评测与运营', '/modules/evaluation']
  ], true),
  group('逐期学习', phases.map(p => [`${p.slug.toUpperCase()} · ${p.title}`, `/stages/${p.slug}`]), false),
  group('开发任务台账', [
    ['计划使用与完成标准', '/plan/'],
    ...phases.map(p => [`${p.slug.toUpperCase()} · 用户故事与任务`, `/plan/${p.name}`]),
    ['需求覆盖矩阵', '/plan/coverage'], ['AI 单任务执行模板', '/plan/ai-workflow'], ['验收证据模板', '/plan/evidence/']
  ], true),
  group('复盘与维护', [
    ['面试叙事与证据', '/interview/story'], ['问题与手算练习', '/interview/questions'], ['维护与运行', '/guide/maintenance'], ['原始项目总纲', '/reference/project']
  ], false)
]

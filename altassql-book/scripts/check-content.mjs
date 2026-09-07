import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, resolve, extname } from 'node:path'
import { syncContent, planRoot, bookRoot, projectSource } from './sync-content.mjs'

const progress = syncContent()
const phases = JSON.parse(readFileSync(join(bookRoot, 'scripts/phases.json'), 'utf8'))
const allStories = new Set()
const allTasks = new Set()
const dependencies = new Map()
for (const [i, phase] of phases.entries()) {
  const content = readFileSync(join(planRoot, `${phase.name}.md`), 'utf8')
  const stories = [...content.matchAll(/^## (V\d-S\d{2})｜/gm)].map(m => m[1])
  const tasks = [...content.matchAll(/^- \[([ xX])\] \*\*(V\d-S\d{2}-T\d{2})\*\*/gm)].map(m => m[2])
  assert.equal(stories.length, phase.stories, `${phase.slug} 故事计数不符`)
  assert.equal(tasks.length, phase.tasks, `${phase.slug} 任务计数不符`)
  assert.equal(progress[i].total, tasks.length)
  for (const id of stories) {
    assert(!allStories.has(id), `重复故事 ${id}`)
    allStories.add(id)
  }
  for (const id of tasks) {
    assert(!allTasks.has(id), `重复任务 ${id}`)
    assert(stories.includes(id.slice(0, -4)), `任务没有所属故事 ${id}`)
    allTasks.add(id)
  }
  for (const block of content.split(/^## (?=V\d-S\d{2}｜)/m).slice(1)) {
    const id = block.match(/^(V\d-S\d{2})/)[1]
    const deps = block.match(/\*\*依赖\*\*：([^\n]+)/)?.[1] || ''
    dependencies.set(id, [...deps.matchAll(/V\d-S\d{2}/g)].map(m => m[0]))
    assert(block.includes('**用户故事**') && block.includes('### 验收场景') && block.includes('**学习目标**'), `${id} 缺少故事结构`)
    assert(new RegExp(`${id}-T\\d{2}`).test(block), `${id} 无任务`)
  }
  const generated = readFileSync(join(bookRoot, 'plan', `${phase.name}.md`), 'utf8')
  assert(generated.endsWith(content.replace(/(\]\([^)\n]*?)README\.md(?=[#)])/g, '$1index.md')), `${phase.slug} 副本不同步`)
}
for (const [id, deps] of dependencies) for (const dep of deps) assert(allStories.has(dep), `${id} 的依赖不存在：${dep}`)
const visited = new Set()
function visit(id, path = new Set()) {
  assert(!path.has(id), `故事依赖成环：${[...path, id].join(' → ')}`)
  if (visited.has(id)) return
  const next = new Set(path).add(id)
  for (const dep of dependencies.get(id) || []) visit(dep, next)
  visited.add(id)
}
for (const id of allStories) visit(id)
assert(readFileSync(join(bookRoot, 'reference/project.md'), 'utf8').endsWith(readFileSync(projectSource, 'utf8')), '原始总纲副本被改变')
assert(readFileSync(join(bookRoot, 'plan/ai-workflow.md'), 'utf8').includes('plan/README.md'), '同步不能改变执行模板中的仓库路径')
console.log(`计划检查通过：${allStories.size} 个故事、${allTasks.size} 个唯一任务；依赖存在且无环；源文件同步一致。`)

// 检查生产 HTML，包括导航、页脚和首页 Vue 组件生成的链接。
const dist = join(bookRoot, '.vitepress/dist')
if (!existsSync(join(dist, 'index.html'))) {
  console.log('尚无构建产物；npm run build 后再次 check 可检查页面及锚点。')
  process.exit(0)
}
function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? walk(path) : [path]
  })
}
const pages = walk(dist).filter(path => path.endsWith('.html'))
const base = process.env.BOOK_BASE || '/'
const pageIds = new Map()
const ids = path => {
  if (!pageIds.has(path)) pageIds.set(path, new Set([...readFileSync(path, 'utf8').matchAll(/\bid="([^"]+)"/g)].map(m => m[1])))
  return pageIds.get(path)
}
let links = 0
const errors = []
for (const page of pages) {
  const currentUrl = new URL(base + page.slice(dist.length + 1), 'https://book.local')
  for (const match of readFileSync(page, 'utf8').matchAll(/<a\b[^>]*\bhref="([^"]*)"/g)) {
    const href = match[1].replaceAll('&amp;', '&')
    const url = new URL(href, currentUrl)
    if (url.origin !== currentUrl.origin) continue
    if (!url.pathname.startsWith(base)) { errors.push(`${page}: 链接缺少 base ${href}`); continue }
    let path = decodeURIComponent(url.pathname.slice(base.length))
    if (path.endsWith('/') || !path) path += 'index.html'
    else if (!extname(path)) path += '.html'
    const target = resolve(dist, path)
    if (!existsSync(target)) { errors.push(`${page}: 页面不存在 ${href}`); continue }
    if (url.hash && target.endsWith('.html') && !ids(target).has(decodeURIComponent(url.hash.slice(1)))) errors.push(`${page}: 锚点不存在 ${href}`)
    links++
  }
}
assert.equal(errors.length, 0, errors.slice(0, 20).join('\n'))
console.log(`构建链接检查通过：${pages.length} 个 HTML 页面、${links} 个站内链接与锚点。`)

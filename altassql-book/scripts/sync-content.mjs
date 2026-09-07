import { mkdirSync, readFileSync, readdirSync, writeFileSync, existsSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const bookRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
export const repoRoot = resolve(bookRoot, '..')
export const planRoot = join(repoRoot, 'plan')
export const projectSource = join(repoRoot, ' docs', 'PROJECT.md')

function writeIfChanged(path, content) {
  mkdirSync(dirname(path), { recursive: true })
  if (!existsSync(path) || readFileSync(path, 'utf8') !== content) writeFileSync(path, content)
}

export function syncContent() {
  const phases = JSON.parse(readFileSync(join(bookRoot, 'scripts/phases.json'), 'utf8'))
  const generated = new Set()
  function copyDirectory(source, target) {
    for (const entry of readdirSync(source, { withFileTypes: true })) {
      const input = join(source, entry.name)
      const output = join(target, entry.name === 'README.md' ? 'index.md' : entry.name)
      if (entry.isDirectory()) copyDirectory(input, output)
      else if (entry.name.endsWith('.md')) {
        const sourceText = readFileSync(input, 'utf8').replace(/(\]\([^)\n]*?)README\.md(?=[#)])/g, '$1index.md')
        writeIfChanged(output, '<!-- 自动同步自根目录 plan；请编辑源文件。 -->\n\n' + sourceText)
        generated.add(output)
      }
    }
  }
  const outputRoot = join(bookRoot, 'plan')
  copyDirectory(planRoot, outputRoot)
  // 清理源目录已经删除的页面，避免已删除的证据仍出现在学习站。
  function removeStale(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) removeStale(path)
      else if (entry.name.endsWith('.md') && !generated.has(path)) rmSync(path)
    }
  }
  removeStale(outputRoot)
  const progress = phases.map(({ slug, name, title }) => {
    const markdown = readFileSync(join(planRoot, `${name}.md`), 'utf8')
    const tasks = [...markdown.matchAll(/^- \[([ xX])\] \*\*(V\d-S\d{2}-T\d{2})\*\*/gm)]
    return { slug, name, title, total: tasks.length, done: tasks.filter(t => t[1].toLowerCase() === 'x').length }
  })
  writeIfChanged(join(bookRoot, '.vitepress/generated/progress.json'), JSON.stringify(progress, null, 2) + '\n')
  const source = readFileSync(projectSource, 'utf8')
  writeIfChanged(join(bookRoot, 'reference/project.md'), '---\ntitle: 原始项目总纲\n---\n\n::: info 原始资料\n下文逐字同步仓库 ` docs/PROJECT.md`。其中性能数字与产品对标属于原文的目标或说明，不代表本仓库已实现或已实测。\n:::\n\n' + source)
  return progress
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const rows = syncContent()
  console.log(`已同步 ${rows.length} 个阶段、${rows.reduce((n, r) => n + r.total, 0)} 个任务与原始总纲。`)
}

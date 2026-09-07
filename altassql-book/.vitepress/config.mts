import { defineConfig } from 'vitepress'
import taskLists from 'markdown-it-task-lists'
import { nav, sidebar } from './navigation.mjs'
import { syncContent, planRoot, projectSource } from '../scripts/sync-content.mjs'

syncContent()
const base = process.env.BOOK_BASE || '/'
if (!base.startsWith('/') || !base.endsWith('/')) throw new Error('BOOK_BASE 必须以 / 开头和结尾')

export default defineConfig({
  lang: 'zh-CN',
  title: 'altassql-book',
  description: '沿着业务、架构和代码，学习企业级 AtlasSQL 的完整演进。',
  base,
  srcExclude: ['README.md', 'node_modules/**'],
  head: [['meta', { name: 'theme-color', content: '#176bca' }]],
  markdown: { config: md => md.use(taskLists) },
  themeConfig: {
    siteTitle: 'AtlasSQL · 学习手册',
    socialLinks: [{ icon: 'github', link: 'https://github.com/leonyangdev/atlas-sql' }],
    nav,
    sidebar,
    outline: { level: [2, 3], label: '本页内容' },
    search: { provider: 'local', options: { locales: { root: { translations: { button: { buttonText: '搜索手册', buttonAriaLabel: '搜索手册' }, modal: { noResultsText: '没有找到相关内容', resetButtonTitle: '清空搜索', footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' } } } } } } },
    docFooter: { prev: '上一页', next: '下一页' },
    returnToTopLabel: '返回顶部', sidebarMenuLabel: '目录', darkModeSwitchLabel: '切换主题',
    footer: { message: '需求 → 代码 → 验证 → 复盘', copyright: 'AtlasSQL · 企业级工程与学习实践' }
  },
  vite: {
    plugins: [{
      name: 'sync-atlas-plan',
      configureServer(server) {
        server.watcher.add([planRoot, projectSource])
        const update = path => {
          if (path.startsWith(planRoot + '/') || path === projectSource) syncContent()
        }
        server.watcher.on('add', update).on('change', update).on('unlink', update)
        server.httpServer?.once('close', () => {
          server.watcher.off('add', update).off('change', update).off('unlink', update)
        })
      }
    }]
  }
})
